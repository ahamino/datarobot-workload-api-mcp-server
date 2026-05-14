#!/usr/bin/env python3
"""
WAPI MCP Server - FastMCP Server for the DataRobot Workload API

Exposes tools for managing workloads, artifacts, artifact repositories,
bundles, and querying the OpenAPI specification.
"""

import json
import os
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
    extract_bundle,
    format_scaling_info,
    wait_for_status,
    wait_for_workload_with_progress,
)
from wapi_mcp.telemetry import LOG, init_telemetry, trace_span, record_tool_call


# ---------------------------------------------------------------------------
# Session Header Translation (Pure ASGI Middleware)
# ---------------------------------------------------------------------------
# The DataRobot gateway strips non-standard headers like `mcp-session-id`.
# Headers prefixed with `x-datarobot-` are preserved.
# This middleware translates between the two without breaking SSE streaming.

def create_session_header_middleware(app):
    """Wrap ASGI app with session header translation."""
    import logging
    mw_log = logging.getLogger("session-middleware")

    async def middleware(scope, receive, send):
        if scope["type"] != "http":
            await app(scope, receive, send)
            return

        # Log all incoming headers for debugging
        headers = list(scope.get("headers", []))
        path = scope.get("path", "")

        if "/mcp" in path:
            header_names = [name.decode() for name, _ in headers]
            mw_log.info(f"[MW] Request to {path} - headers: {header_names}")

        # Look for session ID headers
        dr_session_id = None
        mcp_session_id = None

        for name, value in headers:
            name_lower = name.lower()
            if name_lower == b"x-datarobot-mcp-session-id":
                dr_session_id = value
                mw_log.info(f"[MW] Found x-datarobot-mcp-session-id: {value.decode()[:16]}...")
            elif name_lower == b"mcp-session-id":
                mcp_session_id = value
                mw_log.info(f"[MW] Found mcp-session-id: {value.decode()[:16]}...")

        # Add mcp-session-id header if we found the DataRobot one (and mcp-session-id not already present)
        if dr_session_id and not mcp_session_id:
            headers.append((b"mcp-session-id", dr_session_id))
            scope = dict(scope)
            scope["headers"] = headers
            mw_log.info("[MW] Translated x-datarobot-mcp-session-id -> mcp-session-id")

        # Wrap send to add x-datarobot-mcp-session-id to response
        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                response_headers = list(message.get("headers", []))

                # Find mcp-session-id in response
                mcp_session_id = None
                for name, value in response_headers:
                    if name.lower() == b"mcp-session-id":
                        mcp_session_id = value
                        break

                # Add x-datarobot-mcp-session-id if found
                if mcp_session_id:
                    response_headers.append((b"x-datarobot-mcp-session-id", mcp_session_id))
                    message = dict(message)
                    message["headers"] = response_headers

            await send(message)

        await app(scope, receive, send_wrapper)

    return middleware


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
        start_time = time.time()
        LOG.info(f"Tool call: {tool_name}")

        with trace_span(f"tool/{tool_name}", {"tool.name": tool_name}) as span:
            try:
                result = await func(*args, **kwargs)
                duration_ms = (time.time() - start_time) * 1000
                record_tool_call(tool_name, "success", duration_ms)
                if span:
                    span.set_attribute("tool.status", "success")
                    span.set_attribute("tool.duration_ms", duration_ms)
                LOG.info(f"Tool {tool_name} completed in {duration_ms:.1f}ms")
                return result

            except Exception as e:
                duration_ms = (time.time() - start_time) * 1000
                error_type = type(e).__name__
                record_tool_call(tool_name, "error", duration_ms, error_type)
                if span:
                    span.set_attribute("tool.status", "error")
                    span.set_attribute("tool.error_type", error_type)
                LOG.error(f"Tool {tool_name} failed after {duration_ms:.1f}ms: {e}")

                # Return formatted error message instead of raising
                from wapi_mcp.exceptions import WapiAPIError
                if isinstance(e, WapiAPIError):
                    return f"API ERROR in {tool_name}:\n\n{str(e)}"
                else:
                    return f"ERROR in {tool_name}: {error_type}: {str(e)}"

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
# Workload Tools
# ---------------------------------------------------------------------------

@mcp.tool()
@traced_tool
async def workload_list(
    limit: int = 100,
    offset: int = 0,
    status: Optional[str] = None,
    importance: Optional[str] = None,
    artifact_status: Optional[str] = None,
    artifact_id: Optional[str] = None,
    repository_id: Optional[str] = None,
    created_by: Optional[str] = None,
    tag_keys: Optional[list[str]] = None,
    tag_values: Optional[list[str]] = None,
) -> str:
    """List workloads with optional pagination and filtering.

    Args:
        limit: Maximum number of workloads to return (default: 100)
        offset: Number of workloads to skip for pagination (default: 0)
        status: Filter by proton status. Valid values:
                unknown, submitted, initializing, provisioning, launching,
                running, warming, draining, stopping, stopped, errored, terminated
        importance: Filter by importance (critical, high, moderate, low)
        artifact_status: Filter by artifact status (draft, locked)
        artifact_id: Filter by specific artifact ID
        repository_id: Filter by artifact repository ID
        created_by: Filter by creator user ID
        tag_keys: Filter by tag keys (list)
        tag_values: Filter by tag values (list)
    """
    client = await get_client()

    # Parse list parameters
    tag_keys = parse_json_param(tag_keys, "tag_keys")
    tag_values = parse_json_param(tag_values, "tag_values")

    status_list = [status] if status else None
    importance_list = [importance] if importance else None
    artifact_status_list = [artifact_status] if artifact_status else None

    result = await client.list_workloads(
        limit=limit,
        offset=offset,
        status=status_list,
        importance=importance_list,
        artifact_status=artifact_status_list,
        artifact_id=artifact_id,
        repository_id=repository_id,
        created_by=created_by,
        tag_keys=tag_keys,
        tag_values=tag_values,
        service_stats=True,
    )
    data = result.get("data", [])

    if not data:
        return "No workloads found."

    rows = []
    for w in data:
        wid = w.get("id", "")
        name = w.get("name", "")
        wstatus = w.get("status", "")
        wimportance = w.get("importance", "")
        bundle = extract_bundle(w.get("runtime"))
        created = format_created_at(w.get("createdAt", ""))
        rows.append(f"- {wid}: {name} | status={wstatus} | importance={wimportance} | bundle={bundle} | created={created}")

    return f"Found {len(data)} workloads:\n" + "\n".join(rows)


@mcp.tool()
@traced_tool
async def workload_search(query: str, limit: int = 100, offset: int = 0) -> str:
    """Search workloads by name or other attributes.

    Args:
        query: Search query string
        limit: Maximum number of results (default: 100)
        offset: Number to skip for pagination (default: 0)
    """
    client = await get_client()
    result = await client.list_workloads(limit=limit, offset=offset, search=query)
    data = result.get("data", [])

    if not data:
        return f"No workloads found matching '{query}'."

    rows = []
    for w in data:
        wid = w.get("id", "")
        name = w.get("name", "")
        status = w.get("status", "")
        importance = w.get("importance", "")
        bundle = extract_bundle(w.get("runtime"))
        rows.append(f"- {wid}: {name} | status={status} | importance={importance} | bundle={bundle}")

    return f"Found {len(data)} workloads matching '{query}':\n" + "\n".join(rows)


@mcp.tool()
@traced_tool
async def workload_get(workload_id: str) -> str:
    """Get workload metadata and URLs.

    All workloads have built-in log collection (no configuration needed).
    Use otel_logs(workload_id) to view application logs.

    Args:
        workload_id: The workload ID to retrieve
    """
    client = await get_client()
    workload = await client.get_workload(workload_id)

    name = workload.get("name", "")
    status = workload.get("status", "unknown")
    artifact_id = workload.get("artifactId", "")
    importance = workload.get("importance", "")
    description = workload.get("description", "")
    created_at = format_created_at(workload.get("createdAt", ""))
    runtime = workload.get("runtime")
    bundle = extract_bundle(runtime)
    scaling = format_scaling_info(runtime)
    endpoint = workload.get("endpoint", "")

    ui_url = client._build_url(f"/console-nextgen/workloads/{workload_id}/overview")

    result = f"""Workload: {name}
ID: {workload_id}
Status: {status}
Importance: {importance}
Artifact: {artifact_id}
Bundle: {bundle}
Scaling: {scaling}
Created: {created_at}
Description: {description or "(none)"}

Endpoint URL: {endpoint or "(not running)"}
UI URL: {ui_url}"""

    if status not in ("running", "stopped"):
        result += "\n\nTip: Use workload_status() to see detailed status, conditions, and container logs."

    result += f"""

Logs (built-in): otel_logs("{workload_id}")"""

    return result


