"""
OpenTelemetry setup and helpers for tracing and metrics.

This module handles observability concerns including:
- Distributed tracing with OTLP export
- Metrics collection (counters, histograms, gauges)
- Standard logging (no OTLP export)

Configuration is via environment variables:
- OTEL_EXPORTER_OTLP_ENDPOINT: OTLP collector endpoint (enables telemetry when set)
- OTEL_SERVICE_NAME: Service name (default: "wapi-mcp-server")
- LOG_LEVEL: Logging level (default: "INFO")
"""

import logging
import os
import re
from contextlib import asynccontextmanager, contextmanager
from typing import Any, Dict, Optional

# Single source for the reported service version (keep in sync with pyproject).
__version__ = "0.5.0"

# ---------------------------------------------------------------------------
# OpenTelemetry GenAI semantic conventions
# https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-spans/
# ---------------------------------------------------------------------------

# "Execute Tool" span attribute keys.
GEN_AI_OPERATION_NAME = "gen_ai.operation.name"
GEN_AI_TOOL_NAME = "gen_ai.tool.name"
GEN_AI_TOOL_TYPE = "gen_ai.tool.type"
GEN_AI_TOOL_DESCRIPTION = "gen_ai.tool.description"
GEN_AI_TOOL_CALL_ARGUMENTS = "gen_ai.tool.call.arguments"
GEN_AI_TOOL_CALL_RESULT = "gen_ai.tool.call.result"

# Value for gen_ai.operation.name when executing a tool.
GEN_AI_OPERATION_EXECUTE_TOOL = "execute_tool"
# Value for gen_ai.tool.type — MCP tools are function-style tools.
GEN_AI_TOOL_TYPE_FUNCTION = "function"

# Standard OTel error attribute (set on failed spans).
ERROR_TYPE = "error.type"


def genai_capture_content() -> bool:
    """Whether to record tool call arguments/results on spans.

    Follows the OTel GenAI opt-out env var. Tool arguments/results can contain
    user data, so deployments can disable capture by setting this to a falsy value.
    Defaults to enabled to preserve existing input/output capture behavior.
    """
    return os.environ.get(
        "OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT", "true"
    ).strip().lower() in ("1", "true", "yes")


# ---------------------------------------------------------------------------
# Global State
# ---------------------------------------------------------------------------

_tracer = None
_meter = None
_otel_initialized = False

# Metrics instruments
_tool_call_counter = None
_tool_call_duration = None
_api_request_counter = None
_api_request_duration = None
_active_sessions_gauge = None
_active_sessions_count = 0


# ---------------------------------------------------------------------------
# Setup Functions
# ---------------------------------------------------------------------------

def _get_otel_resource():
    """Create OpenTelemetry resource with service info."""
    try:
        from opentelemetry.sdk.resources import Resource, SERVICE_NAME, SERVICE_VERSION
        return Resource.create({
            SERVICE_NAME: os.environ.get("OTEL_SERVICE_NAME", "wapi-mcp-server"),
            SERVICE_VERSION: __version__,
        })
    except ImportError:
        return None


def setup_tracing():
    """Configure OpenTelemetry tracing with OTLP export."""
    global _tracer, _otel_initialized

    otel_endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    if not otel_endpoint:
        return None

    try:
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        resource = _get_otel_resource()

        tracer_provider = TracerProvider(resource=resource)
        trace.set_tracer_provider(tracer_provider)

        otlp_exporter = OTLPSpanExporter()
        tracer_provider.add_span_processor(BatchSpanProcessor(otlp_exporter))

        _tracer = trace.get_tracer("wapi-mcp-server", __version__)
        _otel_initialized = True
        return _tracer

    except ImportError as e:
        logging.getLogger("wapi-mcp").warning(f"OpenTelemetry tracing packages not available: {e}")
        return None
    except Exception as e:
        logging.getLogger("wapi-mcp").warning(f"Failed to configure OpenTelemetry tracing: {e}")
        return None


def setup_metrics():
    """Configure OpenTelemetry metrics with OTLP export."""
    global _meter, _tool_call_counter, _tool_call_duration
    global _api_request_counter, _api_request_duration, _active_sessions_gauge

    otel_endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    if not otel_endpoint:
        return None

    try:
        from opentelemetry import metrics
        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
        from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter

        resource = _get_otel_resource()

        otlp_exporter = OTLPMetricExporter()
        metric_reader = PeriodicExportingMetricReader(
            otlp_exporter,
            export_interval_millis=60000,
        )

        meter_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])
        metrics.set_meter_provider(meter_provider)

        _meter = metrics.get_meter("wapi-mcp-server", __version__)

        _tool_call_counter = _meter.create_counter(
            name="mcp.tool.calls",
            description="Number of MCP tool calls",
            unit="1",
        )

        _tool_call_duration = _meter.create_histogram(
            name="mcp.tool.duration",
            description="Duration of MCP tool calls in milliseconds",
            unit="ms",
        )

        _api_request_counter = _meter.create_counter(
            name="mcp.api.requests",
            description="Number of API requests made",
            unit="1",
        )

        _api_request_duration = _meter.create_histogram(
            name="mcp.api.duration",
            description="Duration of API requests in milliseconds",
            unit="ms",
        )

        _active_sessions_gauge = _meter.create_up_down_counter(
            name="mcp.sessions.active",
            description="Number of active MCP sessions",
            unit="1",
        )

        return _meter

    except ImportError as e:
        logging.getLogger("wapi-mcp").warning(f"OpenTelemetry metrics packages not available: {e}")
        return None
    except Exception as e:
        logging.getLogger("wapi-mcp").warning(f"Failed to configure OpenTelemetry metrics: {e}")
        return None


