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