@mcp.tool()
@traced_tool
async def workload_status(workload_id: str) -> str:
    """Get detailed workload status including conditions and container logs.

    IMPORTANT: Analyze the conditions and logs carefully to understand what's happening.
    Look for error messages, crash loops, image pull issues, or resource problems.

    For full application logs, use otel_logs(workload_id) - logs are collected automatically.

    Args:
        workload_id: The workload ID to check status for
    """
    client = await get_client()
    workload = await client.get_workload(workload_id)

    status = workload.get("status", "unknown")
    name = workload.get("name", "")
    status_details = workload.get("statusDetails", {})
    log_tail = status_details.get("logTail", [])

    result = f"""=== WORKLOAD STATUS REPORT ===
Workload: {name}
ID: {workload_id}
Current Status: {status}

INSTRUCTIONS FOR AGENT: Analyze the logs below carefully.
- If status is 'errored': Look for the root cause in logs
- If status is 'submitted' or 'initializing': Check if containers are ready
- Look for: CrashLoopBackOff, ImagePullBackOff, OOMKilled, permission errors
- Summarize findings for the user in plain language

"""

    # Display container logs
    result += "=== CONTAINER LOGS (last 30 lines) ===\n"
    if log_tail:
        for line in log_tail[-30:]:
            result += f"{line}\n"

        # Highlight potential issues in logs
        log_text = "\n".join(log_tail[-30:]).lower()
        issues_found = []
        if "error" in log_text:
            issues_found.append("'error' keyword found in logs")
        if "exception" in log_text:
            issues_found.append("'exception' keyword found in logs")
        if "traceback" in log_text:
            issues_found.append("Python traceback detected")
        if "killed" in log_text:
            issues_found.append("Process may have been killed (OOM?)")
        if "permission denied" in log_text:
            issues_found.append("Permission issues detected")
        if "connection refused" in log_text:
            issues_found.append("Connection refused - check network/ports")

        if issues_found:
            result += "\nPOTENTIAL ISSUES DETECTED IN LOGS:\n"
            for issue in issues_found:
                result += f"  - {issue}\n"
    else:
        result += "No container logs available yet.\n"

    # Status-specific guidance
    result += "\n=== STATUS INTERPRETATION ===\n"
    if status == "running":
        result += "Workload is running successfully.\n"
    elif status == "errored":
        result += "Workload has FAILED. Review the logs above to identify the cause.\n"
        result += "   Common causes: image pull failures, crash loops, resource limits, startup errors.\n"
    elif status == "stopped":
        result += "Workload is stopped. Use workload_start to start it.\n"
    elif status in ("submitted", "initializing"):
        result += "Workload is starting. Containers are being created.\n"
        result += "   If stuck here for >5 minutes, check for image pull or resource issues.\n"
    elif status == "stopping":
        result += "Workload is shutting down.\n"
    else:
        result += f"Unknown status: {status}\n"

    return result


@mcp.tool()
@traced_tool
async def workload_create(
    name: str,
    artifact_id: Optional[str] = None,
    image_uri: Optional[str] = None,
    port: int = 8000,
    cpu: float = 1.0,
    memory_bytes: int = 536870912,
    replica_count: int = 1,
    environment_vars: Optional[list[dict]] = None,
    readiness_probe_path: Optional[str] = None,
    liveness_probe_path: Optional[str] = None,
    entrypoint: Optional[list[str]] = None,
    gpu: Optional[int] = None,
    gpu_type: Optional[str] = None,
    resource_bundle_ids: Optional[list[str]] = None,
    autoscaling_enabled: bool = False,
    autoscaling_min: int = 1,
    autoscaling_max: int = 5,
    autoscaling_metric: str = "cpuAverageUtilization",
    autoscaling_target: int = 70,
    importance: str = "low",
    description: Optional[str] = None,
    wait_for_running: bool = False,
    timeout: int = 600,
) -> str:
    """Create a new workload to run a container.

    BEFORE CREATING - REQUIRED STEPS:
    1. Call read_openapi_spec() to understand the API schema and requirements
    2. Call bundle_list() to see available compute bundles (CPU/GPU configs)

    CRITICAL - PORT REQUIREMENTS:
    - The port parameter MUST be >= 1024 (non-privileged ports only)
    - The container application MUST ACTUALLY LISTEN on this port
    - Simply setting port=8080 does NOT make the app listen on 8080!
    - If an image defaults to port 80 or another privileged port, you MUST configure
      the application to listen on a non-privileged port (>= 1024) using:
      * Environment variables (check image docs for PORT, LISTEN_PORT, etc.)
      * Entrypoint override with port flags (ONLY if you know the exact command)
    - NEVER guess entrypoint commands - always look up the image documentation first
    - If unsure how to reconfigure an image's port, search for the image documentation

    MINIMAL EXAMPLE:
        workload_create(name="my-app", image_uri="docker.io/user/myapp:latest")

    WITH GPU (call bundle_list first to see available bundles):
        workload_create(
            name="my-gpu-app",
            image_uri="docker.io/user/myapp:latest",
            resource_bundle_ids=["gpu.l4.small"]
        )

    WITH AUTOSCALING:
        workload_create(
            name="my-app",
            image_uri="docker.io/user/myapp:latest",
            autoscaling_enabled=True,
            autoscaling_min=1,
            autoscaling_max=10,
            autoscaling_metric="httpRequestsConcurrency",
            autoscaling_target=50
        )

    Args:
        name: Workload name (required)
        artifact_id: Use existing artifact ID (don't set image_uri if using this)
        image_uri: Container image (e.g., "docker.io/user/image:tag")
        port: Port the container listens on. MUST be >= 1024!
        cpu: CPU cores (default: 1.0) - used only with inline artifact
        memory_bytes: Memory in bytes (default: 536870912 = 512MB) - used only with inline artifact
        replica_count: Number of replicas (default: 1, ignored if autoscaling enabled)
        environment_vars: MUST BE A LIST like [{"name": "VAR", "value": "val"}]
        readiness_probe_path: Health check path (e.g., "/health", "/readyz")
        liveness_probe_path: Liveness check path (e.g., "/health", "/healthz")
        entrypoint: MUST BE A LIST - NEVER guess, look up image docs first!
        gpu: Number of GPUs for inline artifact (e.g., 1)
        gpu_type: GPU type for inline artifact (e.g., "nvidia-l4")
        resource_bundle_ids: List of bundle IDs from bundle_list() for scheduling
        autoscaling_enabled: Enable autoscaling (default: False)
        autoscaling_min: Minimum replicas when autoscaling (default: 1)
        autoscaling_max: Maximum replicas when autoscaling (default: 5)
        autoscaling_metric: Scaling metric - cpuAverageUtilization, httpRequestsConcurrency,
                           gpuCacheUtilization, gpuRequestQueueDepth (default: cpuAverageUtilization)
        autoscaling_target: Target value for the scaling metric (default: 70)
        importance: Importance level: "low", "moderate", "high", "critical" (default: low)
        description: Optional workload description
        wait_for_running: If True, wait until workload is running (default: False)
        timeout: Wait timeout in seconds (default: 600)

    Returns workload ID and URLs. Use workload_status() to debug issues.
    """
    if not artifact_id and not image_uri:
        return "Error: Must provide either artifact_id or image_uri"

    if artifact_id and image_uri:
        return "Error: Provide either artifact_id OR image_uri, not both"

    # Validate port
    if port < 1024:
        return f"Error: Port must be >= 1024 (got {port}). Non-privileged ports only."

    # Parse list parameters that may have been stringified by MCP client
    environment_vars = parse_json_param(environment_vars, "environment_vars")
    entrypoint = parse_json_param(entrypoint, "entrypoint")
    resource_bundle_ids = parse_json_param(resource_bundle_ids, "resource_bundle_ids")

    # Validate list parameters
    if environment_vars is not None:
        if isinstance(environment_vars, dict):
            return "Error: environment_vars must be a LIST of dicts, not a single dict. Use: [{\"name\": \"VAR\", \"value\": \"val\"}]"
        if not isinstance(environment_vars, list):
            return f"Error: environment_vars must be a list, got {type(environment_vars).__name__}"

    if entrypoint is not None:
        if isinstance(entrypoint, str):
            return f"Error: entrypoint must be a LIST of strings, not a string. Use: [\"python\", \"-m\", \"app\"] instead of \"{entrypoint}\""
        if not isinstance(entrypoint, list):
            return f"Error: entrypoint must be a list, got {type(entrypoint).__name__}"

    if resource_bundle_ids is not None and not isinstance(resource_bundle_ids, list):
        return f"Error: resource_bundle_ids must be a list, got {type(resource_bundle_ids).__name__}"

    # Validate autoscaling metric
    valid_metrics = ["cpuAverageUtilization", "httpRequestsConcurrency", "gpuCacheUtilization", "gpuRequestQueueDepth"]
    if autoscaling_metric not in valid_metrics:
        return f"Error: autoscaling_metric must be one of {valid_metrics}, got '{autoscaling_metric}'"

    client = await get_client()

    # Build runtime config using new GroupRuntime schema
    group_runtime: dict = {"name": "default"}

    # Set replica count or autoscaling
    if autoscaling_enabled:
        group_runtime["autoscaling"] = {
            "enabled": True,
            "policies": [{
                "scalingMetric": autoscaling_metric,
                "target": autoscaling_target,
                "minCount": autoscaling_min,
                "maxCount": autoscaling_max,
            }]
        }
    else:
        group_runtime["replicaCount"] = replica_count

    # Add resource bundles if specified
    if resource_bundle_ids:
        group_runtime["resourceBundles"] = resource_bundle_ids

    runtime: dict = {
        "containerGroups": [group_runtime]
    }

    # Build payload
    payload: dict = {
        "name": name,
        "runtime": runtime,
        "importance": importance,
    }

    if description:
        payload["description"] = description

    if artifact_id:
        # Use existing artifact
        payload["artifactId"] = artifact_id
    else:
        # Create inline artifact
        resource_request: dict = {"cpu": cpu, "memory": memory_bytes}
        if gpu is not None and gpu > 0:
            resource_request["gpu"] = gpu
            if gpu_type:
                resource_request["gpuType"] = gpu_type

        container: dict = {
            "name": "main",
            "imageUri": image_uri,
            "port": port,
            "primary": True,
            "resourceRequest": resource_request,
        }

        if entrypoint:
            container["entrypoint"] = entrypoint

        if environment_vars:
            container["environmentVars"] = environment_vars

        if readiness_probe_path:
            container["readinessProbe"] = {
                "path": readiness_probe_path,
                "port": port,
                "initialDelaySeconds": 10,
            }

        if liveness_probe_path:
            container["livenessProbe"] = {
                "path": liveness_probe_path,
                "port": port,
                "initialDelaySeconds": 30,
            }

        payload["artifact"] = {
            "name": f"{name}-artifact",
            "spec": {
                "type": "service",
                "containerGroups": [{
                    "containers": [container]
                }]
            },
        }

    workload = await client.create_workload(payload)
    workload_id = workload.get("id")

    if not workload_id:
        return f"Workload created but no ID returned: {json.dumps(workload, indent=2)}"

    endpoint = workload.get("endpoint", "")
    ui_url = client._build_url(f"/console-nextgen/workloads/{workload_id}/overview")
    status = workload.get("status", "unknown")

    result = "Workload created successfully!\n\n"
    result += f"ID: {workload_id}\n"
    result += f"Status: {status}\n"
    result += f"Importance: {importance}\n"
    if autoscaling_enabled:
        result += f"Autoscaling: enabled ({autoscaling_min}-{autoscaling_max} replicas, target {autoscaling_metric}={autoscaling_target})\n"
    else:
        result += f"Replicas: {replica_count}\n"
    result += f"Endpoint URL: {endpoint or '(starting...)'}\n"
    result += f"UI URL: {ui_url}\n"
    result += f"\nLogs (built-in): otel_logs(\"{workload_id}\")\n\n"

    if not wait_for_running:
        result += "Poll workload_get every 30-60 seconds until status='running' or 'errored'."
    else:
        result += "Waiting for workload to start...\n"
        try:
            workload, progress_log = await wait_for_workload_with_progress(
                client, workload_id, timeout, poll_interval_seconds=10
            )
            result += f"\n{progress_log}\n"
        except (TimeoutError, RuntimeError) as e:
            result += f"\n{e}\n"
            result += "\nUse workload_get to check current status."

    return result