def setup_logging():
    """Configure standard logging."""
    log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, log_level, logging.INFO),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    return logging.getLogger("wapi-mcp")


def init_telemetry(logger=None):
    """Initialize all OpenTelemetry components."""
    setup_tracing()
    setup_metrics()
    if logger:
        logger.info(
            "OpenTelemetry telemetry initialized" if _otel_initialized
            else "OpenTelemetry not configured (set OTEL_EXPORTER_OTLP_ENDPOINT to enable)"
        )


# ---------------------------------------------------------------------------
# Telemetry Helpers
# ---------------------------------------------------------------------------

@contextmanager
def trace_span(name: str, attributes: Optional[Dict[str, Any]] = None):
    """Create a tracing span if OpenTelemetry is configured (sync version)."""
    if _tracer is None:
        yield None
        return

    # NOTE: do not wrap the `yield` in a try/except that yields again — a
    # contextmanager must yield exactly once, and a second yield while handling
    # a body exception raises "generator didn't stop after throw()". The import
    # is safe here because _tracer is only set once OpenTelemetry is configured.
    from opentelemetry.trace import Status, StatusCode

    with _tracer.start_as_current_span(name) as span:
        if attributes:
            for key, value in attributes.items():
                if value is not None:
                    span.set_attribute(
                        key,
                        str(value) if not isinstance(value, (str, int, float, bool)) else value
                    )
        try:
            yield span
        except Exception as e:
            span.set_status(Status(StatusCode.ERROR, str(e)))
            span.record_exception(e)
            raise


@asynccontextmanager
async def trace_span_async(name: str, attributes: Optional[Dict[str, Any]] = None):
    """Create a tracing span if OpenTelemetry is configured (async version).

    Use this in async functions to avoid generator issues with streaming responses.
    """
    if _tracer is None:
        yield None
        return

    # NOTE: do not wrap the `yield` in a try/except that yields again — a
    # contextmanager must yield exactly once, and a second yield while handling
    # a body exception raises "generator didn't stop after throw()". The import
    # is safe here because _tracer is only set once OpenTelemetry is configured.
    from opentelemetry.trace import Status, StatusCode

    with _tracer.start_as_current_span(name) as span:
        if attributes:
            for key, value in attributes.items():
                if value is not None:
                    span.set_attribute(
                        key,
                        str(value) if not isinstance(value, (str, int, float, bool)) else value
                    )
        try:
            yield span
        except Exception as e:
            span.set_status(Status(StatusCode.ERROR, str(e)))
            span.record_exception(e)
            raise


def normalize_path(path: str) -> str:
    """Normalize API path for metrics (replace IDs with placeholders)."""
    path = re.sub(r'/[a-f0-9]{24}(?=/|$)', '/{id}', path)
    path = re.sub(r'/[a-f0-9-]{36}(?=/|$)', '/{id}', path)
    return path


# OpenTelemetry HTTP client span attributes (semconv: http.*, url.*, server.*).
HTTP_REQUEST_METHOD = "http.request.method"
HTTP_RESPONSE_STATUS_CODE = "http.response.status_code"
HTTP_ROUTE = "http.route"
URL_FULL = "url.full"
SERVER_ADDRESS = "server.address"


@asynccontextmanager
async def trace_http_client_span(method: str, url: str, route: Optional[str] = None):
    """Span for an outbound HTTP call to an external service (OTel HTTP client semconv).

    Emitted as a CLIENT span and nested under whatever span is active (e.g. the
    tool's execute_tool span), so external calls show up in the trace tree. The
    caller should set http.response.status_code / error.type on the yielded span.
    No-op when tracing is not configured.
    """
    if _tracer is None:
        yield None
        return

    from urllib.parse import urlsplit
    from opentelemetry.trace import Status, StatusCode, SpanKind

    route = route or urlsplit(url).path
    with _tracer.start_as_current_span(
        f"{method.upper()} {route}", kind=SpanKind.CLIENT
    ) as span:
        span.set_attribute(HTTP_REQUEST_METHOD, method.upper())
        span.set_attribute(URL_FULL, url)
        span.set_attribute(HTTP_ROUTE, route)
        host = urlsplit(url).hostname
        if host:
            span.set_attribute(SERVER_ADDRESS, host)
        try:
            yield span
        except Exception as e:
            span.set_status(Status(StatusCode.ERROR, str(e)))
            span.record_exception(e)
            raise


def record_tool_call(tool_name: str, status: str, duration_ms: float, error: Optional[str] = None):
    """Record metrics for a tool call."""
    if _tool_call_counter is not None:
        attributes = {"tool.name": tool_name, "status": status}
        if error:
            attributes["error.type"] = error
        _tool_call_counter.add(1, attributes)

    if _tool_call_duration is not None:
        _tool_call_duration.record(duration_ms, {"tool.name": tool_name, "status": status})


def record_api_request(method: str, path: str, status_code: int, duration_ms: float):
    """Record metrics for an API request."""
    if _api_request_counter is not None:
        attributes = {
            "http.method": method,
            "http.route": normalize_path(path),
            "http.status_code": status_code,
        }
        _api_request_counter.add(1, attributes)

    if _api_request_duration is not None:
        _api_request_duration.record(duration_ms, {
            "http.method": method,
            "http.route": normalize_path(path),
        })


def increment_active_sessions():
    """Increment active sessions counter."""
    global _active_sessions_count
    _active_sessions_count += 1
    if _active_sessions_gauge is not None:
        _active_sessions_gauge.add(1)


def decrement_active_sessions():
    """Decrement active sessions counter."""
    global _active_sessions_count
    _active_sessions_count -= 1
    if _active_sessions_gauge is not None:
        _active_sessions_gauge.add(-1)


# Initialize logging on module import
LOG = setup_logging()
