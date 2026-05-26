"""Tests for the WAPI MCP server module."""

import pytest


class TestServerImport:
    """Tests for server module import."""

    def test_import_server_module(self):
        """Test that the server module can be imported."""
        import wapi_mcp_server
        assert wapi_mcp_server is not None

    def test_mcp_instance_exists(self):
        """Test that the MCP instance exists."""
        import wapi_mcp_server
        assert hasattr(wapi_mcp_server, 'mcp')


class TestToolRegistration:
    """Tests for tool registration."""

    def test_workload_tools_exist(self):
        """Test that workload tools are defined."""
        import wapi_mcp_server

        workload_tools = [
            'workload_list',
            'workload_get',
            'workload_create',
            'workload_start',
            'workload_stop',
            'workload_delete',
            'workload_update',
            'workload_status',
            'workload_search',
        ]

        for tool_name in workload_tools:
            assert hasattr(wapi_mcp_server, tool_name), f"Missing tool: {tool_name}"

    def test_artifact_tools_exist(self):
        """Test that artifact tools are defined."""
        import wapi_mcp_server

        artifact_tools = [
            'artifact_list',
            'artifact_get',
            'artifact_create',
            'artifact_update',
            'artifact_delete',
            'artifact_clone',
            'artifact_lock',
        ]

        for tool_name in artifact_tools:
            assert hasattr(wapi_mcp_server, tool_name), f"Missing tool: {tool_name}"

    def test_proton_tools_exist(self):
        """Test that proton tools are defined."""
        import wapi_mcp_server

        proton_tools = [
            'proton_list',
            'proton_get',
            'proton_status_details',
        ]

        for tool_name in proton_tools:
            assert hasattr(wapi_mcp_server, tool_name), f"Missing tool: {tool_name}"

    def test_otel_tools_exist(self):
        """Test that OTEL tools are defined."""
        import wapi_mcp_server

        otel_tools = [
            'otel_logs',
            'otel_traces',
            'otel_trace_get',
            'otel_metrics',
        ]

        for tool_name in otel_tools:
            assert hasattr(wapi_mcp_server, tool_name), f"Missing tool: {tool_name}"

    def test_bundle_tools_exist(self):
        """Test that bundle tools are defined."""
        import wapi_mcp_server
        assert hasattr(wapi_mcp_server, 'bundle_list')

    def test_openapi_tools_exist(self):
        """Test that OpenAPI tools are defined."""
        import wapi_mcp_server
        assert hasattr(wapi_mcp_server, 'read_openapi_spec')

    def test_credential_tools_exist(self):
        """Test that credential tools are defined."""
        import wapi_mcp_server

        credential_tools = [
            'credential_list',
            'credential_get',
            'credential_keys',
        ]

        for tool_name in credential_tools:
            assert hasattr(wapi_mcp_server, tool_name), f"Missing tool: {tool_name}"

    def test_workload_settings_tools_exist(self):
        """Test that workload settings tools are defined."""
        import wapi_mcp_server

        settings_tools = [
            'workload_settings_get',
            'workload_settings_update',
        ]

        for tool_name in settings_tools:
            assert hasattr(wapi_mcp_server, tool_name), f"Missing tool: {tool_name}"

    def test_workload_stats_tools_exist(self):
        """Test that workload stats tools are defined."""
        import wapi_mcp_server

        stats_tools = [
            'workload_stats',
            'workloads_stats_summary',
            'workload_history',
            'workload_events',
        ]

        for tool_name in stats_tools:
            assert hasattr(wapi_mcp_server, tool_name), f"Missing tool: {tool_name}"

    def test_artifact_build_tools_exist(self):
        """Test that artifact build tools are defined."""
        import wapi_mcp_server

        build_tools = [
            'artifact_build_list',
            'artifact_build_trigger',
            'artifact_build_get',
            'artifact_build_logs',
        ]

        for tool_name in build_tools:
            assert hasattr(wapi_mcp_server, tool_name), f"Missing tool: {tool_name}"

    def test_workload_management_tools_exist(self):
        """Test that workload management tools are defined."""
        import wapi_mcp_server

        management_tools = [
            'workload_promote',
            'workload_related',
        ]

        for tool_name in management_tools:
            assert hasattr(wapi_mcp_server, tool_name), f"Missing tool: {tool_name}"

    def test_artifact_repo_tools_exist(self):
        """Test that artifact repository tools are defined."""
        import wapi_mcp_server

        repo_tools = [
            'artifact_repo_list',
            'artifact_repo_get',
            'artifact_repo_delete',
        ]

        for tool_name in repo_tools:
            assert hasattr(wapi_mcp_server, tool_name), f"Missing tool: {tool_name}"