@mcp.tool()
@traced_tool
async def workload_start(workload_id: str, wait_for_running: bool = False, timeout: int = 600) -> str:
    """Start a stopped workload.

    Args:
        workload_id: The workload ID to start
        wait_for_running: If True, wait for workload to reach 'running' status
        timeout: Timeout in seconds when waiting (default: 600)
    """
    client = await get_client()
    await client.start_workload(workload_id)
    workload = await client.get_workload(workload_id)
    status = workload.get("status", "unknown")

    result = f"Workload {workload_id} start initiated.\n"
    result += f"Current status: {status}\n\n"

    if not wait_for_running:
        result += "Poll workload_get every 30-60 seconds until status='running' or 'errored'."
    else:
        result += "Waiting for workload to start...\n"
        try:
            workload, progress_log = await wait_for_workload_with_progress(
                client, workload_id, timeout, poll_interval_seconds=10
            )
            result += f"\n{progress_log}"
        except (TimeoutError, RuntimeError) as e:
            result += f"\n{e}\n"

    return result


@mcp.tool()
@traced_tool
async def workload_stop(workload_ids: list[str]) -> str:
    """Stop one or more running workloads.

    Args:
        workload_ids: List of workload IDs to stop
    """
    # Parse list parameter that may have been stringified by MCP client
    workload_ids = parse_json_param(workload_ids, "workload_ids")
    if not isinstance(workload_ids, list):
        return f"Error: workload_ids must be a list, got {type(workload_ids).__name__}"

    client = await get_client()
    results = []

    for wid in workload_ids:
        try:
            await client.stop_workload(wid)
            try:
                await wait_for_status(client, "workload", wid, "stopped", 10)
                results.append(f"Stopped {wid}")
            except (TimeoutError, RuntimeError) as e:
                results.append(f"Stop sent to {wid} but: {e}")
        except Exception as e:
            results.append(f"Failed to stop {wid}: {e}")

    return "\n".join(results)


@mcp.tool()
@traced_tool
async def workload_delete(workload_ids: list[str]) -> str:
    """Delete one or more workloads.

    Args:
        workload_ids: List of workload IDs to delete
    """
    # Parse list parameter that may have been stringified by MCP client
    workload_ids = parse_json_param(workload_ids, "workload_ids")
    if not isinstance(workload_ids, list):
        return f"Error: workload_ids must be a list, got {type(workload_ids).__name__}"

    client = await get_client()
    results = []

    for wid in workload_ids:
        try:
            await client.delete_workload(wid)
            results.append(f"Deleted {wid}")
        except Exception as e:
            results.append(f"Failed to delete {wid}: {e}")

    return "\n".join(results)


@mcp.tool()
@traced_tool
async def workload_update(
    workload_id: str,
    name: Optional[str] = None,
    description: Optional[str] = None,
    importance: Optional[str] = None,
) -> str:
    """Update workload properties (name, description, importance).

    Args:
        workload_id: The workload ID to update
        name: New workload name
        description: New workload description
        importance: New importance level: "low", "moderate", "high", "critical"
    """
    client = await get_client()

    payload: dict = {}
    if name is not None:
        payload["name"] = name
    if description is not None:
        payload["description"] = description
    if importance is not None:
        payload["importance"] = importance

    if not payload:
        return "Error: No fields provided to update."

    workload = await client.patch_workload(workload_id, payload)

    return f"""Updated workload {workload_id}:
Name: {workload.get("name", "N/A")}
Description: {workload.get("description", "N/A")}
Importance: {workload.get("importance", "N/A")}
Status: {workload.get("status", "N/A")}"""


@mcp.tool()
@traced_tool
async def workload_settings_get(workload_id: str) -> str:
    """Get workload runtime settings (replica count, autoscaling).

    Args:
        workload_id: The workload ID
    """
    client = await get_client()
    settings = await client.get_workload_settings(workload_id)
    return f"Settings for workload {workload_id}:\n{json.dumps(settings, indent=2)}"


@mcp.tool()
@traced_tool
async def workload_settings_update(
    workload_id: str,
    replica_count: Optional[int] = None,
    resource_bundle_ids: Optional[list[str]] = None,
    autoscaling_enabled: Optional[bool] = None,
    autoscaling_min: Optional[int] = None,
    autoscaling_max: Optional[int] = None,
    autoscaling_metric: Optional[str] = None,
    autoscaling_target: Optional[int] = None,
) -> str:
    """Update workload runtime settings (replica count, resources, autoscaling).

    This triggers a rolling replacement - the workload is redeployed with new settings.

    Args:
        workload_id: The workload ID to update
        replica_count: New fixed replica count (ignored if autoscaling enabled)
        resource_bundle_ids: List of bundle IDs for scheduling (from bundle_list)
        autoscaling_enabled: Enable or disable autoscaling
        autoscaling_min: Minimum replicas when autoscaling
        autoscaling_max: Maximum replicas when autoscaling
        autoscaling_metric: Scaling metric - cpuAverageUtilization, httpRequestsConcurrency,
                          gpuCacheUtilization, gpuRequestQueueDepth
        autoscaling_target: Target value for the scaling metric
    """
    # Parse list parameter that may have been stringified by MCP client
    resource_bundle_ids = parse_json_param(resource_bundle_ids, "resource_bundle_ids")
    if resource_bundle_ids is not None and not isinstance(resource_bundle_ids, list):
        return f"Error: resource_bundle_ids must be a list, got {type(resource_bundle_ids).__name__}"

    # Validate autoscaling metric if provided
    if autoscaling_metric is not None:
        valid_metrics = ["cpuAverageUtilization", "httpRequestsConcurrency", "gpuCacheUtilization", "gpuRequestQueueDepth"]
        if autoscaling_metric not in valid_metrics:
            return f"Error: autoscaling_metric must be one of {valid_metrics}, got '{autoscaling_metric}'"

    client = await get_client()

    # Build group runtime update
    group_runtime: dict = {"name": "default"}
    has_changes = False

    # Handle autoscaling
    if autoscaling_enabled is not None:
        has_changes = True
        if autoscaling_enabled:
            # Build autoscaling policy
            policy: dict = {
                "scalingMetric": autoscaling_metric or "cpuAverageUtilization",
                "target": autoscaling_target or 70,
                "minCount": autoscaling_min or 1,
                "maxCount": autoscaling_max or 5,
            }
            group_runtime["autoscaling"] = {
                "enabled": True,
                "policies": [policy]
            }
        else:
            # Disable autoscaling, use replica count
            group_runtime["autoscaling"] = {"enabled": False}
            if replica_count is not None:
                group_runtime["replicaCount"] = replica_count

    # Handle replica count (when not dealing with autoscaling)
    if replica_count is not None and autoscaling_enabled is None:
        has_changes = True
        group_runtime["replicaCount"] = replica_count

    # Handle resource bundles
    if resource_bundle_ids is not None:
        has_changes = True
        group_runtime["resourceBundles"] = resource_bundle_ids

    if not has_changes:
        return "Error: No settings provided to update."

    runtime: dict = {
        "containerGroups": [group_runtime]
    }

    payload = {"runtime": runtime}
    result = await client.update_workload_settings(workload_id, payload)

    return f"""Settings update initiated for workload {workload_id}.

This triggers a rolling replacement. The workload will be redeployed with new settings.

Replacement ID: {result.get('id', 'N/A')}
Status: {result.get('status', 'N/A')}

Use workload_get({workload_id}) to monitor the replacement.
Use workload_history({workload_id}) to see deployment history."""


