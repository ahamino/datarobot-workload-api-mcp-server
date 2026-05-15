"""Unit tests for MCP tools."""

import pytest
from unittest.mock import AsyncMock, patch


class TestWorkloadSettingsTools:
    """Unit tests for workload settings tools."""

    @pytest.mark.asyncio
    async def test_workload_settings_get(self):
        """Test workload_settings_get tool."""
        import wapi_mcp_server as mcp

        mock_client = AsyncMock()
        mock_client.get_workload_settings = AsyncMock(return_value={
            "autoscaling": {"enabled": True, "minReplicas": 1, "maxReplicas": 5},
            "resourceAllocation": {"cpu": 1000, "memory": 1024}
        })

        with patch('wapi_mcp_server.get_client', return_value=mock_client):
            result = await mcp.workload_settings_get("wkld123")

        assert isinstance(result, str)
        assert "autoscaling" in result.lower()
        mock_client.get_workload_settings.assert_called_once_with("wkld123")

    @pytest.mark.asyncio
    async def test_workload_settings_update(self):
        """Test workload_settings_update tool."""
        import wapi_mcp_server as mcp

        mock_client = AsyncMock()
        mock_client.update_workload_settings = AsyncMock(return_value={
            "autoscaling": {"enabled": False}
        })

        with patch('wapi_mcp_server.get_client', return_value=mock_client):
            result = await mcp.workload_settings_update(
                "wkld123",
                autoscaling_enabled=False
            )

        assert isinstance(result, str)
        assert "updated" in result.lower() or "settings" in result.lower()
        mock_client.update_workload_settings.assert_called_once()


class TestWorkloadStatsTools:
    """Unit tests for workload stats tools."""

    @pytest.mark.asyncio
    async def test_workload_stats(self):
        """Test workload_stats tool."""
        import wapi_mcp_server as mcp

        mock_client = AsyncMock()
        mock_client.get_workload_stats = AsyncMock(return_value={
            "requestCount": 1000,
            "errorCount": 5,
            "averageLatency": 150
        })

        with patch('wapi_mcp_server.get_client', return_value=mock_client):
            result = await mcp.workload_stats("wkld123")

        assert isinstance(result, str)
        assert "stats" in result.lower() or "request" in result.lower()
        mock_client.get_workload_stats.assert_called_once()

    @pytest.mark.asyncio
    async def test_workloads_stats_summary(self):
        """Test workloads_stats_summary tool."""
        import wapi_mcp_server as mcp

        mock_client = AsyncMock()
        mock_client.get_all_workloads_stats = AsyncMock(return_value={
            "totalRequests": 5000,
            "totalErrors": 25
        })

        with patch('wapi_mcp_server.get_client', return_value=mock_client):
            result = await mcp.workloads_stats_summary()

        assert isinstance(result, str)
        mock_client.get_all_workloads_stats.assert_called_once()

    @pytest.mark.asyncio
    async def test_workload_history(self):
        """Test workload_history tool."""
        import wapi_mcp_server as mcp

        mock_client = AsyncMock()
        mock_client.get_workload_history = AsyncMock(return_value={
            "data": [
                {
                    "artifactId": "art123",
                    "deployedAt": "2024-01-15T10:00:00Z",
                    "status": "deployed"
                }
            ]
        })

        with patch('wapi_mcp_server.get_client', return_value=mock_client):
            result = await mcp.workload_history("wkld123", limit=10)

        assert isinstance(result, str)
        assert "history" in result.lower() or "artifact" in result.lower()
        mock_client.get_workload_history.assert_called_once()

    @pytest.mark.asyncio
    async def test_workload_events(self):
        """Test workload_events tool."""
        import wapi_mcp_server as mcp

        mock_client = AsyncMock()
        mock_client.get_workload_events = AsyncMock(return_value={
            "data": [
                {
                    "type": "workload.started",
                    "timestamp": "2024-01-15T10:00:00Z",
                    "message": "Workload started"
                }
            ]
        })

        with patch('wapi_mcp_server.get_client', return_value=mock_client):
            result = await mcp.workload_events("wkld123", limit=50)

        assert isinstance(result, str)
        assert "event" in result.lower() or "workload" in result.lower()
        mock_client.get_workload_events.assert_called_once()


