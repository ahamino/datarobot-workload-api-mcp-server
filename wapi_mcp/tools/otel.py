"""OpenTelemetry observability tools: logs, traces, metrics.

Tools call ``server.get_client()`` (not a bound import) so that test patches of
``wapi_mcp_server.get_client`` take effect, and so the shared client/state lives
in one place. ``mcp``/``traced_tool`` are bound at import time (never patched).
"""

from typing import Optional

import wapi_mcp_server as server

mcp = server.mcp
traced_tool = server.traced_tool


@mcp.tool()
@traced_tool
async def otel_logs(
    workload_id: str,
    limit: int = 50,
    level: str = "info",
    search: Optional[str] = None,
    proton_id: Optional[str] = None,
) -> str:
    """Get application logs for a workload (built-in OpenTelemetry).

    All workloads have OTEL logging enabled by default - no configuration needed.
    Logs are automatically collected from stdout/stderr of all containers.

    Logs are bound to the WORKLOAD and aggregated across all of its protons. To
    narrow to a single proton/replica (e.g. when debugging one instance during a
    rollout), pass proton_id — it filters on the proton_id log attribute via
    searchKeys/searchValues. Use proton_list(workload_id) to find proton IDs.

    IMPORTANT: Analyze the logs for errors, exceptions, and issues.

    Args:
        workload_id: The workload ID to get logs for
        limit: Maximum number of log entries (default: 50)
        level: Minimum log level: debug, info, warning, error, critical (default: info)
        search: Optional text to search for in log messages
        proton_id: Optional proton ID to filter logs to a single proton/replica
    """
    client = await server.get_client()

    includes = [search] if search else None
    search_keys = ["proton_id"] if proton_id else None
    search_values = [proton_id] if proton_id else None
    result = await client.get_otel_logs(
        workload_id,
        limit=limit,
        level=level,
        includes=includes,
        search_keys=search_keys,
        search_values=search_values,
    )

    logs = result.get("data", [])

    scope = f"workload {workload_id}" + (f", proton {proton_id}" if proton_id else "")
    if not logs:
        return f"No logs found for {scope}.\nMake sure the workload is running. Logs appear shortly after startup."

    output = f"=== OTEL LOGS FOR {scope.upper()} ===\n"
    output += f"Showing {len(logs)} log entries (level >= {level})\n\n"

    level_counts: dict[str, int] = {}
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
    client = await server.get_client()
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
    client = await server.get_client()
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

        important_attrs = [
            "http.method", "http.url", "http.status_code",
            "db.statement", "error.message",
            "tool.name", "tool.input", "tool.output", "tool.status"
        ]
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
    client = await server.get_client()
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


__all__ = ["otel_logs", "otel_traces", "otel_trace_get", "otel_metrics"]
