"""Workload tools: lifecycle, settings, stats, history, promote, related.

Tools call ``server.get_client()`` so test patches of
``wapi_mcp_server.get_client`` take effect.
"""

from typing import Optional
import json
import wapi_mcp_server as server
from wapi_mcp.helpers import format_created_at, extract_bundle, format_scaling_info, wait_for_status, wait_for_workload_with_progress

from wapi_mcp_server import parse_json_param, validate_autoscaling_policy  # noqa: E402

from wapi_mcp_server import mcp, traced_tool  # noqa: E402


@mcp.tool()
@traced_tool
async def workload_list(
    limit: int = 100,
    offset: int = 0,
    status: Optional[str] = None,
    importance: Optional[str] = None,
    artifact_status: Optional[str] = None,
    artifact_type: Optional[str] = None,
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
        status: Filter by workload status. Valid values:
                unknown, submitted, provisioning, launching, running,
                suspended, interrupted, stopping, stopped, errored, terminated
        importance: Filter by importance (critical, high, moderate, low)
        artifact_status: Filter by artifact status (draft, locked)
        artifact_type: Filter by artifact type (service, nim)
        artifact_id: Filter by specific artifact ID
        repository_id: Filter by artifact repository ID
        created_by: Filter by creator user ID
        tag_keys: Filter by tag keys (list)
        tag_values: Filter by tag values (list)
    """
    client = await server.get_client()

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
        artifact_type=artifact_type,
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
    client = await server.get_client()
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
    client = await server.get_client()
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

Logs (built-in): otel_logs("{workload_id}")
K8s diagnostics: proton_list("{workload_id}") then proton_status_details()"""

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
    client = await server.get_client()
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
    credential_env_vars: Optional[list[dict]] = None,
    readiness_probe_path: Optional[str] = None,
    liveness_probe_path: Optional[str] = None,
    entrypoint: Optional[list[str]] = None,
    gpu: Optional[int] = None,
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
    2. IF the user mentions GPU or asks for specific compute resources:
       a. Call bundle_list() to see available compute bundles (CPU/GPU configs)
       b. Use the appropriate bundle IDs in resource_bundle_ids parameter
       NOTE: GPU TYPE (e.g. L4, A10G, H100) and GPU VRAM are NOT set directly —
       they are determined entirely by which resource bundle you select. The
       resourceAllocation block has no gpuType or gpuMemory field. To run on a
       specific GPU model or VRAM size, pick the matching bundle from bundle_list().
    3. IF the user asks to inject credentials or mentions AWS/S3/database credentials:
       a. Call credential_list() to find available credentials and their IDs
       b. Call credential_keys() to see what field names are available for that credential type
       c. Use the credential_id and appropriate key names in credential_env_vars parameter
       d. NEVER hardcode credentials in environment_vars - always use credential_env_vars

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

    WITH GPU (call bundle_list first — the bundle sets the GPU type AND VRAM):
        workload_create(
            name="my-gpu-app",
            image_uri="docker.io/user/myapp:latest",
            resource_bundle_ids=["gpu.l4.small"]   # GPU model + VRAM come from this bundle
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

    WITH CREDENTIALS (IMPORTANT - follow this workflow):
        # Step 1: User says "I need AWS credentials injected"
        # Step 2: Call credential_list() to find S3 credentials
        # Step 3: Call credential_keys() to see available field names for "s3" type
        # Step 4: Create workload with credential_env_vars:
        workload_create(
            name="my-app",
            image_uri="docker.io/user/myapp:latest",
            credential_env_vars=[
                {"name": "AWS_ACCESS_KEY_ID", "credential_id": "abc123", "key": "awsAccessKeyId"},
                {"name": "AWS_SECRET_ACCESS_KEY", "credential_id": "abc123", "key": "awsSecretAccessKey"}
            ]
        )
        # NEVER put credentials in environment_vars - they won't be secure!

    Args:
        name: Workload name (required)
        artifact_id: Use existing artifact ID (don't set image_uri if using this)
        image_uri: Container image (e.g., "docker.io/user/image:tag")
        port: Port the container listens on. MUST be >= 1024!
        cpu: CPU cores (default: 1.0) - used only with inline artifact
        memory_bytes: Memory in bytes (default: 536870912 = 512MB) - used only with inline artifact
        replica_count: Number of replicas (default: 1, ignored if autoscaling enabled)
        environment_vars: MUST BE A LIST like [{"name": "VAR", "value": "val"}]
        credential_env_vars: Inject DataRobot credentials as env vars. MUST BE A LIST like:
            [{"name": "AWS_KEY", "credential_id": "<id>", "key": "awsAccessKeyId"}]
            WORKFLOW: First call credential_list() to get credential IDs, then call
            credential_keys() to see available field names for that credential type.
            NEVER hardcode secrets - always use this for sensitive values!
        readiness_probe_path: Health check path (e.g., "/health", "/readyz")
        liveness_probe_path: Liveness check path (e.g., "/health", "/healthz")
        entrypoint: MUST BE A LIST - NEVER guess, look up image docs first!
        gpu: Number of GPUs to request (count only). The GPU TYPE and GPU VRAM
             are NOT set here — they come from the resource bundle you select.
        resource_bundle_ids: Bundle ID from bundle_list() for scheduling, as a
                             single-element list, e.g. ["gpu.l4.small"]. Choose
                             EXACTLY ONE bundle — the field is a list for API
                             compatibility but only one bundle is allowed. The
                             selected bundle determines the GPU type (L4, A10G,
                             H100, ...) AND the GPU VRAM. resourceAllocation has no
                             gpuType/gpuMemory field, so a bundle is the ONLY way to
                             pick a specific GPU model or VRAM size.
        autoscaling_enabled: Enable autoscaling (default: False)
        autoscaling_min: Minimum replicas when autoscaling (default: 1)
        autoscaling_max: Maximum replicas when autoscaling (default: 5)
        autoscaling_metric: Scaling metric - one of the standard metrics
                           (cpuAverageUtilization, httpRequestsConcurrency,
                           gpuCacheUtilization, gpuRequestQueueDepth) or a custom
                           metric name for NIM artifacts, e.g. "vllm:kv_cache_usage_perc"
                           (default: cpuAverageUtilization)
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
    if resource_bundle_ids is not None and len(resource_bundle_ids) > 1:
        return (
            "Error: select exactly one resource bundle. resource_bundle_ids is a list "
            f"for API compatibility, but only a single bundle is allowed (got {len(resource_bundle_ids)})."
        )

    # Validate autoscaling metric and its target/scale-to-zero constraints.
    if autoscaling_enabled:
        err = validate_autoscaling_policy(autoscaling_metric, autoscaling_target, autoscaling_min)
        if err:
            return err

    client = await server.get_client()

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
        # Build resource allocation for runtime (NOT in artifact spec).
        # ResourceAllocation only accepts cpu/gpu/memory. To target a specific
        # GPU type, use resource_bundle_ids (the bundle catalog carries GPU type).
        resource_allocation: dict = {"cpu": cpu, "memory": memory_bytes}
        if gpu is not None and gpu > 0:
            resource_allocation["gpu"] = gpu

        container: dict = {
            "name": "main",
            "imageUri": image_uri,
            "port": port,
            "primary": True,
        }

        if entrypoint:
            container["entrypoint"] = entrypoint

        if environment_vars:
            container["environmentVars"] = environment_vars

        # Process credential environment variables
        credential_env_vars = parse_json_param(credential_env_vars, "credential_env_vars")
        if credential_env_vars is not None:
            if not isinstance(credential_env_vars, list):
                return f"Error: credential_env_vars must be a list, got {type(credential_env_vars).__name__}"

            # Transform to CredentialEnvironmentVariable schema
            cred_envs = []
            for cred_env in credential_env_vars:
                if not isinstance(cred_env, dict):
                    return "Error: Each credential_env_var must be a dict with 'name', 'credential_id', 'key'"

                env_name = cred_env.get("name")
                cred_id = cred_env.get("credential_id")
                key = cred_env.get("key")

                if not all([env_name, cred_id, key]):
                    return f"Error: credential_env_var missing required fields (name, credential_id, key): {cred_env}"

                cred_envs.append({
                    "source": "dr-credential",
                    "name": env_name,
                    "drCredentialId": cred_id,
                    "key": key
                })

            # Merge with existing environment vars
            if "environmentVars" not in container:
                container["environmentVars"] = []
            container["environmentVars"].extend(cred_envs)

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

        # Add resource allocation to runtime section
        if "containers" not in runtime["containerGroups"][0]:
            runtime["containerGroups"][0]["containers"] = []
        runtime["containerGroups"][0]["containers"].append({
            "name": "main",
            "resourceAllocation": resource_allocation
        })

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
    client = await server.get_client()
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

    client = await server.get_client()
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

    client = await server.get_client()
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
    """Update workload METADATA only (name, description, importance).

    This does NOT change what the workload runs or how it runs. For a generic
    "update the workload" request, pick the tool that matches the intent:
    - Deploy a DIFFERENT artifact (new image / version / build):
        -> artifact_replacement_create (rolling artifact swap)
    - Change runtime only (replicas, resources, autoscaling) on the SAME artifact:
        -> workload_settings_update
    - Change name / description / importance:
        -> this tool

    Args:
        workload_id: The workload ID to update
        name: New workload name
        description: New workload description
        importance: New importance level: "low", "moderate", "high", "critical"
    """
    client = await server.get_client()

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
    client = await server.get_client()
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

    Use this to change HOW the workload runs while keeping the SAME artifact. It
    triggers a rolling replacement - the workload is redeployed with new settings.
    To deploy a DIFFERENT artifact (new image/version), use
    artifact_replacement_create instead (it can also swap runtime in one call).

    Args:
        workload_id: The workload ID to update
        replica_count: New fixed replica count (ignored if autoscaling enabled)
        resource_bundle_ids: Single bundle ID for scheduling (from bundle_list),
                          as a one-element list. Only one bundle may be selected.
        autoscaling_enabled: Enable or disable autoscaling
        autoscaling_min: Minimum replicas when autoscaling
        autoscaling_max: Maximum replicas when autoscaling
        autoscaling_metric: Scaling metric - one of the standard metrics
                          (cpuAverageUtilization, httpRequestsConcurrency,
                          gpuCacheUtilization, gpuRequestQueueDepth) or a custom
                          metric name for NIM artifacts, e.g. "vllm:kv_cache_usage_perc"
        autoscaling_target: Target value for the scaling metric
    """
    # Parse list parameter that may have been stringified by MCP client
    resource_bundle_ids = parse_json_param(resource_bundle_ids, "resource_bundle_ids")
    if resource_bundle_ids is not None and not isinstance(resource_bundle_ids, list):
        return f"Error: resource_bundle_ids must be a list, got {type(resource_bundle_ids).__name__}"
    if resource_bundle_ids is not None and len(resource_bundle_ids) > 1:
        return (
            "Error: select exactly one resource bundle. resource_bundle_ids is a list "
            f"for API compatibility, but only a single bundle is allowed (got {len(resource_bundle_ids)})."
        )

    # Validate autoscaling metric/target/scale-to-zero if a metric is provided.
    # Custom metric names (e.g. "vllm:kv_cache_usage_perc") are allowed for NIM.
    if autoscaling_metric is not None:
        err = validate_autoscaling_policy(autoscaling_metric, autoscaling_target, autoscaling_min)
        if err:
            return err

    client = await server.get_client()

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
    client = await server.get_client()
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
    client = await server.get_client()

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
    client = await server.get_client()
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
    client = await server.get_client()
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
    client = await server.get_client()
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
async def workload_related(workload_id: str) -> str:
    """Get entities related to a workload (artifacts, etc.).

    Shows artifacts and other resources linked to this workload.

    Args:
        workload_id: The workload ID
    """
    client = await server.get_client()
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


__all__ = [
    "workload_list",
    "workload_search",
    "workload_get",
    "workload_status",
    "workload_create",
    "workload_start",
    "workload_stop",
    "workload_delete",
    "workload_update",
    "workload_settings_get",
    "workload_settings_update",
    "workload_stats",
    "workloads_stats_summary",
    "workload_history",
    "workload_events",
    "workload_promote",
    "workload_related",
]