class TestArtifactBuildTools:
    """Unit tests for artifact build tools."""

    @pytest.mark.asyncio
    async def test_artifact_build_list(self):
        """Test artifact_build_list tool."""
        import wapi_mcp_server as mcp

        mock_client = AsyncMock()
        mock_client.list_artifact_builds = AsyncMock(return_value={
            "data": [
                {
                    "id": "build123",
                    "status": "success",
                    "createdAt": "2024-01-15T10:00:00Z"
                }
            ]
        })

        with patch('wapi_mcp_server.get_client', return_value=mock_client):
            result = await mcp.artifact_build_list("art123", limit=10)

        assert isinstance(result, str)
        assert "build" in result.lower()
        mock_client.list_artifact_builds.assert_called_once()

    @pytest.mark.asyncio
    async def test_artifact_build_trigger(self):
        """Test artifact_build_trigger tool."""
        import wapi_mcp_server as mcp

        mock_client = AsyncMock()
        mock_client.trigger_artifact_build = AsyncMock(return_value={
            "id": "build456",
            "status": "pending"
        })

        with patch('wapi_mcp_server.get_client', return_value=mock_client):
            result = await mcp.artifact_build_trigger("art123")

        assert isinstance(result, str)
        assert "build456" in result or "triggered" in result.lower()
        mock_client.trigger_artifact_build.assert_called_once_with("art123")

    @pytest.mark.asyncio
    async def test_artifact_build_get(self):
        """Test artifact_build_get tool."""
        import wapi_mcp_server as mcp

        mock_client = AsyncMock()
        mock_client.get_artifact_build = AsyncMock(return_value={
            "id": "build123",
            "status": "success",
            "startedAt": "2024-01-15T10:00:00Z",
            "completedAt": "2024-01-15T10:05:00Z"
        })

        with patch('wapi_mcp_server.get_client', return_value=mock_client):
            result = await mcp.artifact_build_get("art123", "build123")

        assert isinstance(result, str)
        assert "build123" in result
        assert "success" in result.lower()
        mock_client.get_artifact_build.assert_called_once()

    @pytest.mark.asyncio
    async def test_artifact_build_logs(self):
        """Test artifact_build_logs tool."""
        import wapi_mcp_server as mcp

        mock_client = AsyncMock()
        mock_client.get_artifact_build_logs = AsyncMock(
            return_value="Step 1: Building image\nStep 2: Success"
        )

        with patch('wapi_mcp_server.get_client', return_value=mock_client):
            result = await mcp.artifact_build_logs("art123", "build123")

        assert isinstance(result, str)
        assert "Building image" in result
        mock_client.get_artifact_build_logs.assert_called_once()


class TestWorkloadManagementTools:
    """Unit tests for workload management tools."""

    @pytest.mark.asyncio
    async def test_workload_promote(self):
        """Test workload_promote tool."""
        import wapi_mcp_server as mcp

        mock_client = AsyncMock()
        mock_client.promote_workload = AsyncMock(return_value={
            "id": "wkld123",
            "status": "promoted"
        })

        with patch('wapi_mcp_server.get_client', return_value=mock_client):
            result = await mcp.workload_promote("wkld123")

        assert isinstance(result, str)
        assert "promoted" in result.lower() or "wkld123" in result
        mock_client.promote_workload.assert_called_once_with("wkld123")

    @pytest.mark.asyncio
    async def test_workload_related(self):
        """Test workload_related tool."""
        import wapi_mcp_server as mcp

        mock_client = AsyncMock()
        mock_client.get_workload_related = AsyncMock(return_value={
            "artifacts": ["art123", "art456"],
            "repositories": ["repo789"]
        })

        with patch('wapi_mcp_server.get_client', return_value=mock_client):
            result = await mcp.workload_related("wkld123")

        assert isinstance(result, str)
        assert "wkld123" in result or "related" in result.lower()
        mock_client.get_workload_related.assert_called_once_with("wkld123")


