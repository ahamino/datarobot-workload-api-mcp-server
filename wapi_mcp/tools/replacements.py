"""Artifact replacement (rolling rollout) tools.

Tools call ``server.get_client()`` so test patches of
``wapi_mcp_server.get_client`` take effect.
"""

from typing import Optional
import wapi_mcp_server as server

from wapi_mcp_server import parse_json_param, _format_replacement  # noqa: E402

from wapi_mcp_server import mcp, traced_tool  # noqa: E402


@mcp.tool()
@traced_tool
async def artifact_replacement_get(workload_id: str) -> str:
    """Get the active (or most recent) replacement for a workload.

    A replacement is a rolling swap of the workload to a different artifact:
    the candidate is deployed alongside the running version, traffic switches
    once it is ready, then the old version is decommissioned.

    Args:
        workload_id: The workload ID
    """
    client = await server.get_client()
    replacement = await client.get_artifact_replacement(workload_id)
    return _format_replacement(replacement)


@mcp.tool()
@traced_tool
async def artifact_replacement_create(
    workload_id: str,
    artifact_id: str,
    strategy: str = "rolling",
    warmup_duration_minutes: int = 0,
    keep_old_version_minutes: int = 0,
    runtime: Optional[dict] = None,
) -> str:
    """Start a replacement, swapping a workload to a different artifact.

    This performs a rolling replacement: the candidate artifact is deployed
    alongside the currently running version and traffic is switched to it once
    it is ready, after which the old version is decommissioned.

    The new artifact must match the current artifact's status — draft can only
    replace draft, locked only locked. For the draft->locked transition use
    workload_promote() instead. To change ONLY runtime settings (replicas,
    resources, autoscaling) of the same artifact, use workload_settings_update().

    Args:
        workload_id: The workload ID to replace the artifact for
        artifact_id: Existing artifact ID to deploy (must match current draft/locked status)
        strategy: Replacement strategy (only "rolling" is supported)
        warmup_duration_minutes: Minutes to warm up the candidate before switching
        keep_old_version_minutes: Minutes to keep the old version after switching
        runtime: Optional WorkloadRuntime to apply alongside the swap (replicas,
                 resources, autoscaling). If omitted, the current runtime is reused.
                 Shape: {"containerGroups": [{"name": "default", ...}]}
    """
    if strategy != "rolling":
        return f"Error: strategy must be 'rolling', got '{strategy}'"

    runtime = parse_json_param(runtime, "runtime")
    if runtime is not None and not isinstance(runtime, dict):
        return f"Error: runtime must be an object, got {type(runtime).__name__}"

    payload: dict = {
        "artifactId": artifact_id,
        "strategy": strategy,
        "config": {
            "warmupDurationMinutes": warmup_duration_minutes,
            "keepOldVersionMinutes": keep_old_version_minutes,
        },
    }
    if runtime is not None:
        payload["runtime"] = runtime

    client = await server.get_client()
    replacement = await client.create_artifact_replacement(workload_id, payload)
    return (
        f"Replacement started for workload {workload_id}.\n\n"
        + _format_replacement(replacement)
        + f"\n\nUse artifact_replacement_get({workload_id}) to monitor progress."
    )


@mcp.tool()
@traced_tool
async def artifact_replacement_delete(workload_id: str) -> str:
    """Cancel the in-progress replacement for a workload.

    Args:
        workload_id: The workload ID whose replacement should be cancelled
    """
    client = await server.get_client()
    await client.delete_artifact_replacement(workload_id)
    return f"Replacement for workload {workload_id} cancelled."


__all__ = [
    "artifact_replacement_get",
    "artifact_replacement_create",
    "artifact_replacement_delete",
]
