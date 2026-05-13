"""
WAPI MCP Server Package

This package contains the core modules for the Workload API MCP Server.
"""

from .telemetry import LOG, init_telemetry, trace_span, record_tool_call
from .exceptions import WapiConfigError, WapiAPIError
from .client import WapiClient
from .helpers import (
    format_created_at,
    extract_bundle,
    extract_scaling_info,
    format_scaling_info,
    wait_for_status,
    wait_for_workload_with_progress,
)

__all__ = [
    # Telemetry
    "LOG",
    "init_telemetry",
    "trace_span",
    "record_tool_call",
    # Exceptions
    "WapiConfigError",
    "WapiAPIError",
    # Client
    "WapiClient",
    # Helpers
    "format_created_at",
    "extract_bundle",
    "extract_scaling_info",
    "format_scaling_info",
    "wait_for_status",
    "wait_for_workload_with_progress",
]