class TestArtifactRepoTools:
    """Unit tests for artifact repository tools."""

    @pytest.mark.asyncio
    async def test_artifact_repo_get(self):
        """Test artifact_repo_get tool."""
        import wapi_mcp_server as mcp

        mock_client = AsyncMock()
        mock_client.get_artifact_repository = AsyncMock(return_value={
            "id": "repo123",
            "name": "My Repository",
            "type": "docker"
        })

        with patch('wapi_mcp_server.get_client', return_value=mock_client):
            result = await mcp.artifact_repo_get("repo123")

        assert isinstance(result, str)
        assert "repo123" in result or "My Repository" in result
        mock_client.get_artifact_repository.assert_called_once_with("repo123")

    @pytest.mark.asyncio
    async def test_artifact_repo_delete(self):
        """Test artifact_repo_delete tool."""
        import wapi_mcp_server as mcp

        mock_client = AsyncMock()
        mock_client.delete_artifact_repository = AsyncMock(return_value=None)

        with patch('wapi_mcp_server.get_client', return_value=mock_client):
            result = await mcp.artifact_repo_delete("repo123")

        assert isinstance(result, str)
        assert "deleted" in result.lower() or "repo123" in result
        mock_client.delete_artifact_repository.assert_called_once_with("repo123")


class TestProtonTools:
    """Unit tests for proton tools."""

    @pytest.mark.asyncio
    async def test_proton_list(self):
        """Test proton_list tool."""
        import wapi_mcp_server as mcp

        mock_client = AsyncMock()
        mock_client.list_workload_protons = AsyncMock(return_value={
            "data": [
                {
                    "id": "proton123456",
                    "artifactId": "art123456789",
                    "status": "running",
                    "role": "primary",
                    "createdAt": "2024-01-15T10:00:00Z",
                },
                {
                    "id": "proton789012",
                    "artifactId": "art987654321",
                    "status": "stopped",
                    "role": "",
                    "createdAt": "2024-01-14T10:00:00Z",
                }
            ],
            "totalCount": 2
        })

        with patch('wapi_mcp_server.get_client', return_value=mock_client):
            result = await mcp.proton_list("wkld123")

        assert isinstance(result, str)
        assert "Found 2 protons" in result
        assert "proton123456" in result or "proton123456"[:12] in result
        assert "art123456789" in result or "art123456789"[:12] in result
        mock_client.list_workload_protons.assert_called_once()

    @pytest.mark.asyncio
    async def test_proton_list_empty(self):
        """Test proton_list with no protons."""
        import wapi_mcp_server as mcp

        mock_client = AsyncMock()
        mock_client.list_workload_protons = AsyncMock(return_value={
            "data": [],
            "totalCount": 0
        })

        with patch('wapi_mcp_server.get_client', return_value=mock_client):
            result = await mcp.proton_list("wkld123")

        assert isinstance(result, str)
        assert "No protons found" in result

    @pytest.mark.asyncio
    async def test_proton_get(self):
        """Test proton_get tool."""
        import wapi_mcp_server as mcp

        mock_client = AsyncMock()
        mock_client.get_workload_proton = AsyncMock(return_value={
            "id": "proton123",
            "name": "workload-abc-1",
            "status": "running",
            "replicas": 2
        })

        with patch('wapi_mcp_server.get_client', return_value=mock_client):
            result = await mcp.proton_get("wkld123", "proton123")

        assert isinstance(result, str)
        assert "proton123" in result
        mock_client.get_workload_proton.assert_called_once()

    @pytest.mark.asyncio
    async def test_proton_status_details(self):
        """Test proton_status_details tool."""
        import wapi_mcp_server as mcp

        mock_client = AsyncMock()
        mock_client.get_proton_status_details = AsyncMock(return_value={
            "overallStatus": {
                "state": "running",
                "summary": "All containers are running",
                "lastUpdated": "2024-01-15T10:00:00Z"
            },
            "replicas": [
                {
                    "name": "replica-1",
                    "status": "running",
                    "address": "10.0.0.1",
                    "nodeAddress": "node-1",
                    "startedAt": "2024-01-15T09:00:00Z",
                    "conditions": [
                        {"type": "Ready", "met": True, "since": "5m"},
                        {"type": "ContainersReady", "met": True, "since": "5m"},
                        {"type": "Initialized", "met": True, "since": "10m"},
                        {"type": "PodScheduled", "met": True, "since": "10m"}
                    ],
                    "containers": [
                        {
                            "name": "main",
                            "status": "running",
                            "ready": True,
                            "restartCount": 0,
                            "image": "ghcr.io/test/image:latest",
                            "startedAt": "2024-01-15T09:00:00Z"
                        }
                    ]
                }
            ]
        })

        with patch('wapi_mcp_server.get_client', return_value=mock_client):
            result = await mcp.proton_status_details("wkld123", "proton123")

        assert isinstance(result, str)
        assert "running" in result.lower()
        assert "Ready" in result
        assert "ContainersReady" in result
        assert "main" in result
        assert "[OK]" in result  # Check marks for met conditions
        mock_client.get_proton_status_details.assert_called_once_with("wkld123", "proton123")

    @pytest.mark.asyncio
    async def test_proton_status_details_with_issues(self):
        """Test proton_status_details with container issues."""
        import wapi_mcp_server as mcp

        mock_client = AsyncMock()
        mock_client.get_proton_status_details = AsyncMock(return_value={
            "overallStatus": {
                "state": "errored",
                "summary": "Container is failing",
                "lastUpdated": "2024-01-15T10:00:00Z"
            },
            "replicas": [
                {
                    "name": "replica-1",
                    "status": "failed",
                    "address": "",
                    "nodeAddress": "",
                    "startedAt": "",
                    "conditions": [
                        {"type": "Ready", "met": False, "since": ""},
                        {"type": "ContainersReady", "met": False, "since": ""}
                    ],
                    "containers": [
                        {
                            "name": "main",
                            "status": "waiting",
                            "ready": False,
                            "restartCount": 5,
                            "image": "ghcr.io/test/image:latest"
                        }
                    ]
                }
            ]
        })

        with patch('wapi_mcp_server.get_client', return_value=mock_client):
            result = await mcp.proton_status_details("wkld123", "proton123")

        assert isinstance(result, str)
        assert "errored" in result.lower() or "failed" in result.lower()
        assert "[--]" in result  # Dash marks for unmet conditions
        assert "restarts: 5" in result.lower()
        assert "waiting" in result.lower()

    @pytest.mark.asyncio
    async def test_proton_status_details_no_content(self):
        """Test proton_status_details with 204 No Content response."""
        import wapi_mcp_server as mcp

        mock_client = AsyncMock()
        mock_client.get_proton_status_details = AsyncMock(
            side_effect=Exception("204 No content")
        )

        with patch('wapi_mcp_server.get_client', return_value=mock_client):
            result = await mcp.proton_status_details("wkld123", "proton123")

        assert isinstance(result, str)
        assert "No status details available" in result
        assert "initializing" in result.lower()

    @pytest.mark.asyncio
    async def test_proton_status_details_empty_response(self):
        """Test proton_status_details with empty response."""
        import wapi_mcp_server as mcp

        mock_client = AsyncMock()
        mock_client.get_proton_status_details = AsyncMock(return_value={})

        with patch('wapi_mcp_server.get_client', return_value=mock_client):
            result = await mcp.proton_status_details("wkld123", "proton123")

        assert isinstance(result, str)
        assert "No status details available" in result


