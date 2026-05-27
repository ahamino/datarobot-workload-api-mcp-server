"""Integration tests for the WAPI MCP server.

These tests require valid DATAROBOT_API_ENDPOINT and DATAROBOT_API_TOKEN
environment variables to be set. They are skipped if credentials are not available.
"""

import os
import re
import time
import pytest

# Skip all tests in this module if credentials are not set
pytestmark = pytest.mark.skipif(
    not os.environ.get("DATAROBOT_API_ENDPOINT") or not os.environ.get("DATAROBOT_API_TOKEN"),
    reason="Integration tests require DATAROBOT_API_ENDPOINT and DATAROBOT_API_TOKEN"
)

# Mutating tests that create real resources (and, for workloads, real compute) are
# opt-in: they only run when WAPI_INTEGRATION_DESTRUCTIVE=1. They always clean up
# after themselves, but gating keeps the default suite read-only.
destructive = pytest.mark.skipif(
    os.environ.get("WAPI_INTEGRATION_DESTRUCTIVE") != "1",
    reason="Mutating integration tests require WAPI_INTEGRATION_DESTRUCTIVE=1",
)


async def _discover_id(api_endpoint, api_token, kind, status=None):
    """Return the id of the first available resource of `kind`, or None."""
    from wapi_mcp.client import WapiClient

    client = WapiClient(base_url=api_endpoint, token=api_token)
    try:
        if kind == "workload":
            result = await client.list_workloads(limit=1, status=status)
        elif kind == "artifact":
            result = await client.list_artifacts(limit=1, status=status)
        elif kind == "repo":
            result = await client.list_artifact_repositories(limit=1)
        else:
            return None
        data = result.get("data") or []
        return data[0]["id"] if data else None
    finally:
        await client.close()


@pytest.fixture(autouse=True)
async def reset_mcp_client():
    """Reset and properly close the global MCP client around each test.

    The client owns an aiohttp session; closing it on the test's own event loop
    (rather than dropping the reference) avoids the "Unclosed client session" /
    "Event loop is closed" teardown noise.
    """
    import wapi_mcp_server as mcp

    async def _close():
        if mcp._client is not None:
            try:
                await mcp._client.close()
            except Exception:
                pass
            mcp._client = None

    await _close()      # discard any client left over from a prior test
    yield
    await _close()      # close the client this test created


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


class TestOpenAPISpecIntegration:
    """Integration tests for the read_openapi_spec tool (read-only)."""

    @pytest.mark.asyncio
    async def test_read_openapi_spec_local(self):
        """The bundled spec loads and the overview reports the local source."""
        import wapi_mcp_server as mcp

        result = await mcp.read_openapi_spec()
        assert isinstance(result, str)
        assert "local" in result.lower()
        assert "OVERVIEW" in result
        # Bounded — never the full ~160KB spec.
        assert len(result) <= mcp.MAX_OPENAPI_RESPONSE_CHARS + 500

    @pytest.mark.asyncio
    async def test_read_openapi_spec_remote_master(self):
        """The remote source fetches the live spec from the configured endpoint."""
        import wapi_mcp_server as mcp

        result = await mcp.read_openapi_spec(source="remote")
        assert isinstance(result, str)
        # If the live endpoint serves the spec, we get the master overview; if it
        # doesn't expose /openapi.yaml, we get a clean error (not an exception).
        assert "MASTER" in result or "Error fetching master OpenAPI spec" in result
        assert len(result) <= mcp.MAX_OPENAPI_RESPONSE_CHARS + 500

    @pytest.mark.asyncio
    async def test_read_openapi_spec_remote_has_replacement_path(self):
        """The live spec should expose the replacement endpoint (v0.4)."""
        import wapi_mcp_server as mcp

        result = await mcp.read_openapi_spec(path="/workloads/{workload_id}/replacement", source="remote")
        assert isinstance(result, str)
        # Either the path is present on the live spec, or the endpoint didn't serve
        # a spec at all — both are acceptable outcomes for a remote integration check.
        assert (
            "replacement" in result.lower()
            or "not found" in result.lower()
            or "Error fetching master OpenAPI spec" in result
        )


