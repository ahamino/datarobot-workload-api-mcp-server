"""Integration tests for the WAPI MCP server.

These tests require valid DATAROBOT_API_ENDPOINT and DATAROBOT_API_TOKEN
environment variables to be set. They are skipped if credentials are not available.
"""

import os
import pytest

# Skip all tests in this module if credentials are not set
pytestmark = pytest.mark.skipif(
    not os.environ.get("DATAROBOT_API_ENDPOINT") or not os.environ.get("DATAROBOT_API_TOKEN"),
    reason="Integration tests require DATAROBOT_API_ENDPOINT and DATAROBOT_API_TOKEN"
)


@pytest.fixture(autouse=True)
def reset_mcp_client():
    """Reset the global MCP client before each test to avoid event loop issues."""
    import wapi_mcp_server as mcp
    # Reset the global client to None so each test gets a fresh one
    mcp._client = None
    yield
    # Clean up after test
    mcp._client = None


@pytest.fixture
def api_endpoint():
    """Get the API endpoint from environment."""
    return os.environ.get("DATAROBOT_API_ENDPOINT")


@pytest.fixture
def api_token():
    """Get the API token from environment."""
    return os.environ.get("DATAROBOT_API_TOKEN")


class TestClientIntegration:
    """Integration tests for the WAPI client."""

    @pytest.mark.asyncio
    async def test_client_connection(self, api_endpoint, api_token):
        """Test that client can connect to the API."""
        from wapi_mcp.client import WapiClient

        client = WapiClient(base_url=api_endpoint, token=api_token)
        try:
            # List workloads with limit=1 to verify connection
            result = await client.list_workloads(limit=1)
            assert "data" in result
            assert isinstance(result["data"], list)
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_list_workloads(self, api_endpoint, api_token):
        """Test listing workloads."""
        from wapi_mcp.client import WapiClient

        client = WapiClient(base_url=api_endpoint, token=api_token)
        try:
            result = await client.list_workloads(limit=5)
            assert "data" in result
            # Verify structure of workload objects if any exist
            for workload in result["data"]:
                assert "id" in workload
                assert "name" in workload
                assert "status" in workload
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_list_artifacts(self, api_endpoint, api_token):
        """Test listing artifacts."""
        from wapi_mcp.client import WapiClient

        client = WapiClient(base_url=api_endpoint, token=api_token)
        try:
            result = await client.list_artifacts(limit=5)
            assert "data" in result
            # Verify structure of artifact objects if any exist
            for artifact in result["data"]:
                assert "id" in artifact
                assert "name" in artifact
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_list_bundles(self, api_endpoint, api_token):
        """Test listing compute bundles."""
        from wapi_mcp.client import WapiClient

        client = WapiClient(base_url=api_endpoint, token=api_token)
        try:
            result = await client.list_bundles()
            # Bundles endpoint returns a list directly or wrapped
            assert result is not None
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_list_artifact_repositories(self, api_endpoint, api_token):
        """Test listing artifact repositories."""
        from wapi_mcp.client import WapiClient

        client = WapiClient(base_url=api_endpoint, token=api_token)
        try:
            result = await client.list_artifact_repositories(limit=5)
            assert "data" in result
        finally:
            await client.close()


class TestMCPToolsIntegration:
    """Integration tests for MCP tools."""

    @pytest.mark.asyncio
    async def test_workload_list_tool(self):
        """Test workload_list MCP tool."""
        import wapi_mcp_server as mcp

        result = await mcp.workload_list(limit=3)
        assert isinstance(result, str)
        # Should return formatted output or "No workloads found"
        assert "workload" in result.lower() or "no workloads" in result.lower()

    @pytest.mark.asyncio
    async def test_artifact_list_tool(self):
        """Test artifact_list MCP tool."""
        import wapi_mcp_server as mcp

        result = await mcp.artifact_list(limit=3)
        assert isinstance(result, str)
        assert "artifact" in result.lower() or "no artifacts" in result.lower()

    @pytest.mark.asyncio
    async def test_bundle_list_tool(self):
        """Test bundle_list MCP tool."""
        import wapi_mcp_server as mcp

        result = await mcp.bundle_list()
        assert isinstance(result, str)
        # Should list compute bundles
        assert "bundle" in result.lower() or "cpu" in result.lower()

    @pytest.mark.asyncio
    async def test_workload_search_tool(self):
        """Test workload_search MCP tool."""
        import wapi_mcp_server as mcp

        result = await mcp.workload_search("test", limit=3)
        assert isinstance(result, str)
        # Should return results or "No workloads found"
        assert "workload" in result.lower() or "no workloads" in result.lower()

    @pytest.mark.asyncio
    async def test_artifact_repo_list_tool(self):
        """Test artifact_repo_list MCP tool."""
        import wapi_mcp_server as mcp

        result = await mcp.artifact_repo_list(limit=3)
        assert isinstance(result, str)
        # Check for valid output (repositories found, none found, or error message)
        result_lower = result.lower()
        assert any(term in result_lower for term in ["repositor", "artifact", "found", "error"])


