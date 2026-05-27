"""Artifact, build, and artifact-repository tools.

Tools call ``server.get_client()`` so test patches of
``wapi_mcp_server.get_client`` take effect.
"""

from typing import Optional
import json
import wapi_mcp_server as server
from wapi_mcp.helpers import format_created_at

from wapi_mcp_server import parse_json_param  # noqa: E402

from wapi_mcp_server import mcp, traced_tool  # noqa: E402


@mcp.tool()
@traced_tool
async def artifact_list(limit: int = 100, offset: int = 0, status: Optional[str] = None) -> str:
    """List artifacts with optional pagination and filtering.

    Args:
        limit: Maximum number of artifacts to return (default: 100)
        offset: Number of artifacts to skip (default: 0)
        status: Filter by status: 'draft' or 'locked'
    """
    client = await server.get_client()
    result = await client.list_artifacts(limit=limit, offset=offset, status=status)
    data = result.get("data", [])

    if not data:
        return "No artifacts found."

    rows = []
    for a in data:
        aid = a.get("id", "")
        name = a.get("name", "")
        astatus = a.get("status", "")
        atype = a.get("type", "")
        version = a.get("version", "")
        repo_id = a.get("artifactRepositoryId", "")
        rows.append(f"- {aid}: {name} | type={atype} | status={astatus} | v{version or 'N/A'} | repo={repo_id or 'none'}")

    return f"Found {len(data)} artifacts:\n" + "\n".join(rows)


@mcp.tool()
@traced_tool
async def artifact_search(query: str, limit: int = 100, offset: int = 0) -> str:
    """Search artifacts by name or other attributes.

    Args:
        query: Search query string
        limit: Maximum number of results (default: 100)
        offset: Number to skip for pagination (default: 0)
    """
    client = await server.get_client()
    result = await client.list_artifacts(limit=limit, offset=offset, search=query)
    data = result.get("data", [])

    if not data:
        return f"No artifacts found matching '{query}'."

    rows = []
    for a in data:
        aid = a.get("id", "")
        name = a.get("name", "")
        astatus = a.get("status", "")
        atype = a.get("type", "")
        rows.append(f"- {aid}: {name} | type={atype} | status={astatus}")

    return f"Found {len(data)} artifacts matching '{query}':\n" + "\n".join(rows)


@mcp.tool()
@traced_tool
async def artifact_get(artifact_id: str) -> str:
    """Get details of a specific artifact.

    Args:
        artifact_id: The artifact ID to retrieve
    """
    client = await server.get_client()
    artifact = await client.get_artifact(artifact_id)
    return f"Artifact {artifact_id}:\n{json.dumps(artifact, indent=2)}"