class TestReadOnlyToolsIntegration:
    """Read-only coverage for tools that take a resource id (discover-or-skip)."""

    @pytest.fixture
    async def workload_id(self, api_endpoint, api_token):
        return await _discover_id(api_endpoint, api_token, "workload")

    @pytest.fixture
    async def running_workload_id(self, api_endpoint, api_token):
        return await _discover_id(api_endpoint, api_token, "workload", status="running")

    @pytest.fixture
    async def artifact_id(self, api_endpoint, api_token):
        return await _discover_id(api_endpoint, api_token, "artifact")

    @pytest.fixture
    async def repo_id(self, api_endpoint, api_token):
        return await _discover_id(api_endpoint, api_token, "repo")

    @pytest.mark.asyncio
    async def test_workload_get(self, workload_id):
        if not workload_id:
            pytest.skip("No workload available")
        import wapi_mcp_server as mcp
        result = await mcp.workload_get(workload_id)
        assert isinstance(result, str)
        assert workload_id in result

    @pytest.mark.asyncio
    async def test_workload_status(self, workload_id):
        if not workload_id:
            pytest.skip("No workload available")
        import wapi_mcp_server as mcp
        result = await mcp.workload_status(workload_id)
        assert isinstance(result, str)
        assert "status" in result.lower()

    @pytest.mark.asyncio
    async def test_workload_related(self, workload_id):
        if not workload_id:
            pytest.skip("No workload available")
        import wapi_mcp_server as mcp
        result = await mcp.workload_related(workload_id)
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_artifact_get(self, artifact_id):
        if not artifact_id:
            pytest.skip("No artifact available")
        import wapi_mcp_server as mcp
        result = await mcp.artifact_get(artifact_id)
        assert isinstance(result, str)
        assert artifact_id in result

    @pytest.mark.asyncio
    async def test_artifact_repo_get(self, repo_id):
        if not repo_id:
            pytest.skip("No artifact repository available")
        import wapi_mcp_server as mcp
        result = await mcp.artifact_repo_get(repo_id)
        assert isinstance(result, str)
        assert repo_id in result

    @pytest.mark.asyncio
    async def test_proton_get_and_status_details(self, api_endpoint, api_token, workload_id):
        if not workload_id:
            pytest.skip("No workload available")
        from wapi_mcp.client import WapiClient
        import wapi_mcp_server as mcp

        client = WapiClient(base_url=api_endpoint, token=api_token)
        try:
            protons = await client.list_workload_protons(workload_id, limit=1)
        finally:
            await client.close()
        data = protons.get("data") or []
        if not data:
            pytest.skip("Workload has no protons")
        proton_id = data[0]["id"]

        got = await mcp.proton_get(workload_id, proton_id)
        assert isinstance(got, str)
        assert proton_id in got

        details = await mcp.proton_status_details(workload_id, proton_id)
        assert isinstance(details, str)

    @pytest.mark.asyncio
    async def test_otel_traces(self, running_workload_id):
        if not running_workload_id:
            pytest.skip("No running workload available")
        import wapi_mcp_server as mcp
        result = await mcp.otel_traces(running_workload_id)
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_otel_trace_get(self, api_endpoint, api_token, running_workload_id):
        if not running_workload_id:
            pytest.skip("No running workload available")
        from wapi_mcp.client import WapiClient
        import wapi_mcp_server as mcp

        client = WapiClient(base_url=api_endpoint, token=api_token)
        try:
            traces = await client.list_otel_traces(running_workload_id)
        finally:
            await client.close()
        data = traces.get("data") or traces.get("traces") or []
        if not data:
            pytest.skip("No traces available")
        trace_id = data[0].get("traceId") or data[0].get("id")
        if not trace_id:
            pytest.skip("No trace id in trace data")

        result = await mcp.otel_trace_get(running_workload_id, trace_id)
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_artifact_build_get_and_logs(self, api_endpoint, api_token):
        """Find an artifact that has builds, then read build details + logs."""
        from wapi_mcp.client import WapiClient
        import wapi_mcp_server as mcp

        client = WapiClient(base_url=api_endpoint, token=api_token)
        try:
            artifacts = await client.list_artifacts(limit=10)
            build_artifact_id = None
            build_id = None
            for art in artifacts.get("data") or []:
                builds = await client.list_artifact_builds(art["id"], limit=1)
                bdata = builds.get("data") or []
                if bdata:
                    build_artifact_id = art["id"]
                    build_id = bdata[0]["id"]
                    break
        finally:
            await client.close()
        if not build_id:
            pytest.skip("No artifact with builds available")

        got = await mcp.artifact_build_get(build_artifact_id, build_id)
        assert isinstance(got, str)
        assert build_id in got

        logs = await mcp.artifact_build_logs(build_artifact_id, build_id)
        assert isinstance(logs, str)

    @pytest.mark.asyncio
    async def test_artifact_replacement_get(self, workload_id):
        """Reading a replacement returns its details, or a clean 'none active' message."""
        if not workload_id:
            pytest.skip("No workload available")
        import wapi_mcp_server as mcp

        # The tool returns a formatted string on success and a captured error string
        # (not an exception) when there's no active replacement (the common case).
        result = await mcp.artifact_replacement_get(workload_id)
        assert isinstance(result, str)
        assert (
            "Replacement" in result
            or "no active replacement" in result.lower()
            or "404" in result
        )