@mcp.tool()
@traced_tool
async def workload_stats(workload_id: str) -> str:
    """Get performance statistics for a workload.

    Args:
        workload_id: The workload ID to get stats for
    """
    client = await get_client()
    stats = await client.get_workload_stats(workload_id)

    metrics = stats.get("metrics", {})
    period = stats.get("period", {})

    result = f"=== Stats for workload {workload_id} ===\n"
    if period:
        result += f"Period: {period.get('start', 'N/A')} to {period.get('end', 'N/A')}\n"

    result += f"""
Requests:
  Total: {metrics.get('totalRequests', 0)}
  Per minute: {metrics.get('requestsPerMinute', 0)}
  Concurrent: {metrics.get('concurrentRequests', 0)}

Response Time: {metrics.get('responseTime', 0)}ms

Errors:
  User errors (4xx): {metrics.get('userErrors', 0)} ({metrics.get('userErrorRate', 0):.2%})
  Server errors (5xx): {metrics.get('serverErrors', 0)} ({metrics.get('serverErrorRate', 0):.2%})
  Total error rate: {metrics.get('totalErrorRate', 0):.2%}

Slow requests: {metrics.get('slowRequests', 0)}
"""
    return result


@mcp.tool()
@traced_tool
async def workloads_stats_summary(
    status: Optional[str] = None,
    importance: Optional[str] = None,
    artifact_status: Optional[str] = None,
    created_by: Optional[str] = None,
    search: Optional[str] = None,
) -> str:
    """Get aggregated statistics across all workloads.

    Returns summary counts by status and importance level.

    Args:
        status: Filter by proton status. Valid values:
                unknown, submitted, initializing, provisioning, launching,
                running, warming, draining, stopping, stopped, errored, terminated
        importance: Filter by importance (critical, high, moderate, low)
        artifact_status: Filter by artifact status (draft, locked)
        created_by: Filter by creator user ID
        search: Search query for name/description
    """
    client = await get_client()

    status_list = [status] if status else None
    importance_list = [importance] if importance else None
    artifact_status_list = [artifact_status] if artifact_status else None

    stats = await client.get_all_workloads_stats(
        status=status_list,
        importance=importance_list,
        artifact_status=artifact_status_list,
        created_by=created_by,
        search=search,
    )

    by_status = stats.get("byStatus", {})
    by_importance = stats.get("byImportance", {})
    total = stats.get("total", 0)

    result = "=== Workloads Summary ===\n"
    result += f"Total: {total}\n\n"

    result += "By Status:\n"
    for s, count in by_status.items():
        result += f"  {s}: {count}\n"

    result += "\nBy Importance:\n"
    for imp, count in by_importance.items():
        result += f"  {imp}: {count}\n"

    return result


@mcp.tool()
@traced_tool
async def workload_history(workload_id: str, limit: int = 10) -> str:
    """Get artifact deployment history for a workload.

    Shows the history of artifact versions deployed to this workload.

    Args:
        workload_id: The workload ID
        limit: Maximum number of history entries (default: 10)
    """
    client = await get_client()
    result = await client.get_workload_history(workload_id, limit=limit)
    data = result.get("data", [])

    if not data:
        return f"No deployment history for workload {workload_id}."

    rows = []
    for h in data:
        hid = h.get("id", "")
        artifact_id = h.get("artifactId", "")
        status = h.get("status", "")
        reason = h.get("reason", "")
        deployed_at = format_created_at(h.get("deployedAt", ""))
        retired_at = h.get("retiredAt")

        row = f"- {hid[:8]}: artifact={artifact_id[:8]} | status={status} | deployed={deployed_at}"
        if retired_at:
            row += f" | retired={format_created_at(retired_at)}"
        if reason:
            row += f" | reason={reason}"
        rows.append(row)

    return f"Deployment history for workload {workload_id} ({len(data)} entries):\n" + "\n".join(rows)


@mcp.tool()
@traced_tool
async def workload_events(workload_id: str, limit: int = 50) -> str:
    """Get events for a workload (status changes, errors, etc.).

    Args:
        workload_id: The workload ID
        limit: Maximum number of events (default: 50)
    """
    client = await get_client()
    result = await client.get_workload_events(workload_id, limit=limit)
    events = result.get("data", result.get("events", []))

    if not events:
        return f"No events found for workload {workload_id}."

    rows = []
    for e in events[:limit]:
        event_type = e.get("eventType", "")
        timestamp = format_created_at(e.get("timestamp", ""))
        details = e.get("details", {})
        rows.append(f"- [{timestamp}] {event_type}: {json.dumps(details)}")

    return f"Events for workload {workload_id} ({len(events)} total):\n" + "\n".join(rows)


@mcp.tool()
@traced_tool
async def workload_promote(workload_id: str) -> str:
    """Promote a workload's draft artifact to locked (production).

    This locks the currently running draft artifact, making it immutable.
    The workload continues running the same artifact, which is now assigned
    a version number. Workload stats are reset.

    Prerequisites:
    - Workload must be running a DRAFT artifact
    - No replacement can be in progress

    Args:
        workload_id: The workload ID to promote
    """
    client = await get_client()
    workload = await client.promote_workload(workload_id)

    artifact_id = workload.get("artifactId", "")
    artifact = workload.get("artifact", {})
    version = artifact.get("version", "")
    status = workload.get("status", "")

    return f"""Workload promoted successfully!

Workload: {workload_id}
Status: {status}
Artifact: {artifact_id}
Version: v{version}
Artifact Status: {artifact.get("status", "locked")}

The artifact is now locked and immutable.
Stats have been reset."""


@mcp.tool()
@traced_tool
async def proton_list(workload_id: str, limit: int = 10, offset: int = 0) -> str:
    """List protons (deployment instances) for a workload.

    A proton represents a running deployment of an artifact on a workload.
    Workloads may have multiple protons during rolling updates.

    Args:
        workload_id: The workload ID
        limit: Maximum number of protons to return (default: 10)
        offset: Number to skip for pagination (default: 0)
    """
    client = await get_client()
    result = await client.list_workload_protons(workload_id, limit=limit, offset=offset)
    data = result.get("data", [])

    if not data:
        return f"No protons found for workload {workload_id}."

    rows = []
    for p in data:
        pid = p.get("id", "")
        status = p.get("status", "")
        role = p.get("role", "")
        artifact_id = p.get("artifactId", "")
        created = format_created_at(p.get("createdAt", ""))
        running_since = p.get("runningSince")
        endpoint = p.get("endpoint", "")

        row = f"- {pid[:12]}: status={status} | role={role} | artifact={artifact_id[:12]} | created={created}"
        if running_since:
            row += f" | running_since={format_created_at(running_since)}"
        if endpoint:
            row += f"\n    endpoint: {endpoint}"
        rows.append(row)

    return f"Found {len(data)} protons for workload {workload_id}:\n" + "\n".join(rows)


@mcp.tool()
@traced_tool
async def proton_get(workload_id: str, proton_id: str) -> str:
    """Get details of a specific proton.

    Args:
        workload_id: The workload ID
        proton_id: The proton ID to retrieve
    """
    client = await get_client()
    proton = await client.get_workload_proton(workload_id, proton_id)

    return f"""Proton {proton_id}:
Workload: {workload_id}
Status: {proton.get("status", "")}
Role: {proton.get("role", "")}
Artifact ID: {proton.get("artifactId", "")}
Endpoint: {proton.get("endpoint", "(none)")}
Created: {format_created_at(proton.get("createdAt", ""))}
Running Since: {format_created_at(proton.get("runningSince", "")) or "(not running)"}

Runtime:
{json.dumps(proton.get("runtime", {}), indent=2)}

Status Details:
{json.dumps(proton.get("statusDetails", {}), indent=2)}"""