@mcp.tool()
@traced_tool
async def artifact_create(
    name: str,
    image_uri: str,
    port: int = 8000,
    description: Optional[str] = None,
    environment_vars: Optional[list[dict]] = None,
    readiness_probe_path: Optional[str] = None,
    liveness_probe_path: Optional[str] = None,
    entrypoint: Optional[list[str]] = None,
    artifact_type: str = "service",
) -> str:
    """Create a new container artifact (reusable workload template).

    Artifacts define WHAT to run — image, port, entrypoint, env vars, probes.
    They start in 'draft' status allowing iteration; use artifact_lock to make
    them immutable ('locked').

    Note: resources (CPU/memory/GPU, replicas, autoscaling) are NOT part of the
    artifact — they are set on the workload's runtime. Pass cpu/memory/gpu or
    resource_bundle_ids to workload_create, or change them later with
    workload_settings_update.

    IMPORTANT SCHEMA REQUIREMENTS:
    - type must be "service" (default) or "nim" for NVIDIA NIMs
    - Port must be >= 1024 (non-privileged ports only)
    - Entrypoint must be array of strings: ["python", "-m", "app"]

    Args:
        name: Artifact name (required)
        image_uri: Container image URI (e.g., "docker.io/user/image:tag")
        port: Container port, must be >= 1024 (default: 8000)
        description: Optional artifact description
        environment_vars: List of {"name": "VAR", "value": "val"} environment variables
        readiness_probe_path: HTTP path for readiness probe (e.g., "/readyz")
        liveness_probe_path: HTTP path for liveness probe (e.g., "/healthz")
        entrypoint: Container entrypoint as array (e.g., ["python", "-m", "myapp"])
        artifact_type: "service" (default) or "nim"

    Returns artifact in 'draft' status. Use artifact_lock to make immutable.
    """
    if port < 1024:
        return f"Error: Port must be >= 1024 (got {port}). Non-privileged ports only."

    # Parse list parameters that may have been stringified by MCP client
    environment_vars = parse_json_param(environment_vars, "environment_vars")
    entrypoint = parse_json_param(entrypoint, "entrypoint")

    client = await server.get_client()

    # Build container spec. Resources are a runtime concern (set on the workload),
    # not part of the artifact's Container schema.
    container: dict = {
        "name": "main",
        "imageUri": image_uri,
        "port": port,
        "primary": True,
    }

    if entrypoint:
        container["entrypoint"] = entrypoint

    if environment_vars:
        container["environmentVars"] = environment_vars

    if readiness_probe_path:
        container["readinessProbe"] = {
            "path": readiness_probe_path,
            "port": port,
            "initialDelaySeconds": 10,
        }

    if liveness_probe_path:
        container["livenessProbe"] = {
            "path": liveness_probe_path,
            "port": port,
            "initialDelaySeconds": 30,
        }

    # Build artifact payload
    payload: dict = {
        "name": name,
        "spec": {
            "type": artifact_type,
            "containerGroups": [{
                "containers": [container]
            }]
        },
    }

    if description:
        payload["description"] = description

    artifact = await client.create_artifact(payload)
    artifact_id = artifact.get("id", "")

    return f"""Created artifact: {artifact_id}
Name: {name}
Type: {artifact_type}
Image: {image_uri}
Status: {artifact.get("status", "draft")}

Use this artifact_id when calling workload_create with artifact_id parameter.
To make immutable for production: artifact_lock(artifact_id="{artifact_id}")

Full response:
{json.dumps(artifact, indent=2)}"""