@destructive
class TestArtifactLifecycleIntegration:
    """Self-contained artifact CRUD (create/update/clone/delete). Draft artifacts
    are metadata (no compute) and the test cleans up after itself, but it still
    mutates the live environment — gate it behind WAPI_INTEGRATION_DESTRUCTIVE so
    CI/default runs stay read-only and don't create artifacts on every merge."""

    @pytest.mark.asyncio
    async def test_create_get_update_clone_delete(self, api_endpoint, api_token):
        from wapi_mcp.client import WapiClient
        import wapi_mcp_server as mcp

        suffix = int(time.time())
        created_ids: list[str] = []
        try:
            create_out = await mcp.artifact_create(
                name=f"itest-artifact-{suffix}",
                image_uri="nginx:latest",
                port=8080,
                description="integration test artifact",
            )
            m = re.search(r"Created artifact:\s*(\S+)", create_out)
            assert m, f"Could not parse artifact id from: {create_out[:200]}"
            art_id = m.group(1)
            created_ids.append(art_id)

            got = await mcp.artifact_get(art_id)
            assert art_id in got

            updated = await mcp.artifact_update(art_id, image_uri="nginx:alpine")
            assert art_id in updated or "Updated" in updated

            clone_out = await mcp.artifact_clone(art_id, f"itest-artifact-{suffix}-clone")
            cm = re.search(r"New Artifact ID:\s*(\S+)", clone_out)
            assert cm, f"Could not parse clone id from: {clone_out[:200]}"
            created_ids.append(cm.group(1))

            del_out = await mcp.artifact_delete(created_ids)
            assert isinstance(del_out, str)
            created_ids = []  # deleted through the tool
        finally:
            # Safety net: delete anything the tool path didn't.
            if created_ids:
                client = WapiClient(base_url=api_endpoint, token=api_token)
                try:
                    for aid in created_ids:
                        try:
                            await client.delete_artifact(aid)
                        except Exception:
                            pass
                finally:
                    await client.close()