@mcp.tool()
@traced_tool
async def proton_status_details(workload_id: str, proton_id: str) -> str:
    """Get per-replica status details for a proton.

    Shows detailed information about each replica (pod) including:
    - Overall status with human-readable summary
    - Per-replica phase (pending, running, succeeded, failed, unknown)
    - Container status (running, waiting, terminated, unknown)
    - Restart counts and ready state
    - Node addresses
    - Readiness conditions (PodScheduled, Initialized, ContainersReady, Ready)

    Use this for debugging deployment issues.

    Args:
        workload_id: The workload ID
        proton_id: The proton ID
    """
    client = await get_client()
    try:
        details = await client.get_proton_status_details(workload_id, proton_id)
    except Exception as e:
        if "204" in str(e) or "No content" in str(e).lower():
            return f"No status details available yet for proton {proton_id}. The proton may still be initializing."
        raise

    if not details:
        return f"No status details available for proton {proton_id}."

    # Parse overall status (WorkloadMonitorOverallStatus)
    overall = details.get("overallStatus", {})
    overall_state = overall.get("state", "unknown") if isinstance(overall, dict) else str(overall)
    overall_summary = overall.get("summary", "") if isinstance(overall, dict) else ""
    last_updated = overall.get("lastUpdated", "") if isinstance(overall, dict) else ""

    replicas = details.get("replicas", [])

    result = f"""=== PROTON STATUS DETAILS ===
Proton: {proton_id}
Overall State: {overall_state}
Summary: {overall_summary}
Last Updated: {last_updated}
Replicas: {len(replicas)}

"""

    for replica in replicas:
        name = replica.get("name", "")
        # ReplicaPhase: pending, running, succeeded, failed, unknown
        status = replica.get("status", "")
        address = replica.get("address", "")
        node_address = replica.get("nodeAddress", "")
        started_at = replica.get("startedAt", "")

        result += f"--- Replica: {name} ---\n"
        result += f"Phase: {status}\n"
        result += f"Address: {address}\n"
        result += f"Node: {node_address}\n"
        result += f"Started: {started_at or '(not started)'}\n"

        # Conditions (PodScheduled, Initialized, ContainersReady, Ready)
        conditions = replica.get("conditions", [])
        if conditions:
            result += "Conditions:\n"
            for cond in conditions:
                ctype = cond.get("type", "")
                met = cond.get("met")
                since = cond.get("since", "")
                status_icon = "[OK]" if met else "[--]"
                result += f"  {status_icon} {ctype}: {since}\n"

        # Containers (ContainerStatusDetail)
        containers = replica.get("containers", [])
        if containers:
            result += "Containers:\n"
            for cont in containers:
                cname = cont.get("name", "")
                # ContainerStatus: running, waiting, terminated, unknown
                cstatus = cont.get("status", "")
                ready = cont.get("ready", False)
                restarts = cont.get("restartCount", 0)
                image = cont.get("image", "")
                cstarted = cont.get("startedAt", "")
                ready_icon = "[OK]" if ready else "[--]"
                result += f"  {ready_icon} {cname}: {cstatus} (restarts: {restarts})\n"
                result += f"      image: {image}\n"
                if cstarted:
                    result += f"      started: {cstarted}\n"

        result += "\n"

    return result


@mcp.tool()
@traced_tool
async def workload_related(workload_id: str) -> str:
    """Get entities related to a workload (artifacts, etc.).

    Shows artifacts and other resources linked to this workload.

    Args:
        workload_id: The workload ID
    """
    client = await get_client()
    result = await client.get_workload_related(workload_id)

    data = result.get("data", [])
    count = result.get("count", len(data))

    if not data:
        return f"No related entities found for workload {workload_id}."

    rows = []
    for item in data:
        item_id = item.get("id", "")
        item_type = item.get("type", "")
        name = item.get("name", "")
        created = format_created_at(item.get("createdAt", ""))
        rows.append(f"- {item_type}: {item_id} ({name}) | created={created}")

    return f"Related entities for workload {workload_id} ({count} total):\n" + "\n".join(rows)


# ---------------------------------------------------------------------------
# Artifact Tools
# ---------------------------------------------------------------------------

@mcp.tool()
@traced_tool
async def artifact_list(limit: int = 100, offset: int = 0, status: Optional[str] = None) -> str:
    """List artifacts with optional pagination and filtering.

    Args:
        limit: Maximum number of artifacts to return (default: 100)
        offset: Number of artifacts to skip (default: 0)
        status: Filter by status: 'draft' or 'locked'
    """
    client = await get_client()
    result = await client.list_artifacts(limit=limit, offset=offset, status=status)
    data = result.get("data", [])

    if not data:
        return "No artifacts found."

    rows = []
    for a in data:
        aid = a.get("id", "")
        name = a.get("name", "")
        astatus = a.get("status", "")
        atype = a.get("type", "")
        version = a.get("version", "")
        repo_id = a.get("artifactRepositoryId", "")
        rows.append(f"- {aid}: {name} | type={atype} | status={astatus} | v{version or 'N/A'} | repo={repo_id or 'none'}")

    return f"Found {len(data)} artifacts:\n" + "\n".join(rows)


@mcp.tool()
@traced_tool
async def artifact_search(query: str, limit: int = 100, offset: int = 0) -> str:
    """Search artifacts by name or other attributes.

    Args:
        query: Search query string
        limit: Maximum number of results (default: 100)
        offset: Number to skip for pagination (default: 0)
    """
    client = await get_client()
    result = await client.list_artifacts(limit=limit, offset=offset, search=query)
    data = result.get("data", [])

    if not data:
        return f"No artifacts found matching '{query}'."

    rows = []
    for a in data:
        aid = a.get("id", "")
        name = a.get("name", "")
        astatus = a.get("status", "")
        atype = a.get("type", "")
        rows.append(f"- {aid}: {name} | type={atype} | status={astatus}")

    return f"Found {len(data)} artifacts matching '{query}':\n" + "\n".join(rows)


@mcp.tool()
@traced_tool
async def artifact_get(artifact_id: str) -> str:
    """Get details of a specific artifact.

    Args:
        artifact_id: The artifact ID to retrieve
    """
    client = await get_client()
    artifact = await client.get_artifact(artifact_id)
    return f"Artifact {artifact_id}:\n{json.dumps(artifact, indent=2)}"


@mcp.tool()
@traced_tool
async def artifact_create(
    name: str,
    image_uri: str,
    port: int = 8000,
    cpu: float = 1.0,
    memory_bytes: int = 536870912,
    description: Optional[str] = None,
    environment_vars: Optional[list[dict]] = None,
    readiness_probe_path: Optional[str] = None,
    liveness_probe_path: Optional[str] = None,
    entrypoint: Optional[list[str]] = None,
    gpu: Optional[int] = None,
    gpu_type: Optional[str] = None,
    artifact_type: str = "service",
) -> str:
    """Create a new container artifact (reusable workload template).

    Artifacts define container configuration. They start in 'draft' status
    allowing iteration. Use artifact_lock to make them immutable ('locked').

    IMPORTANT SCHEMA REQUIREMENTS:
    - type must be "service" (default) or "nim" for NVIDIA NIMs
    - Port must be >= 1024 (non-privileged ports only)
    - CPU and memory are REQUIRED for resourceRequest
    - For GPU artifacts, specify both gpu (count) and gpu_type
    - Entrypoint must be array of strings: ["python", "-m", "app"]

    Args:
        name: Artifact name (required)
        image_uri: Container image URI (e.g., "docker.io/user/image:tag")
        port: Container port, must be >= 1024 (default: 8000)
        cpu: CPU cores to allocate (default: 1.0)
        memory_bytes: Memory in bytes (default: 536870912 = 512MB)
        description: Optional artifact description
        environment_vars: List of {"name": "VAR", "value": "val"} environment variables
        readiness_probe_path: HTTP path for readiness probe (e.g., "/readyz")
        liveness_probe_path: HTTP path for liveness probe (e.g., "/healthz")
        entrypoint: Container entrypoint as array (e.g., ["python", "-m", "myapp"])
        gpu: Number of GPUs to allocate (e.g., 1)
        gpu_type: GPU type when gpu > 0 (e.g., "nvidia-l4", "nvidia-a10g")
        artifact_type: "service" (default) or "nim"

    Returns artifact in 'draft' status. Use artifact_lock to make immutable.
    """
    if port < 1024:
        return f"Error: Port must be >= 1024 (got {port}). Non-privileged ports only."

    # Parse list parameters that may have been stringified by MCP client
    environment_vars = parse_json_param(environment_vars, "environment_vars")
    entrypoint = parse_json_param(entrypoint, "entrypoint")

    client = await get_client()

    # Build resource request
    resource_request: dict = {"cpu": cpu, "memory": memory_bytes}
    if gpu is not None and gpu > 0:
        resource_request["gpu"] = gpu
        if gpu_type:
            resource_request["gpuType"] = gpu_type

    # Build container spec
    container: dict = {
        "name": "main",
        "imageUri": image_uri,
        "port": port,
        "primary": True,
        "resourceRequest": resource_request,
    }

    if entrypoint:
        container["entrypoint"] = entrypoint

    if environment_vars:
        container["environmentVars"] = environment_vars

    if readiness_probe_path:
        container["readinessProbe"] = {
            "path": readiness_probe_path,
            "port": port,
            "initialDelaySeconds": 10,
        }

    if liveness_probe_path:
        container["livenessProbe"] = {
            "path": liveness_probe_path,
            "port": port,
            "initialDelaySeconds": 30,
        }

    # Build artifact payload
    payload: dict = {
        "name": name,
        "spec": {
            "type": artifact_type,
            "containerGroups": [{
                "containers": [container]
            }]
        },
    }

    if description:
        payload["description"] = description

    artifact = await client.create_artifact(payload)
    artifact_id = artifact.get("id", "")

    return f"""Created artifact: {artifact_id}
Name: {name}
Type: {artifact_type}
Image: {image_uri}
Status: {artifact.get("status", "draft")}

Use this artifact_id when calling workload_create with artifact_id parameter.
To make immutable for production: artifact_lock(artifact_id="{artifact_id}")

Full response:
{json.dumps(artifact, indent=2)}"""


