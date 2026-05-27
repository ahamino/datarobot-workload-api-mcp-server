#!/usr/bin/env python3
"""
WAPI MCP Server - FastMCP Server for the DataRobot Workload API

Exposes tools for managing workloads, artifacts, artifact repositories,
bundles, and querying the OpenAPI specification.
"""

import json
import os
import sys
import time
from functools import wraps
from pathlib import Path
from typing import Optional

import yaml
from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from wapi_mcp.client import WapiClient
from wapi_mcp.helpers import (
    format_created_at,
)
from wapi_mcp.telemetry import (
    LOG,
    init_telemetry,
    trace_span,
    record_tool_call,
    genai_capture_content,
    GEN_AI_OPERATION_NAME,
    GEN_AI_OPERATION_EXECUTE_TOOL,
    GEN_AI_TOOL_NAME,
    GEN_AI_TOOL_TYPE,
    GEN_AI_TOOL_TYPE_FUNCTION,
    GEN_AI_TOOL_DESCRIPTION,
    GEN_AI_TOOL_CALL_ARGUMENTS,
    GEN_AI_TOOL_CALL_RESULT,
    ERROR_TYPE,
    trace_http_client_span,
    HTTP_RESPONSE_STATUS_CODE,
)


def parse_json_param(value, param_name: str):
    """Parse a parameter that may have been stringified by MCP client.

    MCP clients may serialize list/dict params as JSON strings when the
    schema doesn't properly declare type: array. This helper handles both
    cases transparently.
    """
    if value is None:
        return None
    if isinstance(value, (list, dict)):
        return value
    if isinstance(value, str):
        value = value.strip()
        if not value or value in ("null", "None"):
            return None
        try:
            parsed = json.loads(value)
            LOG.debug(f"Parsed stringified {param_name}: {value!r} -> {parsed!r}")
            return parsed
        except json.JSONDecodeError:
            # Not valid JSON, return as-is for validation to catch
            return value
    return value


# Standard (built-in) autoscaling metrics. Custom NIM metric names (containing
# ":") are also accepted and passed through for the API to validate.
STANDARD_SCALING_METRICS = [
    "cpuAverageUtilization",
    "httpRequestsConcurrency",
    "gpuCacheUtilization",
    "gpuRequestQueueDepth",
]
# Metrics whose target is a percentage and must fall in 0..100.
PERCENTAGE_SCALING_METRICS = {"cpuAverageUtilization", "gpuCacheUtilization"}


def validate_autoscaling_policy(metric: str, target, min_count) -> Optional[str]:
    """Validate one autoscaling policy against the spec. Returns an error string
    or None if valid."""
    if metric not in STANDARD_SCALING_METRICS and ":" not in metric:
        return (
            f"Error: autoscaling_metric must be one of {STANDARD_SCALING_METRICS}, or a "
            f"custom NIM metric name (e.g. 'vllm:kv_cache_usage_perc'), got '{metric}'"
        )
    if metric in PERCENTAGE_SCALING_METRICS and target is not None and not (0 <= target <= 100):
        return f"Error: target for {metric} is a percentage and must be between 0 and 100, got {target}"
    # Scale-to-zero is only supported on httpRequestsConcurrency; the CPU/GPU
    # metrics need at least one running replica to read a signal from.
    if min_count is not None and min_count == 0 and metric != "httpRequestsConcurrency":
        return (
            f"Error: minCount=0 (scale-to-zero) is only supported on httpRequestsConcurrency, "
            f"not {metric}. Use minCount>=1."
        )
    return None


# Initialize FastMCP server
mcp = FastMCP("wapi-mcp-server")

# Global client (lazy initialization)
_client: Optional[WapiClient] = None

# Server start time for uptime tracking
_start_time = time.time()


async def get_client() -> WapiClient:
    """Get or create the WapiClient instance."""
    global _client
    if _client is None:
        base_url = os.environ.get("DATAROBOT_API_ENDPOINT", "").strip()
        token = os.environ.get("DATAROBOT_API_TOKEN", "").strip()
        _client = WapiClient(base_url=base_url, token=token)
    return _client