@mcp.tool()
@traced_tool
async def artifact_update(
    artifact_id: str,
    name: Optional[str] = None,
    description: Optional[str] = None,
    image_uri: Optional[str] = None,
    port: Optional[int] = None,
    environment_vars: Optional[list[dict]] = None,
    readiness_probe_path: Optional[str] = None,
    liveness_probe_path: Optional[str] = None,
    entrypoint: Optional[list[str]] = None,
) -> str:
    """Update an artifact's spec/metadata. Provide only the fields to change.

    DRAFT artifacts are edited in place.

    LOCKED artifacts are immutable, so they cannot be edited directly. When the
    target is locked, this tool instead CLONES it into a new DRAFT under the same
    artifact repository and applies the edits to that clone — the original locked
    artifact is left untouched. The new draft's ID is returned; nothing is deployed.

    Note: resources (CPU/memory/GPU, replicas, autoscaling) live on the
    workload's runtime, not the artifact. To change them, use
    workload_settings_update — not this tool.

    To roll the updated artifact out to a running workload, use
    artifact_replacement_create (rollouts require draft<->draft / locked<->locked,
    so a workload on a locked artifact needs the new draft locked first).

    Args:
        artifact_id: The artifact ID to update
        name: New artifact name (also used as the clone name when the source is locked)
        description: New artifact description
        image_uri: New container image URI
        port: New container port (must be >= 1024)
        environment_vars: New environment variables (replaces existing)
        readiness_probe_path: New readiness probe path
        liveness_probe_path: New liveness probe path
        entrypoint: New container entrypoint as array
    """
    if port is not None and port < 1024:
        return f"Error: Port must be >= 1024 (got {port}). Non-privileged ports only."

    # Parse list parameters that may have been stringified by MCP client
    environment_vars = parse_json_param(environment_vars, "environment_vars")
    entrypoint = parse_json_param(entrypoint, "entrypoint")

    client = await server.get_client()

    # Fetch the artifact first: we need its status (draft vs locked), name, repo,
    # and spec (as the merge base for container edits).
    current = await client.get_artifact(artifact_id)
    is_locked = current.get("status") == "locked"
    repo_id = current.get("artifactRepositoryId")
    source_name = current.get("name", "")

    # Locked artifacts are immutable. Clone into the same repository and apply the
    # edits to the resulting DRAFT; the original locked artifact is left untouched.
    target_id = artifact_id
    if is_locked:
        clone_name = name if name is not None else source_name
        clone = await client.clone_artifact(artifact_id, clone_name)
        target_id = clone.get("id", "")
        # The clone copies the source's fields (including repository) as a new
        # draft; use it as the merge base and don't re-apply the name below.
        current = clone
        name = None

    payload: dict = {}

    if name is not None:
        payload["name"] = name
    if description is not None:
        payload["description"] = description

    # Note: the update body (UpdateArtifactRequest) does not accept
    # artifactRepositoryId — repo association is set at create time and the clone
    # already inherits it, so there is nothing to send here.

    # Build container updates if any container fields provided
    container_fields = {
        "image_uri": image_uri, "port": port,
        "environment_vars": environment_vars, "readiness_probe_path": readiness_probe_path,
        "liveness_probe_path": liveness_probe_path, "entrypoint": entrypoint,
    }

    if any(v is not None for v in container_fields.values()):
        current_spec = current.get("spec", {})
        container_groups = current_spec.get("containerGroups", [{}])
        group0 = dict(container_groups[0]) if container_groups else {}
        containers = group0.get("containers") or [{}]
        container = containers[0]

        # Update container fields
        if image_uri is not None:
            container["imageUri"] = image_uri
        if port is not None:
            container["port"] = port
        if entrypoint is not None:
            container["entrypoint"] = entrypoint
        if environment_vars is not None:
            container["environmentVars"] = environment_vars

        # Update probes
        if readiness_probe_path is not None:
            container["readinessProbe"] = {
                "path": readiness_probe_path,
                "port": container.get("port", 8000),
                "initialDelaySeconds": 10,
            }
        if liveness_probe_path is not None:
            container["livenessProbe"] = {
                "path": liveness_probe_path,
                "port": container.get("port", 8000),
                "initialDelaySeconds": 30,
            }

        # Rebuild spec. The write model (UpdateArtifactRequest.spec =
        # MultiContainerArtifactSpec) only permits `containerGroups` — NOT the
        # `type` discriminator that the read model carries. Preserve the existing
        # group (name + any sibling containers) with the updated container.
        group0["containers"] = containers
        payload["spec"] = {"containerGroups": [group0]}

    # For a locked source the clone alone may already capture the change (e.g. a
    # rename), so an empty payload there is fine — for a draft it is an error.
    if not payload and not is_locked:
        return "Error: No fields provided to update."

    artifact = await client.patch_artifact(target_id, payload) if payload else current

    if is_locked:
        new_repo = artifact.get("artifactRepositoryId") or repo_id or "N/A"
        return f"""Source artifact {artifact_id} is LOCKED (immutable) — created a new DRAFT clone instead.

New draft artifact: {target_id}
Name: {artifact.get("name", "N/A")}
Status: {artifact.get("status", "draft")}
Artifact repository: {new_repo} (same as source)

Your edits were applied to the new draft; the original locked artifact is unchanged.

To deploy it to a workload (rollouts require draft<->draft / locked<->locked):
  - Workload running a LOCKED artifact: lock the new draft first, then roll out:
      artifact_lock(artifact_id="{target_id}")
      artifact_replacement_create(workload_id="<id>", artifact_id="{target_id}")
  - Workload running a DRAFT artifact: roll it out directly:
      artifact_replacement_create(workload_id="<id>", artifact_id="{target_id}")"""

    return f"""Updated artifact {artifact_id}:
Status: {artifact.get("status", "unknown")}

Changes applied. To roll the update out to a running workload (zero downtime):
  artifact_replacement_create(workload_id="<id>", artifact_id="{artifact_id}")

Full response:
{json.dumps(artifact, indent=2)}"""