@mcp.tool()
@traced_tool
async def artifact_update(
    artifact_id: str,
    name: Optional[str] = None,
    description: Optional[str] = None,
    image_uri: Optional[str] = None,
    port: Optional[int] = None,
    cpu: Optional[float] = None,
    memory_bytes: Optional[int] = None,
    environment_vars: Optional[list[dict]] = None,
    readiness_probe_path: Optional[str] = None,
    liveness_probe_path: Optional[str] = None,
    entrypoint: Optional[list[str]] = None,
    gpu: Optional[int] = None,
    gpu_type: Optional[str] = None,
) -> str:
    """Update an existing draft artifact (PATCH).

    Only artifacts with status='draft' can be updated.
    Provide only the fields you want to change.

    IMPORTANT: After updating, restart any workloads using this artifact
    to pick up the changes (workload_stop then workload_start).

    Args:
        artifact_id: The artifact ID to update
        name: New artifact name
        description: New artifact description
        image_uri: New container image URI
        port: New container port (must be >= 1024)
        cpu: New CPU allocation
        memory_bytes: New memory allocation in bytes
        environment_vars: New environment variables (replaces existing)
        readiness_probe_path: New readiness probe path
        liveness_probe_path: New liveness probe path
        entrypoint: New container entrypoint as array
        gpu: New GPU count
        gpu_type: New GPU type
    """
    if port is not None and port < 1024:
        return f"Error: Port must be >= 1024 (got {port}). Non-privileged ports only."

    # Parse list parameters that may have been stringified by MCP client
    environment_vars = parse_json_param(environment_vars, "environment_vars")
    entrypoint = parse_json_param(entrypoint, "entrypoint")

    client = await get_client()

    payload: dict = {}

    if name is not None:
        payload["name"] = name
    if description is not None:
        payload["description"] = description

    # Build container updates if any container fields provided
    container_fields = {
        "image_uri": image_uri, "port": port, "cpu": cpu, "memory_bytes": memory_bytes,
        "environment_vars": environment_vars, "readiness_probe_path": readiness_probe_path,
        "liveness_probe_path": liveness_probe_path, "entrypoint": entrypoint,
        "gpu": gpu, "gpu_type": gpu_type
    }

    if any(v is not None for v in container_fields.values()):
        # Need to fetch current spec and update it
        current = await client.get_artifact(artifact_id)
        current_spec = current.get("spec", {})
        container_groups = current_spec.get("containerGroups", [{}])
        containers = container_groups[0].get("containers", [{}]) if container_groups else [{}]
        container = containers[0] if containers else {}

        # Update container fields
        if image_uri is not None:
            container["imageUri"] = image_uri
        if port is not None:
            container["port"] = port
        if entrypoint is not None:
            container["entrypoint"] = entrypoint
        if environment_vars is not None:
            container["environmentVars"] = environment_vars

        # Update resource request
        resource_request = container.get("resourceRequest", {})
        if cpu is not None:
            resource_request["cpu"] = cpu
        if memory_bytes is not None:
            resource_request["memory"] = memory_bytes
        if gpu is not None:
            resource_request["gpu"] = gpu
        if gpu_type is not None:
            resource_request["gpuType"] = gpu_type
        container["resourceRequest"] = resource_request

        # Update probes
        if readiness_probe_path is not None:
            container["readinessProbe"] = {
                "path": readiness_probe_path,
                "port": container.get("port", 8000),
                "initialDelaySeconds": 10,
            }
        if liveness_probe_path is not None:
            container["livenessProbe"] = {
                "path": liveness_probe_path,
                "port": container.get("port", 8000),
                "initialDelaySeconds": 30,
            }

        # Rebuild spec
        payload["spec"] = {
            "type": current_spec.get("type", "service"),
            "containerGroups": [{
                "containers": [container]
            }]
        }

    if not payload:
        return "Error: No fields provided to update."

    artifact = await client.patch_artifact(artifact_id, payload)

    return f"""Updated artifact {artifact_id}:
Status: {artifact.get("status", "unknown")}

Changes applied. If workloads use this artifact, restart them to pick up changes:
  1. workload_stop(workload_ids=[...])
  2. workload_start(workload_id=..., wait_for_running=True)

Full response:
{json.dumps(artifact, indent=2)}"""


@mcp.tool()
@traced_tool
async def artifact_clone(artifact_id: str, new_name: str) -> str:
    """Clone an existing artifact.

    Creates a new artifact with the same configuration as the original.
    The cloned artifact starts in 'draft' status, allowing modifications.

    Args:
        artifact_id: The artifact ID to clone
        new_name: Name for the cloned artifact
    """
    client = await get_client()
    artifact = await client.clone_artifact(artifact_id, new_name)

    return f"""Cloned artifact successfully!

Original: {artifact_id}
New Artifact ID: {artifact.get("id", "")}
Name: {artifact.get("name", "")}
Status: {artifact.get("status", "draft")}
Type: {artifact.get("type", "")}

Full response:
{json.dumps(artifact, indent=2)}"""


@mcp.tool()
@traced_tool
async def artifact_build_list(artifact_id: str, limit: int = 10, offset: int = 0) -> str:
    """List image builds for an artifact.

    Shows build history for artifacts that use server-side image building
    (imageBuildConfig with codeRef to Files API).

    Args:
        artifact_id: The artifact ID
        limit: Maximum number of builds to return (default: 10)
        offset: Number to skip for pagination (default: 0)
    """
    client = await get_client()
    result = await client.list_artifact_builds(artifact_id, limit=limit, offset=offset)
    data = result.get("data", [])

    if not data:
        return f"No builds found for artifact {artifact_id}."

    rows = []
    for b in data:
        bid = b.get("id", "")
        status = b.get("status", "")
        created = format_created_at(b.get("createdAt", ""))
        rows.append(f"- {bid}: status={status} | created={created}")

    return f"Found {len(data)} builds for artifact {artifact_id}:\n" + "\n".join(rows)


@mcp.tool()
@traced_tool
async def artifact_build_trigger(artifact_id: str) -> str:
    """Trigger an image build for a draft artifact.

    Starts a server-side image build for artifacts with imageBuildConfig
    (codeRef pointing to Files API). Only works for draft artifacts.

    Args:
        artifact_id: The artifact ID to build
    """
    client = await get_client()
    result = await client.trigger_artifact_build(artifact_id)
    build_ids = result.get("buildIds", [])

    if not build_ids:
        return f"Build triggered for artifact {artifact_id} but no build IDs returned."

    return f"""Build triggered successfully for artifact {artifact_id}!

Build IDs: {", ".join(build_ids)}

Use artifact_build_get(artifact_id, build_id) to check build status.
Use artifact_build_logs(artifact_id, build_id) to view build logs."""


@mcp.tool()
@traced_tool
async def artifact_build_get(artifact_id: str, build_id: str) -> str:
    """Get details of a specific image build.

    Args:
        artifact_id: The artifact ID
        build_id: The build ID to retrieve
    """
    client = await get_client()
    build = await client.get_artifact_build(artifact_id, build_id)

    status = build.get("status", "")
    created = format_created_at(build.get("createdAt", ""))
    updated = format_created_at(build.get("updatedAt", ""))

    result = f"""Build {build_id}:
Artifact: {artifact_id}
Status: {status}
Created: {created}
Updated: {updated}
"""

    if status == "FAILED":
        result += "\nBuild FAILED. Use artifact_build_logs() to see error details."
    elif status == "COMPLETED" or status == "BUILT":
        result += "\nBuild completed successfully!"
    elif status in ("PENDING", "IN_PROGRESS"):
        result += "\nBuild in progress. Check again later."

    return result


@mcp.tool()
@traced_tool
async def artifact_build_logs(artifact_id: str, build_id: str) -> str:
    """Get logs for an image build.

    Use this to diagnose build failures or monitor build progress.

    Args:
        artifact_id: The artifact ID
        build_id: The build ID to get logs for
    """
    client = await get_client()
    logs = await client.get_artifact_build_logs(artifact_id, build_id)

    if not logs:
        return f"No logs available for build {build_id}."

    # Truncate if very long
    if len(logs) > 10000:
        return f"=== BUILD LOGS (truncated) ===\n...\n{logs[-10000:]}"

    return f"=== BUILD LOGS ===\n{logs}"


@mcp.tool()
@traced_tool
async def artifact_lock(artifact_id: str, repository_id: Optional[str] = None) -> str:
    """Lock an artifact (make it immutable).

    Once locked, an artifact cannot be modified. This is required for
    production workloads to ensure consistency.

    Args:
        artifact_id: The artifact ID to lock
        repository_id: Optional artifact repository ID for versioning
    """
    client = await get_client()
    payload: dict = {"status": "locked"}
    if repository_id:
        payload["artifactRepositoryId"] = repository_id

    artifact = await client.patch_artifact(artifact_id, payload)
    return f"Locked artifact {artifact_id}:\n{json.dumps(artifact, indent=2)}"


@mcp.tool()
@traced_tool
async def artifact_delete(artifact_ids: list[str]) -> str:
    """Delete one or more artifacts.

    Locked artifacts and artifacts with associated workloads cannot be deleted.

    Args:
        artifact_ids: List of artifact IDs to delete
    """
    # Parse list parameter that may have been stringified by MCP client
    artifact_ids = parse_json_param(artifact_ids, "artifact_ids")
    if not isinstance(artifact_ids, list):
        return f"Error: artifact_ids must be a list, got {type(artifact_ids).__name__}"

    client = await get_client()
    results = []

    for aid in artifact_ids:
        try:
            await client.delete_artifact(aid)
            results.append(f"Deleted {aid}")
        except Exception as e:
            results.append(f"Failed to delete {aid}: {e}")

    return "\n".join(results)


# ---------------------------------------------------------------------------
# Artifact Repository Tools
# ---------------------------------------------------------------------------