class TestOpenAPITool:
    """Unit tests for OpenAPI tool."""

    @pytest.mark.asyncio
    async def test_read_openapi_spec_local_file(self):
        """Test read_openapi_spec with local file."""
        import wapi_mcp_server as mcp

        result = await mcp.read_openapi_spec()

        assert isinstance(result, str)
        # Should contain OpenAPI spec content
        assert "openapi" in result.lower() or "components" in result.lower()

    @pytest.mark.asyncio
    async def test_read_openapi_spec_with_path(self):
        """Test read_openapi_spec with specific path."""
        import wapi_mcp_server as mcp

        result = await mcp.read_openapi_spec(path="/paths/~1api~1v2~1workloads~1/get")

        assert isinstance(result, str)
        # Should filter to specific path or indicate filtering


class TestArtifactSearchTool:
    """Unit tests for artifact search tool."""

    @pytest.mark.asyncio
    async def test_artifact_search(self):
        """Test artifact_search tool."""
        import wapi_mcp_server as mcp

        mock_client = AsyncMock()
        mock_client.list_artifacts = AsyncMock(return_value={
            "data": [
                {
                    "id": "art123",
                    "name": "test-artifact",
                    "status": "draft"
                }
            ]
        })

        with patch('wapi_mcp_server.get_client', return_value=mock_client):
            result = await mcp.artifact_search("test", limit=10)

        assert isinstance(result, str)
        assert "artifact" in result.lower()
        mock_client.list_artifacts.assert_called_once()