@mcp.tool()
@traced_tool
async def artifact_clone(artifact_id: str, new_name: str) -> str:
    """Clone an existing artifact.

    Creates a new artifact with the same configuration as the original.
    The cloned artifact starts in 'draft' status, allowing modifications.

    Args:
        artifact_id: The artifact ID to clone
        new_name: Name for the cloned artifact
    """
    client = await server.get_client()
    artifact = await client.clone_artifact(artifact_id, new_name)

    return f"""Cloned artifact successfully!

Original: {artifact_id}
New Artifact ID: {artifact.get("id", "")}
Name: {artifact.get("name", "")}
Status: {artifact.get("status", "draft")}
Type: {artifact.get("type", "")}

Full response:
{json.dumps(artifact, indent=2)}"""


@mcp.tool()
@traced_tool
async def artifact_build_list(artifact_id: str, limit: int = 10, offset: int = 0) -> str:
    """List image builds for an artifact.

    Shows build history for artifacts that use server-side image building
    (imageBuildConfig with codeRef to Files API).

    Args:
        artifact_id: The artifact ID
        limit: Maximum number of builds to return (default: 10)
        offset: Number to skip for pagination (default: 0)
    """
    client = await server.get_client()
    result = await client.list_artifact_builds(artifact_id, limit=limit, offset=offset)
    data = result.get("data", [])

    if not data:
        return f"No builds found for artifact {artifact_id}."

    rows = []
    for b in data:
        bid = b.get("id", "")
        status = b.get("status", "")
        created = format_created_at(b.get("createdAt", ""))
        rows.append(f"- {bid}: status={status} | created={created}")

    return f"Found {len(data)} builds for artifact {artifact_id}:\n" + "\n".join(rows)


@mcp.tool()
@traced_tool
async def artifact_build_trigger(artifact_id: str) -> str:
    """Trigger an image build for a draft artifact.

    Starts a server-side image build for artifacts with imageBuildConfig
    (codeRef pointing to Files API). Only works for draft artifacts.

    Args:
        artifact_id: The artifact ID to build
    """
    client = await server.get_client()
    result = await client.trigger_artifact_build(artifact_id)
    build_ids = result.get("buildIds", [])

    if not build_ids:
        return f"Build triggered for artifact {artifact_id} but no build IDs returned."

    return f"""Build triggered successfully for artifact {artifact_id}!

Build IDs: {", ".join(build_ids)}

Use artifact_build_get(artifact_id, build_id) to check build status.
Use artifact_build_logs(artifact_id, build_id) to view build logs."""


@mcp.tool()
@traced_tool
async def artifact_build_get(artifact_id: str, build_id: str) -> str:
    """Get details of a specific image build.

    Args:
        artifact_id: The artifact ID
        build_id: The build ID to retrieve
    """
    client = await server.get_client()
    build = await client.get_artifact_build(artifact_id, build_id)

    status = build.get("status", "")
    created = format_created_at(build.get("createdAt", ""))
    updated = format_created_at(build.get("updatedAt", ""))

    result = f"""Build {build_id}:
Artifact: {artifact_id}
Status: {status}
Created: {created}
Updated: {updated}
"""

    if status == "FAILED":
        result += "\nBuild FAILED. Use artifact_build_logs() to see error details."
    elif status == "COMPLETED" or status == "BUILT":
        result += "\nBuild completed successfully!"
    elif status in ("PENDING", "IN_PROGRESS"):
        result += "\nBuild in progress. Check again later."

    return result


@mcp.tool()
@traced_tool
async def artifact_build_delete(artifact_id: str, build_id: str) -> str:
    """Cancel or delete an image build for a DRAFT artifact.

    Only works for draft artifacts; builds for locked (immutable) artifacts
    cannot be deleted.

    Args:
        artifact_id: The artifact ID
        build_id: The build ID to cancel/delete
    """
    client = await server.get_client()
    await client.delete_artifact_build(artifact_id, build_id)
    return f"Build {build_id} for artifact {artifact_id} cancelled/deleted."


