"""Tests for the WAPI MCP server module."""



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