def traced_tool(func):
    """Decorator to add logging, metrics, tracing, and error handling to MCP tools."""
    @wraps(func)
    async def wrapper(*args, **kwargs):
        tool_name = func.__name__
        # First line of the docstring serves as the tool description.
        tool_description = (func.__doc__ or "").strip().split("\n", 1)[0][:1024]
        capture_content = genai_capture_content()
        start_time = time.time()
        LOG.info(f"Tool call: {tool_name}")

        # Serialize input for tracing (truncate to avoid huge spans)
        input_str = json.dumps(kwargs, default=str)[:2000] if kwargs else "{}"

        # OTel GenAI "execute_tool" span conventions, plus the legacy tool.*
        # attributes for back-compat with existing dashboards.
        span_attrs = {
            GEN_AI_OPERATION_NAME: GEN_AI_OPERATION_EXECUTE_TOOL,
            GEN_AI_TOOL_NAME: tool_name,
            GEN_AI_TOOL_TYPE: GEN_AI_TOOL_TYPE_FUNCTION,
            GEN_AI_TOOL_DESCRIPTION: tool_description,
            "tool.name": tool_name,
        }
        if capture_content:
            span_attrs["tool.input"] = input_str
            span_attrs[GEN_AI_TOOL_CALL_ARGUMENTS] = input_str

        # Span name follows the convention: "execute_tool {gen_ai.tool.name}".
        with trace_span(f"{GEN_AI_OPERATION_EXECUTE_TOOL} {tool_name}", span_attrs) as span:
            try:
                result = await func(*args, **kwargs)
                duration_ms = (time.time() - start_time) * 1000
                record_tool_call(tool_name, "success", duration_ms)
                if span:
                    span.set_attribute("tool.status", "success")
                    span.set_attribute("tool.duration_ms", duration_ms)
                    if capture_content:
                        # Truncate output to avoid huge spans
                        output_str = str(result)[:2000] if result else ""
                        span.set_attribute("tool.output", output_str)
                        span.set_attribute(GEN_AI_TOOL_CALL_RESULT, output_str)
                LOG.info(f"Tool {tool_name} completed in {duration_ms:.1f}ms")
                return result

            except Exception as e:
                duration_ms = (time.time() - start_time) * 1000
                error_type = type(e).__name__
                record_tool_call(tool_name, "error", duration_ms, error_type)
                if span:
                    span.set_attribute("tool.status", "error")
                    span.set_attribute(ERROR_TYPE, error_type)
                    span.set_attribute("tool.error_type", error_type)
                    if capture_content:
                        span.set_attribute("tool.output", f"ERROR: {str(e)[:500]}")
                LOG.error(f"Tool {tool_name} failed after {duration_ms:.1f}ms: {e}")

                # Expected, user-actionable failures (API/config errors) are returned
                # as a clean message the agent can act on. Anything else is an
                # unexpected bug — re-raise so it surfaces as a tool error (isError)
                # and in logs/tests, rather than masquerading as a normal result.
                from wapi_mcp.exceptions import WapiAPIError, WapiConfigError
                if isinstance(e, WapiAPIError):
                    return f"API ERROR in {tool_name}:\n\n{str(e)}"
                if isinstance(e, WapiConfigError):
                    return f"CONFIG ERROR in {tool_name}: {e}"
                raise

    return wrapper


# ---------------------------------------------------------------------------
# Health Endpoints
# ---------------------------------------------------------------------------

@mcp.custom_route("/healthz", methods=["GET"])
async def liveness_probe(request: Request) -> JSONResponse:
    """Liveness probe - returns 200 if server is running."""
    with trace_span("health.liveness", {"http.route": "/healthz"}):
        LOG.debug("Liveness probe called")
        return JSONResponse({"status": "ok"})


@mcp.custom_route("/readyz", methods=["GET"])
async def readiness_probe(request: Request) -> JSONResponse:
    """Readiness probe - checks if server can connect to API."""
    with trace_span("health.readiness", {"http.route": "/readyz"}) as span:
        LOG.debug("Readiness probe called")
        try:
            client = await get_client()
            await client.list_bundles()
            if span:
                span.set_attribute("health.status", "ready")
            return JSONResponse({"status": "ready"})
        except Exception as e:
            LOG.warning(f"Readiness probe failed: {e}")
            if span:
                span.set_attribute("health.status", "not_ready")
                span.set_attribute("error.message", str(e))
            return JSONResponse(
                {"status": "not ready", "error": str(e)},
                status_code=503
            )