@mcp.tool()
@traced_tool
async def artifact_repo_list(limit: int = 100, offset: int = 0) -> str:
    """List artifact repositories.

    Artifact repositories are used for versioning artifacts.

    Args:
        limit: Maximum number to return (default: 100)
        offset: Number to skip for pagination (default: 0)
    """
    client = await get_client()
    result = await client.list_artifact_repositories(limit=limit, offset=offset)
    data = result.get("data", [])

    if not data:
        return "No artifact repositories found."

    rows = []
    for r in data:
        rid = r.get("id", "")
        name = r.get("name", "")
        num_artifacts = r.get("numArtifacts", 0)
        last_version = r.get("lastVersionNumber", 0)
        created = format_created_at(r.get("createdAt", ""))
        rows.append(f"- {rid}: {name} | artifacts={num_artifacts} | latest_v={last_version} | created={created}")

    return f"Found {len(data)} artifact repositories:\n" + "\n".join(rows)


@mcp.tool()
@traced_tool
async def artifact_repo_get(repo_id: str) -> str:
    """Get details of an artifact repository.

    Args:
        repo_id: The artifact repository ID
    """
    client = await get_client()
    repo = await client.get_artifact_repository(repo_id)
    return f"Artifact repository {repo_id}:\n{json.dumps(repo, indent=2)}"


@mcp.tool()
@traced_tool
async def artifact_repo_delete(repo_id: str) -> str:
    """Delete an artifact repository.

    Artifacts within the repository are cascade-deleted unless they are
    locked or still in use by workloads.

    Args:
        repo_id: The artifact repository ID to delete
    """
    client = await get_client()
    await client.delete_artifact_repository(repo_id)
    return f"Deleted artifact repository {repo_id}"


# ---------------------------------------------------------------------------
# Bundle Tools
# ---------------------------------------------------------------------------

@mcp.tool()
@traced_tool
async def bundle_list() -> str:
    """List available compute bundles - CALL THIS BEFORE creating workloads!

    Returns available CPU and GPU configurations. Use the bundle ID with
    workload_create(resource_bundle_id="...") or note the gpu_type for
    workload_create(gpu=1, gpu_type="...").

    Common bundles:
    - cpu.small, cpu.medium, cpu.large: CPU-only workloads
    - gpu.l4.small, gpu.a10g.medium: GPU workloads (check available types)
    """
    client = await get_client()
    result = await client.list_bundles()
    data = result.get("data", [])

    if not data:
        return "No compute bundles found."

    # Separate CPU and GPU bundles
    cpu_bundles = []
    gpu_bundles = []

    for b in data:
        bid = b.get("id", "")
        name = b.get("name", "")
        cpu_count = b.get("cpuCount", "")
        memory_bytes = b.get("memoryBytes", 0)
        memory_gb = f"{memory_bytes / (1024**3):.1f}GB" if memory_bytes else ""
        gpu_count = b.get("gpuCount", 0)
        gpu_type = b.get("gpuTypeLabel", "")

        if gpu_count and gpu_count > 0:
            gpu_info = f"{gpu_count}x {gpu_type}"
            gpu_bundles.append(f"  - {bid}: {name} | cpu={cpu_count} | mem={memory_gb} | gpu={gpu_info}")
        else:
            cpu_bundles.append(f"  - {bid}: {name} | cpu={cpu_count} | mem={memory_gb}")

    result_str = f"Found {len(data)} compute bundles:\n\n"

    if cpu_bundles:
        result_str += "CPU BUNDLES (for workload_create without gpu parameter):\n"
        result_str += "\n".join(cpu_bundles) + "\n\n"

    if gpu_bundles:
        result_str += "GPU BUNDLES (use resource_bundle_id or set gpu + gpu_type):\n"
        result_str += "\n".join(gpu_bundles) + "\n\n"

    result_str += """USAGE:
  Option 1 - Use bundle ID: workload_create(..., resource_bundle_id="cpu.small")
  Option 2 - Specify resources: workload_create(..., cpu=2, memory_bytes=4294967296)
  Option 3 - For GPU: workload_create(..., gpu=1, gpu_type="nvidia-l4")"""

    return result_str


# ---------------------------------------------------------------------------
# OTEL (OpenTelemetry) Tools
# ---------------------------------------------------------------------------

@mcp.tool()
@traced_tool
async def otel_logs(
    workload_id: str,
    limit: int = 50,
    level: str = "info",
    search: Optional[str] = None,
) -> str:
    """Get application logs for a workload (built-in OpenTelemetry).

    All workloads have OTEL logging enabled by default - no configuration needed.
    Logs are automatically collected from stdout/stderr of all containers.
    Logs are aggregated across all protons in the workload.

    IMPORTANT: Analyze the logs for errors, exceptions, and issues.

    Args:
        workload_id: The workload ID to get logs for
        limit: Maximum number of log entries (default: 50)
        level: Minimum log level: debug, info, warning, error, critical (default: info)
        search: Optional text to search for in log messages
    """
    client = await get_client()

    includes = [search] if search else None
    result = await client.get_otel_logs(
        workload_id,
        limit=limit,
        level=level,
        includes=includes,
    )

    logs = result.get("data", [])

    if not logs:
        return f"No logs found for workload {workload_id}.\nMake sure the workload is running. Logs appear shortly after startup."

    output = f"=== OTEL LOGS FOR WORKLOAD {workload_id} ===\n"
    output += f"Showing {len(logs)} log entries (level >= {level})\n\n"

    level_counts = {}
    error_logs = []

    for log in logs:
        log_level = log.get("level", "UNKNOWN").upper()
        level_counts[log_level] = level_counts.get(log_level, 0) + 1

        timestamp = log.get("timestamp", "")[:19]
        message = log.get("message", "")
        stacktrace = log.get("stacktrace", "")

        if log_level in ("ERROR", "CRITICAL"):
            error_logs.append({"timestamp": timestamp, "message": message, "stacktrace": stacktrace})

        output += f"[{timestamp}] {log_level}: {message}\n"
        if stacktrace:
            output += "  Stacktrace:\n"
            for line in stacktrace.split("\n")[:10]:
                output += f"    {line}\n"

    output += "\n=== SUMMARY ===\n"
    output += f"Log levels: {level_counts}\n"

    if error_logs:
        output += f"\nERRORS FOUND ({len(error_logs)}):\n"
        for err in error_logs[:5]:
            output += f"  - [{err['timestamp']}] {err['message'][:200]}\n"

    return output


@mcp.tool()
@traced_tool
async def otel_traces(workload_id: str) -> str:
    """List recent request traces for a workload.

    Traces show request flows and timing through the application.
    Requires the application to be instrumented with OpenTelemetry tracing.
    Traces are aggregated across all protons in the workload.

    Use otel_trace_get(workload_id, trace_id) to see detailed spans for a specific trace.

    Args:
        workload_id: The workload ID to get traces for
    """
    client = await get_client()
    result = await client.list_otel_traces(workload_id)

    traces = result.get("data", [])
    total = result.get("total", len(traces))

    if not traces:
        return f"No OTEL traces found for workload {workload_id}."

    output = f"=== OTEL TRACES FOR WORKLOAD {workload_id} ===\n"
    output += f"Total: {total} traces\n\n"

    for trace in traces[:20]:
        trace_id = trace.get("traceId", "")
        root_span = trace.get("rootSpanName", "")
        service = trace.get("rootServiceName", "")
        duration_ns = trace.get("duration", 0)
        duration_ms = duration_ns / 1_000_000 if duration_ns else 0
        span_count = trace.get("spansCount", 0)
        error_count = trace.get("errorSpansCount", 0)

        status = "X" if error_count > 0 else "ok"
        output += f"[{status}] {trace_id[:16]}... | {service}/{root_span} | {duration_ms:.1f}ms | {span_count} spans"
        if error_count > 0:
            output += f" | {error_count} errors"
        output += "\n"

    output += "\nUse otel_trace_get(workload_id, trace_id) to see full trace details."
    return output


@mcp.tool()
@traced_tool
async def otel_trace_get(workload_id: str, trace_id: str) -> str:
    """Get detailed spans for a specific OpenTelemetry trace.

    Shows the full request flow with timing and attributes.

    Args:
        workload_id: The workload ID
        trace_id: The 32-character trace ID
    """
    client = await get_client()
    result = await client.get_otel_trace(workload_id, trace_id)

    spans = result.get("spans", [])
    root_span = result.get("rootSpanName", "")
    root_service = result.get("rootServiceName", "")
    duration = result.get("duration", 0)
    duration_ms = duration / 1_000_000 if duration else 0

    output = f"=== TRACE {trace_id} ===\n"
    output += f"Root: {root_service}/{root_span}\n"
    output += f"Duration: {duration_ms:.1f}ms\n"
    output += f"Spans: {len(spans)}\n\n"

    sorted_spans = sorted(spans, key=lambda s: s.get("startTime", 0))

    output += "=== SPANS (chronological) ===\n"
    for span in sorted_spans:
        span_name = span.get("name", "")
        service = span.get("serviceName", "")
        span_duration = span.get("duration", 0) / 1_000_000
        status = span.get("statusCode", "")
        kind = span.get("kind", "")
        attributes = span.get("attributes", {})

        status_icon = "X" if status == "ERROR" else "ok"
        output += f"[{status_icon}] {service}/{span_name} ({kind}) - {span_duration:.1f}ms\n"

        important_attrs = ["http.method", "http.url", "http.status_code", "db.statement", "error.message"]
        for attr in important_attrs:
            if attr in attributes:
                output += f"    {attr}: {attributes[attr]}\n"

        if status == "ERROR":
            status_msg = span.get("statusMessage", "")
            if status_msg:
                output += f"    ERROR: {status_msg}\n"

    return output