class TestOTELIntegration:
    """Integration tests for OTEL tools (read-only)."""

    @pytest.fixture
    async def workload_id(self, api_endpoint, api_token):
        """Get a workload ID for OTEL tests."""
        from wapi_mcp.client import WapiClient

        client = WapiClient(base_url=api_endpoint, token=api_token)
        try:
            result = await client.list_workloads(limit=1, status="running")
            if result.get("data"):
                return result["data"][0]["id"]
            return None
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_otel_logs_tool(self, workload_id):
        """Test otel_logs MCP tool."""
        if not workload_id:
            pytest.skip("No running workload available for OTEL test")

        import wapi_mcp_server as mcp

        result = await mcp.otel_logs(workload_id, limit=5)
        assert isinstance(result, str)
        # Should return logs or "No logs found"
        assert "log" in result.lower() or "otel" in result.lower()

    @pytest.mark.asyncio
    async def test_otel_metrics_tool(self, workload_id):
        """Test otel_metrics MCP tool."""
        if not workload_id:
            pytest.skip("No running workload available for OTEL test")

        import wapi_mcp_server as mcp

        result = await mcp.otel_metrics(workload_id)
        assert isinstance(result, str)
        # Should return metrics or "No metrics found"
        assert "metric" in result.lower() or "otel" in result.lower()


class TestCredentialIntegration:
    """Integration tests for credential tools."""

    @pytest.mark.asyncio
    async def test_credential_list_tool(self):
        """Test credential_list MCP tool."""
        import wapi_mcp_server as mcp

        result = await mcp.credential_list(limit=5)
        assert isinstance(result, str)
        # Should list credentials or indicate none found
        assert "credential" in result.lower()

    @pytest.mark.asyncio
    async def test_credential_keys_tool(self):
        """Test credential_keys MCP tool."""
        import wapi_mcp_server as mcp

        result = await mcp.credential_keys()
        assert isinstance(result, str)
        # Should show credential types and their keys
        assert "credential" in result.lower()
        assert "type" in result.lower() or "key" in result.lower()

    @pytest.fixture
    async def credential_id(self, api_endpoint, api_token):
        """Get a credential ID for testing."""
        from wapi_mcp.client import WapiClient

        client = WapiClient(base_url=api_endpoint, token=api_token)
        try:
            result = await client.list_credentials(limit=1)
            if result.get("data"):
                return result["data"][0].get("credentialId")
            return None
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_credential_get_tool(self, credential_id):
        """Test credential_get MCP tool."""
        if not credential_id:
            pytest.skip("No credentials available for test")

        import wapi_mcp_server as mcp

        result = await mcp.credential_get(credential_id)
        assert isinstance(result, str)
        assert credential_id in result


