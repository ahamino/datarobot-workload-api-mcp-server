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
    """Extract bundle / GPU info from runtime.resources."""
    if not runtime:
        return ""
    resources = runtime.get("resources") or []
    for r in resources:
        bundle_id = r.get("resourceBundleId")
        gpu_label = r.get("gpuTypeLabel")
        if bundle_id or gpu_label:
            if bundle_id and gpu_label:
                return f"{bundle_id} ({gpu_label})"
            return bundle_id or gpu_label
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

    result = {
        "replica_count": runtime.get("replicaCount", 1),
        "autoscaling_enabled": False,
    }

    autoscaling = runtime.get("autoscaling")
    if autoscaling:
        result["autoscaling_enabled"] = autoscaling.get("enabled", False)
        policies = autoscaling.get("policies", [])
        if policies:
            # Use the first policy (typically there's only one)
            policy = policies[0]
            result["min_replicas"] = policy.get("minCount")
            result["max_replicas"] = policy.get("maxCount")
            result["scaling_metric"] = policy.get("scalingMetric")
            result["target"] = policy.get("target")

    return result


def format_scaling_info(runtime: Optional[Dict[str, Any]]) -> str:
    """Format scaling settings as a human-readable string."""
    info = extract_scaling_info(runtime)

    if info.get("autoscaling_enabled"):
        metric = info.get("scaling_metric", "unknown")
        # Make metric more readable
        if metric == "cpuAverageUtilization":
            metric_display = "CPU utilization"
            target_display = f"{info.get('target', 0)}%"
        elif metric == "httpRequestsConcurrency":
            metric_display = "HTTP concurrency"
            target_display = str(info.get("target", 0))
        else:
            metric_display = metric
            target_display = str(info.get("target", 0))

        return (
            f"Autoscaling: enabled ({info.get('min_replicas', 0)}-{info.get('max_replicas', 0)} replicas, "
            f"target {metric_display}: {target_display})"
        )
    else:
        return f"Replicas: {info.get('replica_count', 1)} (fixed)"


def format_status_details(entity: Dict[str, Any]) -> str:
    """Format statusDetails for progress reporting."""
    status_details = entity.get("statusDetails", {})
    lines = []

    # Conditions (ContainersReady, Ready, etc.)
    conditions = status_details.get("conditions", [])
    if conditions:
        cond_strs = []
        for c in conditions:
            name = c.get("name") or c.get("type", "unknown")
            value = c.get("value", "unknown")
            cond_strs.append(f"{name}={value}")
        lines.append(f"Conditions: {', '.join(cond_strs)}")

    # Log tail (shows container startup errors)
    log_tail = status_details.get("logTail", [])
    if log_tail:
        lines.append("Recent logs:")
        for log_line in log_tail[-10:]:
            lines.append(f"  {log_line}")

    return "\n".join(lines) if lines else "No status details available"


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
    deadline = time.time() + timeout_seconds
    progress_lines = []
    last_status = None
    last_conditions = None

    while True:
        workload = await client.get_workload(workload_id)
        status = workload.get("status")
        status_details = workload.get("statusDetails", {})
        conditions = status_details.get("conditions", [])
        log_tail = status_details.get("logTail", [])

        # Build conditions string
        cond_str = ", ".join([
            f"{c.get('name', c.get('type', '?'))}={c.get('value', '?')}"
            for c in conditions
        ]) if conditions else "none"

        # Log progress if status or conditions changed
        if status != last_status or str(conditions) != str(last_conditions):
            elapsed = int(time.time() + timeout_seconds - deadline)
            progress_lines.append(f"[{elapsed}s] Status: {status} | {cond_str}")
            last_status = status
            last_conditions = conditions

        # Success
        if status == "running":
            progress_lines.append("Workload is now running!")
            return workload, "\n".join(progress_lines)

        # Error - include log tail
        if status == "errored":
            progress_lines.append("ERROR: Workload entered 'errored' state")
            if log_tail:
                progress_lines.append("Container logs:")
                for line in log_tail[-15:]:
                    progress_lines.append(f"  {line}")
            raise RuntimeError("\n".join(progress_lines))

        # Timeout
        if time.time() >= deadline:
            progress_lines.append(f"TIMEOUT after {timeout_seconds}s. Last status: {status}")
            if log_tail:
                progress_lines.append("Container logs:")
                for line in log_tail[-15:]:
                    progress_lines.append(f"  {line}")
            raise TimeoutError("\n".join(progress_lines))

        await asyncio.sleep(poll_interval_seconds)