@mcp.tool()
@traced_tool
async def artifact_build_logs(artifact_id: str, build_id: str) -> str:
    """Get logs for an image build.

    Use this to diagnose build failures or monitor build progress.

    Args:
        artifact_id: The artifact ID
        build_id: The build ID to get logs for
    """
    client = await server.get_client()
    logs = await client.get_artifact_build_logs(artifact_id, build_id)

    if not logs:
        return f"No logs available for build {build_id}."

    # Truncate if very long
    if len(logs) > 10000:
        return f"=== BUILD LOGS (truncated) ===\n...\n{logs[-10000:]}"

    return f"=== BUILD LOGS ===\n{logs}"


@mcp.tool()
@traced_tool
async def artifact_lock(artifact_id: str) -> str:
    """Lock an artifact (make it immutable), creating a new version in its repository.

    Once locked, an artifact cannot be modified. This is required for
    production workloads to ensure consistency.

    The artifact's repository association is set at creation time (and inherited by
    clones), so locking only flips the status — the update API does not accept an
    artifactRepositoryId. The artifact keeps whatever repository it already belongs to.

    Args:
        artifact_id: The artifact ID to lock
    """
    client = await server.get_client()
    artifact = await client.patch_artifact(artifact_id, {"status": "locked"})
    return f"Locked artifact {artifact_id}:\n{json.dumps(artifact, indent=2)}"


@mcp.tool()
@traced_tool
async def artifact_delete(artifact_ids: list[str]) -> str:
    """Delete one or more artifacts.

    Locked artifacts and artifacts with associated workloads cannot be deleted.

    Args:
        artifact_ids: List of artifact IDs to delete
    """
    # Parse list parameter that may have been stringified by MCP client
    artifact_ids = parse_json_param(artifact_ids, "artifact_ids")
    if not isinstance(artifact_ids, list):
        return f"Error: artifact_ids must be a list, got {type(artifact_ids).__name__}"

    client = await server.get_client()
    results = []

    for aid in artifact_ids:
        try:
            await client.delete_artifact(aid)
            results.append(f"Deleted {aid}")
        except Exception as e:
            results.append(f"Failed to delete {aid}: {e}")

    return "\n".join(results)


@mcp.tool()
@traced_tool
async def artifact_repo_list(limit: int = 100, offset: int = 0) -> str:
    """List artifact repositories.

    Artifact repositories are used for versioning artifacts.

    Args:
        limit: Maximum number to return (default: 100)
        offset: Number to skip for pagination (default: 0)
    """
    client = await server.get_client()
    result = await client.list_artifact_repositories(limit=limit, offset=offset)
    data = result.get("data", [])

    if not data:
        return "No artifact repositories found."

    rows = []
    for r in data:
        rid = r.get("id", "")
        name = r.get("name", "")
        num_artifacts = r.get("numArtifacts", 0)
        last_version = r.get("lastVersionNumber", 0)
        created = format_created_at(r.get("createdAt", ""))
        rows.append(f"- {rid}: {name} | artifacts={num_artifacts} | latest_v={last_version} | created={created}")

    return f"Found {len(data)} artifact repositories:\n" + "\n".join(rows)


@mcp.tool()
@traced_tool
async def artifact_repo_get(repo_id: str) -> str:
    """Get details of an artifact repository.

    Args:
        repo_id: The artifact repository ID
    """
    client = await server.get_client()
    repo = await client.get_artifact_repository(repo_id)
    return f"Artifact repository {repo_id}:\n{json.dumps(repo, indent=2)}"


@mcp.tool()
@traced_tool
async def artifact_repo_delete(repo_id: str) -> str:
    """Delete an artifact repository.

    Artifacts within the repository are cascade-deleted unless they are
    locked or still in use by workloads.

    Args:
        repo_id: The artifact repository ID to delete
    """
    client = await server.get_client()
    await client.delete_artifact_repository(repo_id)
    return f"Deleted artifact repository {repo_id}"


__all__ = [
    "artifact_list",
    "artifact_search",
    "artifact_get",
    "artifact_create",
    "artifact_update",
    "artifact_clone",
    "artifact_build_list",
    "artifact_build_trigger",
    "artifact_build_get",
    "artifact_build_delete",
    "artifact_build_logs",
    "artifact_lock",
    "artifact_delete",
    "artifact_repo_list",
    "artifact_repo_get",
    "artifact_repo_delete",
]