class TestWorkloadStatsIntegration:
    """Integration tests for workload stats tools."""

    @pytest.fixture
    async def workload_id(self, api_endpoint, api_token):
        """Get a workload ID for stats tests."""
        from wapi_mcp.client import WapiClient

        client = WapiClient(base_url=api_endpoint, token=api_token)
        try:
            result = await client.list_workloads(limit=1)
            if result.get("data"):
                return result["data"][0]["id"]
            return None
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_workload_stats_tool(self, workload_id):
        """Test workload_stats MCP tool."""
        if not workload_id:
            pytest.skip("No workload available for stats test")

        import wapi_mcp_server as mcp

        result = await mcp.workload_stats(workload_id)
        assert isinstance(result, str)
        assert "stat" in result.lower() or "workload" in result.lower()

    @pytest.mark.asyncio
    async def test_workloads_stats_summary_tool(self):
        """Test workloads_stats_summary MCP tool."""
        import wapi_mcp_server as mcp

        result = await mcp.workloads_stats_summary()
        assert isinstance(result, str)
        assert "stat" in result.lower() or "workload" in result.lower()

    @pytest.mark.asyncio
    async def test_workload_history_tool(self, workload_id):
        """Test workload_history MCP tool."""
        if not workload_id:
            pytest.skip("No workload available for history test")

        import wapi_mcp_server as mcp

        result = await mcp.workload_history(workload_id, limit=5)
        assert isinstance(result, str)
        assert "history" in result.lower() or "artifact" in result.lower()

    @pytest.mark.asyncio
    async def test_workload_events_tool(self, workload_id):
        """Test workload_events MCP tool."""
        if not workload_id:
            pytest.skip("No workload available for events test")

        import wapi_mcp_server as mcp

        result = await mcp.workload_events(workload_id, limit=10)
        assert isinstance(result, str)
        assert "event" in result.lower() or "workload" in result.lower()


class TestArtifactBuildIntegration:
    """Integration tests for artifact build tools."""

    @pytest.fixture
    async def draft_artifact_id(self, api_endpoint, api_token):
        """Get a draft artifact ID for build tests."""
        from wapi_mcp.client import WapiClient

        client = WapiClient(base_url=api_endpoint, token=api_token)
        try:
            result = await client.list_artifacts(limit=10, status="draft")
            if result.get("data"):
                return result["data"][0]["id"]
            return None
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_artifact_build_list_tool(self, draft_artifact_id):
        """Test artifact_build_list MCP tool."""
        if not draft_artifact_id:
            pytest.skip("No draft artifact available for build test")

        import wapi_mcp_server as mcp

        result = await mcp.artifact_build_list(draft_artifact_id, limit=5)
        assert isinstance(result, str)
        assert "build" in result.lower()


class TestProtonIntegration:
    """Integration tests for proton tools."""

    @pytest.fixture
    async def workload_with_protons(self, api_endpoint, api_token):
        """Get a workload ID that has protons."""
        from wapi_mcp.client import WapiClient

        client = WapiClient(base_url=api_endpoint, token=api_token)
        try:
            result = await client.list_workloads(limit=10, status=["running", "stopped"])
            for workload in result.get("data", []):
                workload_id = workload["id"]
                protons = await client.list_workload_protons(workload_id, limit=1)
                if protons.get("data"):
                    return workload_id
            return None
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_proton_list_tool(self, workload_with_protons):
        """Test proton_list MCP tool."""
        if not workload_with_protons:
            pytest.skip("No workload with protons available")

        import wapi_mcp_server as mcp

        result = await mcp.proton_list(workload_with_protons, limit=5)
        assert isinstance(result, str)
        assert "proton" in result.lower()


class TestWorkloadSettingsIntegration:
    """Integration tests for workload settings tools."""

    @pytest.fixture
    async def workload_id(self, api_endpoint, api_token):
        """Get a workload ID for settings tests."""
        from wapi_mcp.client import WapiClient

        client = WapiClient(base_url=api_endpoint, token=api_token)
        try:
            result = await client.list_workloads(limit=1)
            if result.get("data"):
                return result["data"][0]["id"]
            return None
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_workload_settings_get_tool(self, workload_id):
        """Test workload_settings_get MCP tool."""
        if not workload_id:
            pytest.skip("No workload available for settings test")

        import wapi_mcp_server as mcp

        result = await mcp.workload_settings_get(workload_id)
        assert isinstance(result, str)
        assert "setting" in result.lower() or "autoscaling" in result.lower() or "resource" in result.lower()


class TestArtifactSearchIntegration:
    """Integration tests for artifact search."""

    @pytest.mark.asyncio
    async def test_artifact_search_tool(self):
        """Test artifact_search MCP tool."""
        import wapi_mcp_server as mcp

        result = await mcp.artifact_search("test", limit=5)
        assert isinstance(result, str)
        assert "artifact" in result.lower()