@mcp.custom_route("/health", methods=["GET"])
async def health_check(request: Request) -> JSONResponse:
    """Detailed health status."""
    with trace_span("health.detailed", {"http.route": "/health"}) as span:
        LOG.debug("Health check called")
        uptime = time.time() - _start_time

        # Check API connectivity
        api_status = "ok"
        api_error = None
        try:
            client = await get_client()
            await client.list_bundles()
        except Exception as e:
            api_status = "error"
            api_error = str(e)
            LOG.warning(f"Health check API connectivity failed: {e}")

        health = {
            "status": "healthy" if api_status == "ok" else "degraded",
            "service": "wapi-mcp-server",
            "uptime_seconds": round(uptime, 2),
            "checks": {
                "api_connectivity": {
                    "status": api_status,
                    "error": api_error,
                }
            }
        }

        if span:
            span.set_attribute("health.status", health["status"])
            span.set_attribute("health.uptime_seconds", uptime)
            span.set_attribute("health.api_connectivity", api_status)

        status_code = 200 if api_status == "ok" else 503
        return JSONResponse(health, status_code=status_code)


# ---------------------------------------------------------------------------
# Shared tool helpers (used by wapi_mcp/tools/*)
# ---------------------------------------------------------------------------


def _format_replacement(r: dict) -> str:
    """Render a Replacement object as a readable summary."""
    config = r.get("config") or {}
    workload_id = r.get("workloadId", "")
    status = r.get("status", "N/A")
    candidate_protons = r.get("candidateProtonIds") or []
    previous_protons = r.get("previousProtonIds") or []
    lines = [
        f"Replacement {r.get('id', 'N/A')}:",
        f"Workload: {workload_id or 'N/A'}",
        f"Status: {status}",
        f"Strategy: {r.get('strategy', 'N/A')}",
        f"Candidate artifact: {r.get('candidateArtifactId', 'N/A')}",
        f"Candidate proton(s): {', '.join(candidate_protons) if candidate_protons else 'N/A'}",
        f"Previous proton(s): {', '.join(previous_protons) if previous_protons else 'N/A'}",
        f"Warmup (min): {config.get('warmupDurationMinutes', 0)}",
        f"Keep old version (min): {config.get('keepOldVersionMinutes', 0)}",
        f"Created: {format_created_at(r.get('createdAt', ''))}",
        f"Switched: {format_created_at(r.get('switchedAt', '')) if r.get('switchedAt') else 'N/A'}",
    ]
    if r.get("message"):
        lines.append(f"Message: {r['message']}")

    # When a replacement fails, the candidate proton is where to look. Point the
    # agent straight at its logs/status instead of having it guess.
    if status == "errored":
        candidate = candidate_protons[0] if candidate_protons else "<candidate-proton-id>"
        lines += [
            "",
            "Replacement FAILED. Debug the candidate proton that did not come up:",
            f'  otel_logs(workload_id="{workload_id}", proton_id="{candidate}")  # candidate logs',
            f'  proton_status_details(workload_id="{workload_id}", proton_id="{candidate}")  # readiness/restarts',
            f'  proton_list(workload_id="{workload_id}")  # roles/status of all protons',
        ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Credential schema helpers (used by wapi_mcp/tools/credentials.py)
# ---------------------------------------------------------------------------

# Cache for credential schemas fetched from OpenAPI spec
_credential_schemas_cache: Optional[dict[str, list[str]]] = None

# Fallback credential keys in case OpenAPI fetch fails
FALLBACK_CREDENTIAL_KEYS = {
    "s3": ["awsAccessKeyId", "awsSecretAccessKey", "awsSessionToken"],
    "basic": ["user", "password"],
    "azure_service_principal": ["azureTenantId", "clientId", "clientSecret"],
    "gcp": ["gcpKey"],
    "api_token": ["apiToken"],
    "bearer": ["token"],
    "oauth": ["token", "refreshToken"],
    "azure": ["azureConnectionString"],
    "azure_sas": ["sasToken"],
    "snowflake_key_pair_user_account": ["privateKeyStr", "passphrase", "user"],
    "databricks_access_token_account": ["databricksAccessToken"],
    "box_jwt": ["enterpriseId", "publicKeyId"],
    "client_id_and_secret": ["clientId", "clientSecret"],
}


async def get_credential_schemas() -> dict[str, list[str]]:
    """Fetch credential schemas from OpenAPI spec and extract field names.

    Returns:
        Dictionary mapping credential type to list of available field names
    """
    global _credential_schemas_cache

    # Return cached value if available
    if _credential_schemas_cache is not None:
        return _credential_schemas_cache

    try:
        client = await get_client()

        # Construct OpenAPI spec URL from base_url
        openapi_url = f"{client.base_url}/openapi.yaml"
        LOG.info(f"Fetching OpenAPI spec from {openapi_url}")

        # Fetch OpenAPI spec
        import aiohttp
        import re
        async with aiohttp.ClientSession() as session:
            async with trace_http_client_span("GET", openapi_url) as span, \
                    session.get(openapi_url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if span:
                    span.set_attribute(HTTP_RESPONSE_STATUS_CODE, resp.status)
                if resp.status != 200:
                    LOG.warning(f"Failed to fetch OpenAPI spec: HTTP {resp.status}")
                    _credential_schemas_cache = FALLBACK_CREDENTIAL_KEYS
                    return _credential_schemas_cache

                spec_text = await resp.text()

        # Parse YAML
        spec = yaml.safe_load(spec_text)

        # Extract credential schemas from components/schemas
        schemas = spec.get("components", {}).get("schemas", {})
        credential_schemas: dict[str, list[str]] = {}

        # Parse CredentialsUpdate schema which has all field definitions
        # with descriptions indicating which credential type each field belongs to
        credentials_update = schemas.get("CredentialsUpdate", {})
        if credentials_update:
            properties = credentials_update.get("properties", {})

            # Parse each field and extract credential types from description
            for field_name, field_def in properties.items():
                if not isinstance(field_def, dict):
                    continue

                description = field_def.get("description", "")

                # Skip non-credential fields
                if field_name in ["name", "description"]:
                    continue

                # Extract credential types from description
                # Pattern: "(applicable for credentialType `type1`, `type2`, ...)"
                # or "(applicable for `type1` only)"
                cred_types_match = re.findall(r'credentialType `([^`]+)`', description)
                cred_types_match.extend(re.findall(r'applicable for `([^`]+)`', description))

                if cred_types_match:
                    # This field belongs to specific credential types
                    for cred_type in cred_types_match:
                        if cred_type not in credential_schemas:
                            credential_schemas[cred_type] = []
                        if field_name not in credential_schemas[cred_type]:
                            credential_schemas[cred_type].append(field_name)
                else:
                    # Check if description gives us a hint about the type
                    # e.g., "AWS access key", "API token", etc.
                    desc_lower = description.lower()
                    if "aws" in desc_lower and "s3" not in credential_schemas:
                        credential_schemas.setdefault("s3", []).append(field_name)
                    elif "api token" in desc_lower:
                        credential_schemas.setdefault("api_token", []).append(field_name)
                    elif "oauth" in desc_lower and "oauth" not in cred_types_match:
                        credential_schemas.setdefault("oauth", []).append(field_name)
                    elif "databricks" in desc_lower:
                        credential_schemas.setdefault("databricks_access_token_account", []).append(field_name)
                    elif "box" in desc_lower:
                        credential_schemas.setdefault("box_jwt", []).append(field_name)
                    elif "azure" in desc_lower and "service principal" in desc_lower:
                        credential_schemas.setdefault("azure_service_principal", []).append(field_name)
                    elif "snowflake" in desc_lower and "key pair" in desc_lower:
                        credential_schemas.setdefault("snowflake_key_pair_user_account", []).append(field_name)
                    elif "gcp" in desc_lower or "google" in desc_lower:
                        credential_schemas.setdefault("gcp", []).append(field_name)

        # Also check for response schemas with single credential type enum
        for schema_name, schema_def in schemas.items():
            if not isinstance(schema_def, dict):
                continue

            properties = schema_def.get("properties", {})

            # Look for schemas with credentialType property that has a single enum value
            if "credentialType" in properties:
                cred_type_prop = properties.get("credentialType", {})
                if "enum" in cred_type_prop and len(cred_type_prop["enum"]) == 1:
                    cred_type = cred_type_prop["enum"][0]
                    # Extract all property names except metadata fields
                    field_names = [
                        prop_name for prop_name in properties.keys()
                        if prop_name not in [
                            "credentialId", "credentialType", "name", "description",
                            "creationDate", "creator", "role"
                        ]
                    ]
                    if field_names and cred_type not in credential_schemas:
                        credential_schemas[cred_type] = field_names

        if credential_schemas:
            LOG.info(f"Extracted {len(credential_schemas)} credential schemas from OpenAPI spec")
            _credential_schemas_cache = credential_schemas
        else:
            LOG.warning("No credential schemas found in OpenAPI spec, using fallback")
            _credential_schemas_cache = FALLBACK_CREDENTIAL_KEYS

    except Exception as e:
        LOG.warning(f"Failed to fetch credential schemas from OpenAPI spec: {e}")
        _credential_schemas_cache = FALLBACK_CREDENTIAL_KEYS

    return _credential_schemas_cache


# ---------------------------------------------------------------------------
# OpenAPI spec helpers (used by wapi_mcp/tools/openapi.py)
# ---------------------------------------------------------------------------

# Path to the bundled OpenAPI spec. Override with OPENAPI_SPEC_PATH; otherwise
# default to the openapi.yaml sitting next to this script, which works both in
# the container (/app/openapi.yaml) and for local/stdio runs from the repo.
OPENAPI_SPEC_PATH = Path(os.environ.get(
    "OPENAPI_SPEC_PATH",
    str(Path(__file__).resolve().parent / "openapi.yaml")
))

_openapi_cache: Optional[dict] = None
_openapi_remote_cache: Optional[dict] = None

REMOTE_SOURCE_ALIASES = {"remote", "master", "live", "server"}


def _load_openapi_spec() -> dict:
    """Load and cache the bundled (local) OpenAPI spec."""
    global _openapi_cache

    if _openapi_cache is None:
        if not OPENAPI_SPEC_PATH.exists():
            raise FileNotFoundError(f"OpenAPI spec not found at {OPENAPI_SPEC_PATH}")
        with open(OPENAPI_SPEC_PATH, "r") as f:
            _openapi_cache = yaml.safe_load(f)
    return _openapi_cache


async def _load_openapi_spec_remote() -> dict:
    """Fetch and cache the live master spec from {DATAROBOT_API_ENDPOINT}/openapi.yaml.

    The bundled spec can lag the deployed API; the remote source is the source of
    truth for whatever environment DATAROBOT_API_ENDPOINT points at.
    """
    global _openapi_remote_cache

    if _openapi_remote_cache is None:
        import aiohttp

        client = await get_client()
        url = f"{client.base_url}/openapi.yaml"
        LOG.info(f"Fetching master OpenAPI spec from {url}")
        headers = {"Authorization": f"Bearer {client.token}"}
        async with aiohttp.ClientSession() as session:
            async with trace_http_client_span("GET", url) as span, \
                    session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if span:
                    span.set_attribute(HTTP_RESPONSE_STATUS_CODE, resp.status)
                if resp.status != 200:
                    raise RuntimeError(
                        f"Failed to fetch master OpenAPI spec from {url}: HTTP {resp.status}"
                    )
                text = await resp.text()
        _openapi_remote_cache = yaml.safe_load(text)
    return _openapi_remote_cache


# Cap on any single read_openapi_spec response so the full spec (~160KB) never
# lands in the agent's context. Targeted lookups (one schema/path) stay well under
# this; anything larger is truncated with guidance to narrow the query.
MAX_OPENAPI_RESPONSE_CHARS = 12000


def _dump_capped(obj, max_chars: int = MAX_OPENAPI_RESPONSE_CHARS) -> str:
    """YAML-dump an object, truncating to keep responses out of context bloat."""
    text = yaml.dump(obj, default_flow_style=False, sort_keys=False)
    if len(text) > max_chars:
        text = (
            text[:max_chars]
            + f"\n\n... [truncated at {max_chars} chars]. Narrow your query — request a "
            "specific schema_name, path, or search term instead of a whole section."
        )
    return text



# ---------------------------------------------------------------------------
# Tool modules
# ---------------------------------------------------------------------------
# The tool modules do `import wapi_mcp_server`. When this file is run directly
# (python wapi_mcp_server.py — the container entrypoint and local stdio), it loads
# as "__main__", so that import would otherwise pull a SECOND, half-initialized
# copy of this module and fail with a circular ImportError. Alias __main__ as
# "wapi_mcp_server" first so the tool imports resolve to this same module.
if __name__ == "__main__":
    sys.modules.setdefault("wapi_mcp_server", sys.modules["__main__"])

# Importing the tool modules (after all shared core/helpers above are defined)
# registers their @mcp.tool functions; the re-exports make them accessible as
# wapi_mcp_server.<tool> for back-compat with tests and existing callers.
from wapi_mcp.tools.otel import (  # noqa: E402,F401
    otel_logs,
    otel_traces,
    otel_trace_get,
    otel_metrics,
)
from wapi_mcp.tools.openapi import read_openapi_spec  # noqa: E402,F401
from wapi_mcp.tools.workloads import (  # noqa: E402,F401
    workload_list,
    workload_search,
    workload_get,
    workload_status,
    workload_create,
    workload_start,
    workload_stop,
    workload_delete,
    workload_update,
    workload_settings_get,
    workload_settings_update,
    workload_stats,
    workloads_stats_summary,
    workload_history,
    workload_events,
    workload_promote,
    workload_related,
)
from wapi_mcp.tools.replacements import (  # noqa: E402,F401
    artifact_replacement_get,
    artifact_replacement_create,
    artifact_replacement_delete,
)
from wapi_mcp.tools.protons import (  # noqa: E402,F401
    proton_list,
    proton_get,
    proton_status_details,
)
from wapi_mcp.tools.artifacts import (  # noqa: E402,F401
    artifact_list,
    artifact_search,
    artifact_get,
    artifact_create,
    artifact_update,
    artifact_clone,
    artifact_build_list,
    artifact_build_trigger,
    artifact_build_get,
    artifact_build_delete,
    artifact_build_logs,
    artifact_lock,
    artifact_delete,
    artifact_repo_list,
    artifact_repo_get,
    artifact_repo_delete,
)
from wapi_mcp.tools.credentials import (  # noqa: E402,F401
    credential_list,
    credential_get,
    credential_keys,
)
from wapi_mcp.tools.bundles import (  # noqa: E402,F401
    bundle_list,
)

# ---------------------------------------------------------------------------
# Main Entry Point
# ---------------------------------------------------------------------------

def main():
    """Main entry point with argument parsing."""
    import argparse

    parser = argparse.ArgumentParser(description="WAPI MCP Server (FastMCP)")
    parser.add_argument(
        "--mode",
        choices=["stdio", "http"],
        default="stdio",
        help="Transport mode: stdio (local) or http (remote/container)",
    )
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Host to bind to in http mode (default: 0.0.0.0)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port to bind to in http mode (default: 8000)",
    )
    args = parser.parse_args()

    # Initialize telemetry
    init_telemetry(LOG)

    if args.mode == "http":
        import uvicorn
        LOG.info(f"Starting WAPI MCP server in HTTP mode on {args.host}:{args.port}")
        # Stateless HTTP: no per-session state is held in the server process, so a
        # client's calls keep working across workload replacements/restarts and
        # scale-out (multiple replicas) without sticky sessions. A stateful server
        # pins each mcp-session-id to one process, so a rolling replacement of this
        # workload would orphan live sessions ("Session not found"). Because there
        # are no sessions, no mcp-session-id header translation is needed.
        app = mcp.http_app(path="/mcp", stateless_http=True)
        uvicorn.run(app, host=args.host, port=args.port)
    else:
        LOG.info("Starting WAPI MCP server in stdio mode")
        mcp.run()


if __name__ == "__main__":
    main()