class TestWorkloadDeleteAndStopTools:
    """Unit tests for workload delete and stop tools."""

    @pytest.mark.asyncio
    async def test_workload_stop_single(self):
        """Test workload_stop with single workload."""
        import wapi_mcp_server as mcp

        mock_client = AsyncMock()
        mock_client.stop_workload = AsyncMock(return_value={"status": "stopping"})

        with patch('wapi_mcp_server.get_client', return_value=mock_client):
            result = await mcp.workload_stop(["wkld123"])

        assert isinstance(result, str)
        assert "stopped" in result.lower() or "stopping" in result.lower()
        mock_client.stop_workload.assert_called_once()

    @pytest.mark.asyncio
    async def test_workload_stop_multiple(self):
        """Test workload_stop with multiple workloads."""
        import wapi_mcp_server as mcp

        mock_client = AsyncMock()
        mock_client.stop_workload = AsyncMock(return_value={"status": "stopping"})

        with patch('wapi_mcp_server.get_client', return_value=mock_client):
            result = await mcp.workload_stop(["wkld123", "wkld456"])

        assert isinstance(result, str)
        # Should stop both
        assert mock_client.stop_workload.call_count == 2

    @pytest.mark.asyncio
    async def test_workload_delete_single(self):
        """Test workload_delete with single workload."""
        import wapi_mcp_server as mcp

        mock_client = AsyncMock()
        mock_client.delete_workload = AsyncMock(return_value=None)

        with patch('wapi_mcp_server.get_client', return_value=mock_client):
            result = await mcp.workload_delete(["wkld123"])

        assert isinstance(result, str)
        assert "deleted" in result.lower()
        mock_client.delete_workload.assert_called_once()

    @pytest.mark.asyncio
    async def test_workload_delete_multiple(self):
        """Test workload_delete with multiple workloads."""
        import wapi_mcp_server as mcp

        mock_client = AsyncMock()
        mock_client.delete_workload = AsyncMock(return_value=None)

        with patch('wapi_mcp_server.get_client', return_value=mock_client):
            result = await mcp.workload_delete(["wkld123", "wkld456"])

        assert isinstance(result, str)
        # Should delete both
        assert mock_client.delete_workload.call_count == 2


class TestArtifactDeleteAndCloneTools:
    """Unit tests for artifact delete and clone tools."""

    @pytest.mark.asyncio
    async def test_artifact_clone(self):
        """Test artifact_clone tool."""
        import wapi_mcp_server as mcp

        mock_client = AsyncMock()
        mock_client.clone_artifact = AsyncMock(return_value={
            "id": "art456",
            "name": "cloned-artifact"
        })

        with patch('wapi_mcp_server.get_client', return_value=mock_client):
            result = await mcp.artifact_clone("art123", "cloned-artifact")

        assert isinstance(result, str)
        assert "art456" in result or "cloned" in result.lower()
        mock_client.clone_artifact.assert_called_once()

    @pytest.mark.asyncio
    async def test_artifact_delete_single(self):
        """Test artifact_delete with single artifact."""
        import wapi_mcp_server as mcp

        mock_client = AsyncMock()
        mock_client.delete_artifact = AsyncMock(return_value=None)

        with patch('wapi_mcp_server.get_client', return_value=mock_client):
            result = await mcp.artifact_delete(["art123"])

        assert isinstance(result, str)
        assert "deleted" in result.lower()
        mock_client.delete_artifact.assert_called_once()

    @pytest.mark.asyncio
    async def test_artifact_lock(self):
        """Test artifact_lock tool."""
        import wapi_mcp_server as mcp

        mock_client = AsyncMock()
        mock_client.patch_artifact = AsyncMock(return_value={
            "id": "art123",
            "status": "locked"
        })

        with patch('wapi_mcp_server.get_client', return_value=mock_client):
            result = await mcp.artifact_lock("art123")

        assert isinstance(result, str)
        assert "locked" in result.lower() or "art123" in result
        mock_client.patch_artifact.assert_called_once()


