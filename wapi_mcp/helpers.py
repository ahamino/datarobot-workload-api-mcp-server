"""
Helper and utility functions for the WAPI MCP Server.
"""

import asyncio
import time
from datetime import datetime
from typing import Any, Dict, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .client import WapiClient


def format_created_at(ts: str) -> str:
    """Format createdAt timestamp into 'YYYY-MM-DD HH:MM:SS'."""
    if not ts:
        return ""
    try:
        s = ts.strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        if " " in s and "+" in s and "T" not in s:
            s = s.replace(" ", "T", 1)
        dt = datetime.fromisoformat(s)
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        s = ts.rstrip("Z")
        if "." in s:
            s = s.split(".", 1)[0]
        s = s.replace("T", " ")
        return s


def extract_bundle(runtime: Optional[Dict[str, Any]]) -> str:
    """Extract resource-bundle / GPU info from a workload runtime.

    The runtime is `runtime.containerGroups[]`; each group carries the requested
    `resourceBundles` (ordered ids) and, once scheduled, a read-only
    `resolvedBundle` ({id, gpuTypeLabel, ...}). Prefer the resolved bundle.
    """
    if not runtime:
        return ""
    for group in runtime.get("containerGroups") or []:
        resolved = group.get("resolvedBundle")
        if resolved:
            bundle_id = resolved.get("id", "")
            gpu_label = resolved.get("gpuTypeLabel")
            return f"{bundle_id} ({gpu_label})" if gpu_label else bundle_id
        requested = group.get("resourceBundles") or []
        if requested:
            # Not yet scheduled — show the requested candidate(s).
            return requested[0] if len(requested) == 1 else f"{requested[0]} (+{len(requested) - 1})"
    return ""


def extract_scaling_info(runtime: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Extract scaling settings from runtime.

    Returns a dict with:
    - replica_count: Current replica count
    - autoscaling_enabled: Whether autoscaling is enabled
    - min_replicas: Minimum replicas (if autoscaling)
    - max_replicas: Maximum replicas (if autoscaling)
    - scaling_metric: The metric used for scaling
    - target: Target value for the scaling metric
    """
    if not runtime:
        return {"replica_count": 1, "autoscaling_enabled": False}

    # replicaCount / autoscaling live on the container group, not the runtime root.
    groups = runtime.get("containerGroups") or []
    group = groups[0] if groups else {}

    result: Dict[str, Any] = {
        "replica_count": group.get("replicaCount", 1),
        "autoscaling_enabled": False,
    }

    autoscaling = group.get("autoscaling")
    if autoscaling and autoscaling.get("enabled"):
        result["autoscaling_enabled"] = True
        policies = autoscaling.get("policies", []) or []
        result["policies"] = policies
        if policies:
            policy = policies[0]
            result["min_replicas"] = policy.get("minCount")
            result["max_replicas"] = policy.get("maxCount")
            result["scaling_metric"] = policy.get("scalingMetric")
            result["target"] = policy.get("target")

    return result


def _format_metric_target(metric: str, target: Any) -> str:
    """Render a single 'metric: target' pair for display."""
    if metric == "cpuAverageUtilization":
        return f"CPU utilization: {target}%"
    if metric == "gpuCacheUtilization":
        return f"GPU cache: {target}%"
    if metric == "httpRequestsConcurrency":
        return f"HTTP concurrency: {target}"
    return f"{metric}: {target}"


def format_scaling_info(runtime: Optional[Dict[str, Any]]) -> str:
    """Format scaling settings as a human-readable string."""
    info = extract_scaling_info(runtime)

    if not info.get("autoscaling_enabled"):
        return f"Replicas: {info.get('replica_count', 1)} (fixed)"

    policies = info.get("policies") or []
    if len(policies) > 1:
        # Stacked policies — the autoscaler scales on whichever wants more replicas.
        rng = f"{policies[0].get('minCount', 0)}-{policies[0].get('maxCount', 0)}"
        targets = "; ".join(
            _format_metric_target(p.get("scalingMetric", "?"), p.get("target", 0)) for p in policies
        )
        return f"Autoscaling: enabled ({rng} replicas, {len(policies)} policies — {targets})"

    target_display = _format_metric_target(info.get("scaling_metric", "unknown"), info.get("target", 0))
    return (
        f"Autoscaling: enabled ({info.get('min_replicas', 0)}-{info.get('max_replicas', 0)} replicas, "
        f"target {target_display})"
    )


async def _diagnose_workload(client: "WapiClient", workload_id: str) -> str:
    """Best-effort failure diagnostics for a workload.

    The public workload object no longer carries statusDetails — per-replica
    detail lives on the proton's /statusDetails endpoint — so summarize each
    proton's status and point at the tools that show full logs/conditions.
    """
    lines = []
    try:
        protons = await client.list_workload_protons(workload_id, limit=10)
        for p in protons.get("data", []) or []:
            lines.append(
                f"  proton {p.get('id')}: role={p.get('role', '?')} status={p.get('status', '?')}"
            )
    except Exception:
        pass
    lines.append(
        f'Inspect: otel_logs("{workload_id}") for application logs; '
        f'proton_status_details("{workload_id}", <proton_id>) for per-replica conditions.'
    )
    return "\n".join(lines)


async def wait_for_status(
    client: "WapiClient",
    entity_type: str,
    entity_id: str,
    target_status: str,
    timeout_seconds: int,
    poll_interval_seconds: int = 1,
) -> Dict[str, Any]:
    """Poll until entity reaches target_status or fails."""
    if entity_type == "workload":
        getter = client.get_workload
    else:
        raise ValueError(f"Unknown entity_type: {entity_type}")

    deadline = time.time() + timeout_seconds
    entity: Optional[Dict[str, Any]] = None

    while True:
        entity = await getter(entity_id)
        last_status = entity.get("status")

        if last_status == target_status:
            return entity

        if last_status == "errored":
            raise RuntimeError(
                f"{entity_type.capitalize()} {entity_id} errored while waiting for '{target_status}'."
            )

        if time.time() >= deadline:
            raise TimeoutError(
                f"Timeout waiting for {entity_type} {entity_id} to reach "
                f"'{target_status}'. Last status: {last_status}"
            )

        await asyncio.sleep(poll_interval_seconds)


async def wait_for_workload_with_progress(
    client: "WapiClient",
    workload_id: str,
    timeout_seconds: int,
    poll_interval_seconds: int = 10,
) -> tuple[Dict[str, Any], str]:
    """
    Wait for workload to reach 'running' status with detailed progress.
    Returns (workload, progress_log).
    """
    start = time.time()
    deadline = start + timeout_seconds
    progress_lines = []
    last_status = None

    while True:
        workload = await client.get_workload(workload_id)
        status = workload.get("status")

        # Log progress on each status transition.
        if status != last_status:
            progress_lines.append(f"[{int(time.time() - start)}s] Status: {status}")
            last_status = status

        # Success
        if status == "running":
            progress_lines.append("Workload is now running!")
            return workload, "\n".join(progress_lines)

        # Error / timeout — attach best-effort per-proton diagnostics.
        if status == "errored":
            progress_lines.append("ERROR: Workload entered 'errored' state")
            progress_lines.append(await _diagnose_workload(client, workload_id))
            raise RuntimeError("\n".join(progress_lines))

        if time.time() >= deadline:
            progress_lines.append(f"TIMEOUT after {timeout_seconds}s. Last status: {status}")
            progress_lines.append(await _diagnose_workload(client, workload_id))
            raise TimeoutError("\n".join(progress_lines))

        await asyncio.sleep(poll_interval_seconds)