class TestToolsAreCallable:
    """Tests that tools are callable functions."""

    def test_workload_list_is_callable(self):
        """Test that workload_list is callable."""
        import wapi_mcp_server
        assert callable(wapi_mcp_server.workload_list)

    def test_artifact_list_is_callable(self):
        """Test that artifact_list is callable."""
        import wapi_mcp_server
        assert callable(wapi_mcp_server.artifact_list)

    def test_otel_logs_is_callable(self):
        """Test that otel_logs is callable."""
        import wapi_mcp_server
        assert callable(wapi_mcp_server.otel_logs)


class TestGenAITracing:
    """The traced_tool decorator emits OTel GenAI 'execute_tool' spans."""

    def _make_in_memory_tracer(self, monkeypatch):
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import SimpleSpanProcessor
        from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
            InMemorySpanExporter,
        )
        import wapi_mcp.telemetry as telemetry

        exporter = InMemorySpanExporter()
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(exporter))
        # trace_span() reads telemetry._tracer; point it at our in-memory tracer.
        monkeypatch.setattr(telemetry, "_tracer", provider.get_tracer("test"))
        return exporter

    @pytest.mark.asyncio
    async def test_success_span_has_gen_ai_attributes(self, monkeypatch):
        import wapi_mcp_server as mcp

        exporter = self._make_in_memory_tracer(monkeypatch)

        @mcp.traced_tool
        async def sample_tool(city: str = "NYC") -> str:
            """Look up the weather for a city."""
            return "sunny"

        result = await sample_tool(city="Paris")
        assert result == "sunny"

        spans = exporter.get_finished_spans()
        span = next(s for s in spans if s.name == "execute_tool sample_tool")
        attrs = dict(span.attributes)
        assert attrs["gen_ai.operation.name"] == "execute_tool"
        assert attrs["gen_ai.tool.name"] == "sample_tool"
        assert attrs["gen_ai.tool.type"] == "function"
        assert attrs["gen_ai.tool.description"] == "Look up the weather for a city."
        assert "Paris" in attrs["gen_ai.tool.call.arguments"]
        assert attrs["gen_ai.tool.call.result"] == "sunny"

    @pytest.mark.asyncio
    async def test_error_span_sets_error_type(self, monkeypatch):
        import wapi_mcp_server as mcp

        exporter = self._make_in_memory_tracer(monkeypatch)

        @mcp.traced_tool
        async def boom_tool() -> str:
            """A tool that fails."""
            raise ValueError("nope")

        # traced_tool swallows the exception and returns an error string.
        result = await boom_tool()
        assert "ERROR" in result

        span = next(s for s in exporter.get_finished_spans() if s.name == "execute_tool boom_tool")
        attrs = dict(span.attributes)
        assert attrs["gen_ai.operation.name"] == "execute_tool"
        assert attrs["gen_ai.tool.name"] == "boom_tool"
        assert attrs["error.type"] == "ValueError"

    @pytest.mark.asyncio
    async def test_content_capture_opt_out(self, monkeypatch):
        import wapi_mcp_server as mcp

        monkeypatch.setenv("OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT", "false")
        exporter = self._make_in_memory_tracer(monkeypatch)

        @mcp.traced_tool
        async def quiet_tool(secret: str = "x") -> str:
            """A tool whose args should not be captured."""
            return "done"

        await quiet_tool(secret="hunter2")

        span = next(s for s in exporter.get_finished_spans() if s.name == "execute_tool quiet_tool")
        attrs = dict(span.attributes)
        # Identity attributes still present; argument/result content omitted.
        assert attrs["gen_ai.tool.name"] == "quiet_tool"
        assert "gen_ai.tool.call.arguments" not in attrs
        assert "gen_ai.tool.call.result" not in attrs