class TestWorkloadCoreTools:
    """Unit tests for core workload tools."""

    @pytest.mark.asyncio
    async def test_workload_create(self):
        """Test workload_create tool."""
        import wapi_mcp_server as mcp

        mock_client = AsyncMock()
        mock_client.create_workload = AsyncMock(return_value={
            "id": "wkld123",
            "name": "test-workload",
            "status": "submitted",
            "artifactId": "art123",
            "endpoint": ""
        })
        mock_client._build_url = lambda path: f"https://example.com{path}"

        with patch('wapi_mcp_server.get_client', return_value=mock_client):
            result = await mcp.workload_create(
                name="test-workload",
                image_uri="nginx:latest",
                port=8080
            )

        assert isinstance(result, str)
        assert "wkld123" in result
        assert "submitted" in result
        mock_client.create_workload.assert_called_once()

    @pytest.mark.asyncio
    async def test_workload_get(self):
        """Test workload_get tool."""
        import wapi_mcp_server as mcp

        mock_client = AsyncMock()
        mock_client.get_workload = AsyncMock(return_value={
            "id": "wkld123",
            "name": "test-workload",
            "status": "running",
            "artifactId": "art123",
            "importance": "high",
            "description": "Test workload",
            "createdAt": "2024-01-15T10:00:00Z",
            "endpoint": "https://example.com/workloads/wkld123",
            "runtime": {
                "containerGroups": [{
                    "replicaCount": 2,
                    "resourceBundles": ["cpu.medium"]
                }]
            }
        })
        mock_client._build_url = lambda path: f"https://example.com{path}"

        with patch('wapi_mcp_server.get_client', return_value=mock_client):
            result = await mcp.workload_get("wkld123")

        assert isinstance(result, str)
        assert "test-workload" in result
        assert "running" in result
        assert "wkld123" in result
        mock_client.get_workload.assert_called_once_with("wkld123")

    @pytest.mark.asyncio
    async def test_workload_status(self):
        """Test workload_status tool."""
        import wapi_mcp_server as mcp

        mock_client = AsyncMock()
        mock_client.get_workload = AsyncMock(return_value={
            "id": "wkld123",
            "name": "test-workload",
            "status": "running",
            "statusDetails": {
                "logTail": [
                    "INFO: Application started",
                    "INFO: Listening on port 8000"
                ]
            }
        })

        with patch('wapi_mcp_server.get_client', return_value=mock_client):
            result = await mcp.workload_status("wkld123")

        assert isinstance(result, str)
        assert "test-workload" in result
        assert "running" in result.lower()
        mock_client.get_workload.assert_called_once_with("wkld123")

    @pytest.mark.asyncio
    async def test_workload_start(self):
        """Test workload_start tool."""
        import wapi_mcp_server as mcp

        mock_client = AsyncMock()
        mock_client.start_workload = AsyncMock(return_value={
            "id": "wkld123",
            "status": "starting"
        })

        with patch('wapi_mcp_server.get_client', return_value=mock_client):
            result = await mcp.workload_start("wkld123", wait_for_running=False)

        assert isinstance(result, str)
        assert "start" in result.lower()
        mock_client.start_workload.assert_called_once_with("wkld123")

    @pytest.mark.asyncio
    async def test_workload_update(self):
        """Test workload_update tool."""
        import wapi_mcp_server as mcp

        mock_client = AsyncMock()
        mock_client.patch_workload = AsyncMock(return_value={
            "id": "wkld123",
            "name": "updated-workload",
            "description": "Updated description",
            "importance": "high",
            "status": "running"
        })

        with patch('wapi_mcp_server.get_client', return_value=mock_client):
            result = await mcp.workload_update(
                "wkld123",
                name="updated-workload",
                description="Updated description",
                importance="high"
            )

        assert isinstance(result, str)
        assert "updated-workload" in result.lower()
        assert "high" in result.lower()
        mock_client.patch_workload.assert_called_once()


