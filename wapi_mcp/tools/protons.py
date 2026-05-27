"""Proton (runtime instance) inspection tools.

Tools call ``server.get_client()`` so test patches of
``wapi_mcp_server.get_client`` take effect.
"""

import json
import wapi_mcp_server as server
from wapi_mcp.helpers import format_created_at


from wapi_mcp_server import mcp, traced_tool  # noqa: E402


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
    client = await server.get_client()
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
    client = await server.get_client()
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
    client = await server.get_client()
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
                # Field names were renamed: met -> value, since -> lastTransitionTime.
                # Fall back to the old names for backward compatibility.
                met = cond.get("value", cond.get("met"))
                since = cond.get("lastTransitionTime", cond.get("since", ""))
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


__all__ = [
    "proton_list",
    "proton_get",
    "proton_status_details",
]