@destructive
class TestDestructiveLifecycleIntegration:
    """Opt-in (WAPI_INTEGRATION_DESTRUCTIVE=1) coverage for mutating tools that
    create real workloads/builds/locks. Each test cleans up after itself."""

    @pytest.mark.asyncio
    async def test_workload_lifecycle(self, api_endpoint, api_token):
        from wapi_mcp.client import WapiClient
        import wapi_mcp_server as mcp

        suffix = int(time.time())
        workload_id = None
        try:
            out = await mcp.workload_create(
                name=f"itest-workload-{suffix}",
                image_uri="nginx:latest",
                port=8080,
                importance="low",
            )
            m = re.search(r"(?m)^ID:\s*(\S+)", out)
            assert m, f"Could not parse workload id from: {out[:300]}"
            workload_id = m.group(1)

            assert workload_id in await mcp.workload_get(workload_id)
            assert "status" in (await mcp.workload_status(workload_id)).lower()
            assert isinstance(await mcp.workload_update(workload_id, description="updated"), str)
            assert isinstance(await mcp.workload_settings_update(workload_id, replica_count=1), str)
            assert isinstance(await mcp.workload_stop([workload_id]), str)
        finally:
            if workload_id:
                client = WapiClient(base_url=api_endpoint, token=api_token)
                try:
                    try:
                        await client.delete_workload(workload_id)
                    except Exception:
                        pass
                finally:
                    await client.close()

    @pytest.mark.asyncio
    async def test_artifact_lock(self, api_endpoint, api_token):
        from wapi_mcp.client import WapiClient
        import wapi_mcp_server as mcp

        suffix = int(time.time())
        art_id = None
        try:
            create_out = await mcp.artifact_create(
                name=f"itest-lock-{suffix}", image_uri="nginx:latest", port=8080,
            )
            art_id = re.search(r"Created artifact:\s*(\S+)", create_out).group(1)
            locked = await mcp.artifact_lock(art_id)
            assert isinstance(locked, str)
            assert "lock" in locked.lower()
        finally:
            if art_id:
                client = WapiClient(base_url=api_endpoint, token=api_token)
                try:
                    try:
                        await client.delete_artifact(art_id)
                    except Exception:
                        pass
                finally:
                    await client.close()

    @pytest.mark.asyncio
    async def test_build_trigger_get_delete(self, api_endpoint, api_token):
        import wapi_mcp_server as mcp

        draft_id = await _discover_id(api_endpoint, api_token, "artifact", status="draft")
        if not draft_id:
            pytest.skip("No draft artifact available to build")

        trigger_out = await mcp.artifact_build_trigger(draft_id)
        assert isinstance(trigger_out, str)
        m = re.search(r"(?:Build|build)[^\n]*?([0-9a-fA-F]{8,})", trigger_out)
        if not m:
            pytest.skip(f"Could not parse build id from: {trigger_out[:200]}")
        build_id = m.group(1)

        assert isinstance(await mcp.artifact_build_get(draft_id, build_id), str)
        assert isinstance(await mcp.artifact_build_delete(draft_id, build_id), str)

    @pytest.mark.asyncio
    async def test_replacement_create_get_delete(self, api_endpoint, api_token):
        """Best-effort replacement smoke test on a SELF-CREATED workload.

        Never targets a discovered/shared workload — a rolling replacement would
        disrupt a live service. We create our own workload, attempt a same-artifact
        replacement, and tear everything down. If the workload isn't in a state that
        accepts a replacement, the tool's error string is an acceptable outcome.
        """
        from wapi_mcp.client import WapiClient
        import wapi_mcp_server as mcp

        suffix = int(time.time())
        workload_id = None
        artifact_id = None
        try:
            out = await mcp.workload_create(
                name=f"itest-repl-{suffix}", image_uri="nginx:latest",
                port=8080, importance="low", wait_for_running=True, timeout=120,
            )
            m = re.search(r"(?m)^ID:\s*(\S+)", out)
            if not m:
                pytest.skip(f"Could not create workload: {out[:200]}")
            workload_id = m.group(1)

            client = WapiClient(base_url=api_endpoint, token=api_token)
            try:
                wl = await client.get_workload(workload_id)
            finally:
                await client.close()
            artifact_id = wl.get("artifactId")
            if not artifact_id:
                pytest.skip("Created workload has no active artifact")

            # Success returns a Replacement string; if the workload has no active
            # proton yet, the tool returns a captured 4xx error string — both fine.
            created = await mcp.artifact_replacement_create(workload_id, artifact_id)
            assert isinstance(created, str)
            assert isinstance(await mcp.artifact_replacement_get(workload_id), str)
            assert isinstance(await mcp.artifact_replacement_delete(workload_id), str)
        finally:
            if workload_id:
                client = WapiClient(base_url=api_endpoint, token=api_token)
                try:
                    try:
                        await client.delete_workload(workload_id)
                    except Exception:
                        pass
                finally:
                    await client.close()