@mcp.tool()
@traced_tool
async def otel_metrics(workload_id: str) -> str:
    """Get resource metrics for a workload.

    Shows CPU, memory, network, and other resource utilization metrics.
    Metrics are aggregated across all protons in the workload.
    Requires the application to export OpenTelemetry metrics.

    Args:
        workload_id: The workload ID to get metrics for
    """
    client = await get_client()
    result = await client.get_otel_metrics(workload_id)

    metrics = result.get("data", [])

    if not metrics:
        return f"No metrics found for workload {workload_id}.\nThe application must export OpenTelemetry metrics."

    output = f"=== OTEL METRICS FOR WORKLOAD {workload_id} ===\n\n"

    for metric in metrics:
        name = metric.get("otelName", "")
        display_name = metric.get("displayName", name)
        current = metric.get("currentValue")
        unit = metric.get("unit", "")
        level = metric.get("level", "")

        if unit == "bytes" and current:
            current_fmt = f"{current / (1024**2):.1f} MB"
        elif unit == "nanocores" and current:
            current_fmt = f"{current / 1_000_000:.2f} cores"
        elif unit == "percentage" and current:
            current_fmt = f"{current:.1f}%"
        elif current is not None:
            current_fmt = f"{current}"
        else:
            current_fmt = "N/A"

        output += f"- {display_name or name} [{level}]: {current_fmt}\n"

    return output


# ---------------------------------------------------------------------------
# OpenAPI Spec Tool
# ---------------------------------------------------------------------------

OPENAPI_SPEC_PATH = Path(os.environ.get(
    "OPENAPI_SPEC_PATH",
    "/app/openapi.yaml"
))

_openapi_cache: Optional[dict] = None


def _load_openapi_spec() -> dict:
    """Load and cache the OpenAPI spec."""
    global _openapi_cache

    if _openapi_cache is None:
        if not OPENAPI_SPEC_PATH.exists():
            raise FileNotFoundError(f"OpenAPI spec not found at {OPENAPI_SPEC_PATH}")
        with open(OPENAPI_SPEC_PATH, "r") as f:
            _openapi_cache = yaml.safe_load(f)
    return _openapi_cache


@mcp.tool()
@traced_tool
async def read_openapi_spec(
    section: Optional[str] = None,
    search: Optional[str] = None,
    schema_name: Optional[str] = None,
    path: Optional[str] = None,
) -> str:
    """Query the Workload API OpenAPI specification.

    Use this tool to understand the API schema, available endpoints, request/response
    formats, and valid field values before making API calls.

    USAGE EXAMPLES:
        # Get overview
        read_openapi_spec()

        # Get all schema definitions
        read_openapi_spec(section="schemas")

        # Get a specific schema by name
        read_openapi_spec(schema_name="CreateWorkloadRequest")

        # Get details for a specific API path
        read_openapi_spec(path="/workloads")

        # Search for keywords
        read_openapi_spec(search="replica")

    Args:
        section: Section to retrieve: "info", "paths", "schemas", or "all"
        search: Search for a keyword in schema/field names (case-insensitive)
        schema_name: Get a specific schema definition by exact name
        path: Get details for a specific API path (e.g., "/workloads")

    Returns formatted spec information.
    """
    try:
        spec = _load_openapi_spec()
    except FileNotFoundError as e:
        return f"Error: {e}"

    # Handle specific schema lookup
    if schema_name:
        schemas = spec.get("components", {}).get("schemas", {})
        if schema_name in schemas:
            return f"=== SCHEMA: {schema_name} ===\n\n{yaml.dump(schemas[schema_name], default_flow_style=False, sort_keys=False)}"
        for name, schema in schemas.items():
            if name.lower() == schema_name.lower():
                return f"=== SCHEMA: {name} ===\n\n{yaml.dump(schema, default_flow_style=False, sort_keys=False)}"
        similar = [n for n in schemas.keys() if schema_name.lower() in n.lower()]
        if similar:
            return f"Schema '{schema_name}' not found. Similar schemas:\n" + "\n".join(f"  - {n}" for n in similar[:10])
        return f"Schema '{schema_name}' not found. Use read_openapi_spec(section='schemas') to see all."

    # Handle specific path lookup
    if path:
        paths = spec.get("paths", {})
        if not path.startswith("/"):
            path = "/" + path
        if path in paths:
            return f"=== PATH: {path} ===\n\n{yaml.dump(paths[path], default_flow_style=False, sort_keys=False)}"
        matching = [p for p in paths.keys() if path in p]
        if matching:
            result = f"Paths matching '{path}':\n\n"
            for p in matching[:5]:
                result += f"=== {p} ===\n{yaml.dump(paths[p], default_flow_style=False, sort_keys=False)}\n\n"
            return result
        return f"Path '{path}' not found. Use read_openapi_spec(section='paths') to see all."

    # Handle search
    if search:
        search_lower = search.lower()
        results = {"schemas": [], "paths": [], "fields": []}

        schemas = spec.get("components", {}).get("schemas", {})
        for name, schema in schemas.items():
            if search_lower in name.lower():
                results["schemas"].append(name)
            props = schema.get("properties", {})
            for prop_name in props.keys():
                if search_lower in prop_name.lower():
                    results["fields"].append(f"{name}.{prop_name}")

        paths = spec.get("paths", {})
        for path_name, path_def in paths.items():
            if search_lower in path_name.lower():
                results["paths"].append(path_name)
            for method, op in path_def.items():
                if isinstance(op, dict):
                    op_id = op.get("operationId", "")
                    summary = op.get("summary", "")
                    if search_lower in op_id.lower() or search_lower in summary.lower():
                        results["paths"].append(f"{method.upper()} {path_name}: {summary}")

        output = f"=== SEARCH RESULTS FOR '{search}' ===\n\n"
        if results["schemas"]:
            output += f"Matching schemas ({len(results['schemas'])}):\n"
            for s in results["schemas"][:15]:
                output += f"  - {s}\n"
            output += "\n"
        if results["paths"]:
            output += f"Matching paths ({len(results['paths'])}):\n"
            for p in results["paths"][:15]:
                output += f"  - {p}\n"
            output += "\n"
        if results["fields"]:
            output += f"Matching fields ({len(results['fields'])}):\n"
            for f in results["fields"][:20]:
                output += f"  - {f}\n"

        if not any(results.values()):
            output += "No matches found."

        return output

    # Handle section retrieval
    if section == "all":
        return yaml.dump(spec, default_flow_style=False, sort_keys=False)

    if section == "info":
        info = spec.get("info", {})
        return f"=== API INFO ===\n\n{yaml.dump(info, default_flow_style=False, sort_keys=False)}"

    if section == "schemas":
        schemas = spec.get("components", {}).get("schemas", {})
        output = f"=== AVAILABLE SCHEMAS ({len(schemas)}) ===\n\n"
        grouped: dict[str, list[str]] = {}
        for name in sorted(schemas.keys()):
            prefix = name.split("-")[0].rstrip("0123456789")
            if prefix not in grouped:
                grouped[prefix] = []
            grouped[prefix].append(name)

        for prefix in sorted(grouped.keys()):
            output += f"{prefix}:\n"
            for name in grouped[prefix]:
                desc = schemas[name].get("description", "")[:60]
                output += f"  - {name}"
                if desc:
                    output += f": {desc}"
                output += "\n"
            output += "\n"
        output += "\nUse read_openapi_spec(schema_name='SchemaName') to get full details."
        return output

    if section == "paths":
        paths = spec.get("paths", {})
        output = f"=== AVAILABLE PATHS ({len(paths)}) ===\n\n"
        for path_name in sorted(paths.keys()):
            methods = [m.upper() for m in paths[path_name].keys() if m in ("get", "post", "put", "patch", "delete")]
            output += f"  {', '.join(methods):20} {path_name}\n"
        output += "\nUse read_openapi_spec(path='/path') to get full details."
        return output

    # Default: show overview
    info = spec.get("info", {})
    paths = spec.get("paths", {})
    schemas = spec.get("components", {}).get("schemas", {})

    output = f"""=== WORKLOAD API OPENAPI SPEC OVERVIEW ===

Title: {info.get('title', 'N/A')}
Version: {info.get('version', 'N/A')}

Available endpoints: {len(paths)}
Schema definitions: {len(schemas)}

COMMON QUERIES:
  read_openapi_spec(section="paths")     - List all API endpoints
  read_openapi_spec(section="schemas")   - List all schema definitions
  read_openapi_spec(schema_name="X")     - Get specific schema
  read_openapi_spec(path="/workloads")   - Get endpoint details
  read_openapi_spec(search="replica")    - Search for keyword

KEY PATHS:
"""
    for path_name in sorted(paths.keys())[:10]:
        methods = [m.upper() for m in paths[path_name].keys() if m in ("get", "post", "put", "patch", "delete")]
        output += f"  {', '.join(methods):20} {path_name}\n"

    if len(paths) > 10:
        output += f"  ... and {len(paths) - 10} more paths\n"

    return output


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
        app = mcp.http_app(path="/mcp")
        app = create_session_header_middleware(app)
        LOG.info("Session header translation enabled")
        uvicorn.run(app, host=args.host, port=args.port)
    else:
        LOG.info("Starting WAPI MCP server in stdio mode")
        mcp.run()


if __name__ == "__main__":
    main()