class TestArtifactCoreTools:
    """Unit tests for core artifact tools."""

    @pytest.mark.asyncio
    async def test_artifact_create(self):
        """Test artifact_create tool."""
        import wapi_mcp_server as mcp

        mock_client = AsyncMock()
        mock_client.create_artifact = AsyncMock(return_value={
            "id": "art123",
            "name": "test-artifact",
            "status": "draft",
            "spec": {
                "type": "service",
                "containerGroups": [{
                    "containers": [{
                        "imageUri": "nginx:latest",
                        "port": 8080
                    }]
                }]
            }
        })

        with patch('wapi_mcp_server.get_client', return_value=mock_client):
            result = await mcp.artifact_create(
                name="test-artifact",
                image_uri="nginx:latest",
                port=8080
            )

        assert isinstance(result, str)
        assert "art123" in result
        assert "test-artifact" in result
        assert "draft" in result.lower()
        mock_client.create_artifact.assert_called_once()

    @pytest.mark.asyncio
    async def test_artifact_get(self):
        """Test artifact_get tool."""
        import wapi_mcp_server as mcp

        mock_client = AsyncMock()
        mock_client.get_artifact = AsyncMock(return_value={
            "id": "art123",
            "name": "test-artifact",
            "status": "locked",
            "spec": {
                "type": "service",
                "containerGroups": [{
                    "containers": [{
                        "imageUri": "nginx:latest"
                    }]
                }]
            }
        })

        with patch('wapi_mcp_server.get_client', return_value=mock_client):
            result = await mcp.artifact_get("art123")

        assert isinstance(result, str)
        assert "art123" in result
        mock_client.get_artifact.assert_called_once_with("art123")

    @pytest.mark.asyncio
    async def test_artifact_update(self):
        """Test artifact_update tool."""
        import wapi_mcp_server as mcp

        mock_client = AsyncMock()
        mock_client.get_artifact = AsyncMock(return_value={
            "id": "art123",
            "status": "draft",
            "spec": {
                "containerGroups": [{
                    "containers": [{
                        "name": "main",
                        "imageUri": "nginx:latest",
                        "port": 8080,
                        "primary": True,
                        "environmentVars": []
                    }]
                }]
            }
        })
        mock_client.patch_artifact = AsyncMock(return_value={
            "id": "art123",
            "status": "draft"
        })

        with patch('wapi_mcp_server.get_client', return_value=mock_client):
            result = await mcp.artifact_update(
                "art123",
                image_uri="nginx:alpine"
            )

        assert isinstance(result, str)
        assert "updated" in result.lower() or "art123" in result
        mock_client.get_artifact.assert_called_once_with("art123")
        mock_client.patch_artifact.assert_called_once()


class TestOTELTraceTools:
    """Unit tests for OTEL trace tools."""

    @pytest.mark.asyncio
    async def test_otel_traces(self):
        """Test otel_traces tool."""
        import wapi_mcp_server as mcp

        mock_client = AsyncMock()
        mock_client.list_otel_traces = AsyncMock(return_value={
            "data": [
                {
                    "traceId": "trace123",
                    "spanCount": 5,
                    "duration": 150,
                    "timestamp": "2024-01-15T10:00:00Z"
                },
                {
                    "traceId": "trace456",
                    "spanCount": 3,
                    "duration": 75,
                    "timestamp": "2024-01-15T10:01:00Z"
                }
            ]
        })

        with patch('wapi_mcp_server.get_client', return_value=mock_client):
            result = await mcp.otel_traces("wkld123")

        assert isinstance(result, str)
        assert "trace123" in result or "trace" in result.lower()
        mock_client.list_otel_traces.assert_called_once()

    @pytest.mark.asyncio
    async def test_otel_trace_get(self):
        """Test otel_trace_get tool."""
        import wapi_mcp_server as mcp

        mock_client = AsyncMock()
        mock_client.get_otel_trace = AsyncMock(return_value={
            "traceId": "trace123",
            "spans": [
                {
                    "spanId": "span1",
                    "name": "HTTP GET /api",
                    "duration": 50
                },
                {
                    "spanId": "span2",
                    "name": "Database query",
                    "duration": 100
                }
            ]
        })

        with patch('wapi_mcp_server.get_client', return_value=mock_client):
            result = await mcp.otel_trace_get("wkld123", "trace123")

        assert isinstance(result, str)
        assert "trace123" in result or "span" in result.lower()
        mock_client.get_otel_trace.assert_called_once_with("wkld123", "trace123")


