"""
Async HTTP client wrapper for the Workload API.

This module provides the WapiClient class for interacting with the
DataRobot Workload API, including workloads, artifacts, artifact repositories,
and bundles.
"""

import time
from typing import Any, Dict, List, Optional

import aiohttp

from .exceptions import WapiAPIError, WapiConfigError
from .telemetry import LOG, record_api_request


class WapiClient:
    """Async HTTP client wrapper for the Workload API."""

    def __init__(self, base_url: str, token: str, timeout: int = 30):
        if not base_url:
            raise WapiConfigError("DATAROBOT_API_ENDPOINT is not set")
        if not token:
            raise WapiConfigError("DATAROBOT_API_TOKEN is not set")

        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self._session: Optional[aiohttp.ClientSession] = None

    async def __aenter__(self) -> "WapiClient":
        """Enter async context - create session."""
        self._session = aiohttp.ClientSession(
            timeout=self.timeout,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
            },
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Exit async context - close session."""
        if self._session:
            await self._session.close()
            self._session = None

    @property
    def session(self) -> aiohttp.ClientSession:
        """Get the active session, creating one if needed."""
        if self._session is None:
            self._session = aiohttp.ClientSession(
                timeout=self.timeout,
                headers={
                    "Authorization": f"Bearer {self.token}",
                    "Content-Type": "application/json",
                },
            )
        return self._session

    def _build_url(self, path: str) -> str:
        """Build a full URL from a path."""
        # If base_url ends with /api/v2 and path starts with /api/v2, avoid duplication
        base = self.base_url
        if base.endswith("/api/v2") and path.startswith("/api/v2"):
            base = base[:-7]  # Remove /api/v2 from base
        if path.startswith("/"):
            url = f"{base}{path}"
        else:
            url = f"{base}/{path}"
        # Ensure URL ends with trailing slash (required by DataRobot API)
        if not url.endswith("/") and "?" not in url:
            url = url + "/"
        return url

    async def request(
        self,
        method: str,
        path: str,
        *,
        json_body: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Perform an async HTTP request and raise on non-2xx response."""
        url = self._build_url(path)
        LOG.debug("HTTP %s %s", method, url)

        start_time = time.time()
        status_code = 0

        try:
            async with self.session.request(
                method=method.upper(),
                url=url,
                json=json_body,
                params=params,
            ) as resp:
                status_code = resp.status

                if resp.status >= 400:
                    text = await resp.text()
                    LOG.error("Request failed: %s %s -> %s", method, url, resp.status)
                    raise WapiAPIError(
                        status_code=resp.status,
                        method=method.upper(),
                        url=url,
                        response_body=text
                    )

                # Return JSON or empty dict for no content
                if resp.status == 204 or resp.content_length == 0:
                    return {}
                return await resp.json()

        finally:
            duration_ms = (time.time() - start_time) * 1000
            record_api_request(method.upper(), path, status_code, duration_ms)

    async def _list_paginated(
        self,
        path: str,
        *,
        limit: int,
        offset: int,
        extra_params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Internal helper for paginated list APIs."""
        MAX_PAGE_SIZE = 100
        params_common = dict(extra_params or {})
        current_offset = offset

        if limit is None or limit <= 0:
            total_needed: Optional[int] = None
        else:
            total_needed = limit

        all_items: List[Dict[str, Any]] = []
        last_resp: Optional[Dict[str, Any]] = None

        while True:
            if total_needed is None:
                page_limit = MAX_PAGE_SIZE
            else:
                remaining = total_needed - len(all_items)
                if remaining <= 0:
                    break
                page_limit = min(MAX_PAGE_SIZE, remaining)

            page_params = dict(params_common)
            page_params["limit"] = page_limit
            page_params["offset"] = current_offset

            resp_json = await self.request("GET", path, params=page_params)
            last_resp = resp_json
            page_data = resp_json.get("data") or []

            if not page_data:
                break

            all_items.extend(page_data)

            if len(page_data) < page_limit:
                break

            current_offset += page_limit

        result: Dict[str, Any] = {"data": all_items}
        if last_resp is not None:
            if "total" in last_resp:
                result["total"] = last_resp["total"]
            if "totalCount" in last_resp:
                result["totalCount"] = last_resp["totalCount"]
        return result

    # -------------------- Workloads ------------------------------------

    async def create_workload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new workload."""
        return await self.request("POST", "/api/v2/workloads/", json_body=payload)

    async def get_workload(self, workload_id: str) -> Dict[str, Any]:
        """Get a workload by ID."""
        return await self.request("GET", f"/api/v2/workloads/{workload_id}/")

    async def start_workload(self, workload_id: str) -> Dict[str, Any]:
        """Start a stopped workload."""
        return await self.request("POST", f"/api/v2/workloads/{workload_id}/start/")

    async def stop_workload(self, workload_id: str) -> Dict[str, Any]:
        """Stop a running workload."""
        return await self.request("POST", f"/api/v2/workloads/{workload_id}/stop/")

    async def delete_workload(self, workload_id: str) -> None:
        """Delete a workload."""
        await self.request("DELETE", f"/api/v2/workloads/{workload_id}/")

    async def patch_workload(self, workload_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Update a workload (PATCH)."""
        return await self.request(
            "PATCH", f"/api/v2/workloads/{workload_id}/", json_body=payload
        )

    async def list_workloads(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        search: Optional[str] = None,
        order_by: Optional[str] = "-createdAt",
        ids: Optional[List[str]] = None,
        status: Optional[List[str]] = None,
        importance: Optional[List[str]] = None,
        artifact_id: Optional[str] = None,
        artifact_status: Optional[List[str]] = None,
        repository_id: Optional[str] = None,
        created_by: Optional[str] = None,
        tag_keys: Optional[List[str]] = None,
        tag_values: Optional[List[str]] = None,
        service_stats: bool = False,
    ) -> Dict[str, Any]:
        """List workloads with optional filtering."""
        extra_params: Dict[str, Any] = {}
        if search is not None:
            extra_params["search"] = search
        if order_by is not None:
            extra_params["orderBy"] = order_by
        if ids:
            extra_params["ids"] = ids
        if status:
            extra_params["status"] = status
        if importance:
            extra_params["importance"] = importance
        if artifact_id:
            extra_params["artifactId"] = artifact_id
        if artifact_status:
            extra_params["artifactStatus"] = artifact_status
        if repository_id:
            extra_params["repositoryId"] = repository_id
        if created_by:
            extra_params["createdBy"] = created_by
        if tag_keys:
            extra_params["tagKeys"] = tag_keys
        if tag_values:
            extra_params["tagValues"] = tag_values
        if service_stats:
            extra_params["serviceStats"] = "true"

        return await self._list_paginated(
            "/api/v2/workloads/",
            limit=limit,
            offset=offset,
            extra_params=extra_params,
        )

    async def get_workload_settings(self, workload_id: str) -> Dict[str, Any]:
        """Get workload settings."""
        return await self.request("GET", f"/api/v2/workloads/{workload_id}/settings/")

    async def update_workload_settings(self, workload_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Update workload settings."""
        return await self.request(
            "PATCH", f"/api/v2/workloads/{workload_id}/settings/", json_body=payload
        )

    async def get_workload_stats(
        self,
        workload_id: str,
        *,
        proton_id: Optional[str] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get workload statistics."""
        params: Dict[str, Any] = {}
        if proton_id:
            params["protonId"] = proton_id
        if start_time:
            params["startTime"] = start_time
        if end_time:
            params["endTime"] = end_time
        return await self.request(
            "GET", f"/api/v2/workloads/{workload_id}/stats/", params=params
        )

    async def reset_workload_stats(
        self,
        workload_id: str,
        *,
        proton_id: Optional[str] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
    ) -> None:
        """Reset/clear workload statistics."""
        params: Dict[str, Any] = {}
        if proton_id:
            params["protonId"] = proton_id
        if start_time:
            params["startTime"] = start_time
        if end_time:
            params["endTime"] = end_time
        await self.request(
            "DELETE", f"/api/v2/workloads/{workload_id}/stats/", params=params
        )

    async def get_workload_metric(
        self,
        workload_id: str,
        metric_name: str,
        *,
        proton_id: Optional[str] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        resolution: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get a specific metric over time for a workload."""
        params: Dict[str, Any] = {}
        if proton_id:
            params["protonId"] = proton_id
        if start_time:
            params["startTime"] = start_time
        if end_time:
            params["endTime"] = end_time
        if resolution:
            params["resolution"] = resolution
        return await self.request(
            "GET", f"/api/v2/workloads/{workload_id}/stats/{metric_name}/", params=params
        )

    async def get_all_workloads_stats(
        self,
        *,
        search: Optional[str] = None,
        status: Optional[List[str]] = None,
        importance: Optional[List[str]] = None,
        artifact_status: Optional[List[str]] = None,
        artifact_id: Optional[str] = None,
        repository_id: Optional[str] = None,
        created_by: Optional[str] = None,
        ids: Optional[List[str]] = None,
        tag_keys: Optional[List[str]] = None,
        tag_values: Optional[List[str]] = None,
        order_by: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get aggregated stats across all workloads."""
        params: Dict[str, Any] = {}
        if search:
            params["search"] = search
        if status:
            params["status"] = status
        if importance:
            params["importance"] = importance
        if artifact_status:
            params["artifactStatus"] = artifact_status
        if artifact_id:
            params["artifactId"] = artifact_id
        if repository_id:
            params["repositoryId"] = repository_id
        if created_by:
            params["createdBy"] = created_by
        if ids:
            params["ids"] = ids
        if tag_keys:
            params["tagKeys"] = tag_keys
        if tag_values:
            params["tagValues"] = tag_values
        if order_by:
            params["orderBy"] = order_by
        return await self.request("GET", "/api/v2/workloads/stats/", params=params)

    async def get_workload_history(
        self,
        workload_id: str,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> Dict[str, Any]:
        """Get artifact deployment history for a workload."""
        return await self._list_paginated(
            f"/api/v2/workloads/{workload_id}/history/",
            limit=limit,
            offset=offset,
        )

    async def get_workload_events(
        self,
        workload_id: str,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> Dict[str, Any]:
        """Get workload events."""
        params = {"limit": limit, "offset": offset}
        return await self.request(
            "GET", f"/api/v2/workloads/{workload_id}/events/", params=params
        )

    async def list_workload_protons(
        self,
        workload_id: str,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> Dict[str, Any]:
        """List protons for a workload."""
        return await self._list_paginated(
            f"/api/v2/workloads/{workload_id}/protons/",
            limit=limit,
            offset=offset,
        )

    async def get_workload_proton(self, workload_id: str, proton_id: str) -> Dict[str, Any]:
        """Get a specific proton for a workload."""
        return await self.request(
            "GET", f"/api/v2/workloads/{workload_id}/protons/{proton_id}/",
        )

    async def get_proton_status_details(self, workload_id: str, proton_id: str) -> Dict[str, Any]:
        """Get per-replica status details for a proton."""
        return await self.request(
            "GET", f"/api/v2/workloads/{workload_id}/protons/{proton_id}/statusDetails/",
        )

    async def promote_workload(self, workload_id: str) -> Dict[str, Any]:
        """Promote a workload's draft artifact to locked."""
        return await self.request(
            "POST", f"/api/v2/workloads/{workload_id}/promote/",
        )

    async def get_workload_related(self, workload_id: str) -> Dict[str, Any]:
        """Get related entities for a workload."""
        return await self.request("GET", f"/api/v2/workloads/{workload_id}/related/")

    async def get_workload_shared_roles(
        self,
        workload_id: str,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> Dict[str, Any]:
        """Get shared roles for a workload."""
        return await self._list_paginated(
            f"/api/v2/workloads/{workload_id}/sharedRoles/",
            limit=limit,
            offset=offset,
        )

    async def update_workload_shared_roles(
        self,
        workload_id: str,
        payload: Dict[str, Any],
    ) -> None:
        """Update shared roles for a workload."""
        await self.request(
            "PATCH", f"/api/v2/workloads/{workload_id}/sharedRoles/",
            json_body=payload,
        )

    # -------------------- Artifacts ------------------------------------

    async def list_artifacts(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        status: Optional[str] = None,
        order_by: Optional[str] = "-createdAt",
        search: Optional[str] = None,
        repository_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """List artifacts with optional filtering."""
        extra_params: Dict[str, Any] = {}
        if status is not None:
            extra_params["status"] = status
        if order_by is not None:
            extra_params["orderBy"] = order_by
        if search is not None:
            extra_params["search"] = search
        if repository_id is not None:
            extra_params["repositoryId"] = repository_id

        return await self._list_paginated(
            "/api/v2/artifacts/",
            limit=limit,
            offset=offset,
            extra_params=extra_params,
        )

    async def create_artifact(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new artifact."""
        return await self.request("POST", "/api/v2/artifacts/", json_body=payload)

    async def get_artifact(self, artifact_id: str) -> Dict[str, Any]:
        """Get an artifact by ID."""
        return await self.request("GET", f"/api/v2/artifacts/{artifact_id}/")

    async def put_artifact(self, artifact_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Replace an artifact (PUT)."""
        return await self.request(
            "PUT", f"/api/v2/artifacts/{artifact_id}/", json_body=payload
        )

    async def patch_artifact(self, artifact_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Update an artifact (PATCH)."""
        return await self.request(
            "PATCH", f"/api/v2/artifacts/{artifact_id}/", json_body=payload
        )

    async def delete_artifact(self, artifact_id: str) -> None:
        """Delete an artifact."""
        await self.request("DELETE", f"/api/v2/artifacts/{artifact_id}/")

    async def get_artifact_shared_roles(
        self,
        artifact_id: str,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> Dict[str, Any]:
        """Get shared roles for an artifact."""
        return await self._list_paginated(
            f"/api/v2/artifacts/{artifact_id}/sharedRoles/",
            limit=limit,
            offset=offset,
        )

    async def update_artifact_shared_roles(
        self,
        artifact_id: str,
        payload: Dict[str, Any],
    ) -> None:
        """Update shared roles for an artifact."""
        await self.request(
            "PATCH", f"/api/v2/artifacts/{artifact_id}/sharedRoles/",
            json_body=payload,
        )

    async def clone_artifact(self, artifact_id: str, name: str) -> Dict[str, Any]:
        """Clone an existing artifact."""
        return await self.request(
            "POST", f"/api/v2/artifacts/{artifact_id}/clone/",
            json_body={"name": name},
        )

    async def list_artifact_builds(
        self,
        artifact_id: str,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> Dict[str, Any]:
        """List image builds for an artifact."""
        return await self._list_paginated(
            f"/api/v2/artifacts/{artifact_id}/builds/",
            limit=limit,
            offset=offset,
        )

    async def trigger_artifact_build(self, artifact_id: str) -> Dict[str, Any]:
        """Trigger an image build for a draft artifact."""
        return await self.request(
            "POST", f"/api/v2/artifacts/{artifact_id}/builds/",
        )

    async def get_artifact_build(self, artifact_id: str, build_id: str) -> Dict[str, Any]:
        """Get an image build by ID."""
        return await self.request(
            "GET", f"/api/v2/artifacts/{artifact_id}/builds/{build_id}/",
        )

    async def get_artifact_build_logs(self, artifact_id: str, build_id: str) -> str:
        """Get logs for an image build."""
        url = self._build_url(f"/api/v2/artifacts/{artifact_id}/builds/{build_id}/logs/")
        async with self.session.request("GET", url) as resp:
            if resp.status >= 400:
                text = await resp.text()
                raise WapiAPIError(
                    status_code=resp.status,
                    method="GET",
                    url=url,
                    response_body=text
                )
            return await resp.text()

    # -------------------- Artifact Repositories -------------------------

    async def list_artifact_repositories(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        search: Optional[str] = None,
        order_by: Optional[str] = "-createdAt",
    ) -> Dict[str, Any]:
        """List artifact repositories."""
        extra_params: Dict[str, Any] = {}
        if search is not None:
            extra_params["search"] = search
        if order_by is not None:
            extra_params["orderBy"] = order_by

        return await self._list_paginated(
            "/api/v2/artifactRepositories/",
            limit=limit,
            offset=offset,
            extra_params=extra_params,
        )

    async def get_artifact_repository(self, repo_id: str) -> Dict[str, Any]:
        """Get an artifact repository by ID."""
        return await self.request("GET", f"/api/v2/artifactRepositories/{repo_id}/")

    async def delete_artifact_repository(self, repo_id: str) -> None:
        """Delete an artifact repository."""
        await self.request("DELETE", f"/api/v2/artifactRepositories/{repo_id}/")

    # -------------------- Bundles --------------------------------------

    async def list_bundles(self) -> Dict[str, Any]:
        """List available compute bundles."""
        return await self.request("GET", "/api/v2/mlops/compute/bundles/")

    # -------------------- OTEL (OpenTelemetry) ---------------------------
    #
    # OTEL data is aggregated at the workload level across all protons.
    # No per-proton OTEL filtering is available.

    async def get_otel_logs(
        self,
        workload_id: str,
        *,
        limit: int = 100,
        offset: int = 0,
        level: Optional[str] = None,
        includes: Optional[List[str]] = None,
        excludes: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Get OpenTelemetry logs for a workload."""
        params: Dict[str, Any] = {"limit": limit, "offset": offset}
        if level:
            params["level"] = level
        if includes:
            params["includes"] = includes
        if excludes:
            params["excludes"] = excludes
        return await self.request(
            "GET", f"/api/v2/otel/workload/{workload_id}/logs/", params=params
        )

    async def list_otel_traces(
        self,
        workload_id: str,
        *,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
    ) -> Dict[str, Any]:
        """List OpenTelemetry traces for a workload."""
        params: Dict[str, Any] = {}
        if start_time:
            params["startTime"] = start_time
        if end_time:
            params["endTime"] = end_time
        return await self.request(
            "GET", f"/api/v2/otel/workload/{workload_id}/traces/", params=params
        )

    async def get_otel_trace(self, workload_id: str, trace_id: str) -> Dict[str, Any]:
        """Get a specific OpenTelemetry trace."""
        return await self.request(
            "GET", f"/api/v2/otel/workload/{workload_id}/traces/{trace_id}/"
        )

    async def get_otel_metrics(
        self,
        workload_id: str,
        *,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get autocollected OpenTelemetry metrics for a workload."""
        params: Dict[str, Any] = {}
        if start_time:
            params["startTime"] = start_time
        if end_time:
            params["endTime"] = end_time
        return await self.request(
            "GET", f"/api/v2/otel/workload/{workload_id}/metrics/autocollectedValues/", params=params
        )

    # -------------------- Credentials ------------------------------------
    #
    # DataRobot credentials can be injected as environment variables in workloads.
    # Use CredentialEnvironmentVariable with source="dr-credential".

    async def list_credentials(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        types: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """List available DataRobot credentials.

        Args:
            limit: Maximum number of results
            offset: Number of results to skip
            types: Filter by credential types (e.g., ["s3", "basic", "gcp"])
        """
        params: Dict[str, Any] = {"limit": limit, "offset": offset}
        if types:
            params["types"] = types
        return await self.request("GET", "/api/v2/credentials/", params=params)

    async def get_credential(self, credential_id: str) -> Dict[str, Any]:
        """Get a credential by ID."""
        return await self.request("GET", f"/api/v2/credentials/{credential_id}/")

    # -------------------- Cleanup --------------------------------------

    async def close(self) -> None:
        """Close the client session."""
        if self._session:
            await self._session.close()
            self._session = None
