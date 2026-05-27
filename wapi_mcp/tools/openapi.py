"""OpenAPI spec query tool.

The spec loaders/cache/constants stay in wapi_mcp_server (so test monkeypatches
of OPENAPI_SPEC_PATH/_openapi_cache/_load_openapi_spec_remote keep working); this
module references them via ``server.`` so those patches take effect.
"""

from typing import Optional

import wapi_mcp_server as server

from wapi_mcp_server import mcp, traced_tool  # noqa: E402


@mcp.tool()
@traced_tool
async def read_openapi_spec(
    section: Optional[str] = None,
    search: Optional[str] = None,
    schema_name: Optional[str] = None,
    path: Optional[str] = None,
    source: str = "local",
) -> str:
    """Query the Workload API OpenAPI specification.

    Use this tool to understand the API schema, available endpoints, request/response
    formats, and valid field values before making API calls. Queries are targeted
    and return bounded output — the full ~160KB spec is never returned at once, so
    request the specific schema_name, path, search term, or section list you need.

    Two sources are available:
    - "local" (default): the spec bundled with this server. Fast, offline.
    - "remote" (aka "master"/"live"): fetched from {DATAROBOT_API_ENDPOINT}/openapi.yaml
      — the source of truth for the deployed environment. Use this when you suspect
      the bundled spec is behind, or to confirm what the live API actually accepts.

    USAGE EXAMPLES:
        # Overview of the bundled spec
        read_openapi_spec()

        # Get a specific schema by name
        read_openapi_spec(schema_name="CreateWorkloadRequest")

        # Search the LIVE master spec for a keyword
        read_openapi_spec(search="replica", source="remote")

        # Inspect an endpoint on the live spec
        read_openapi_spec(path="/workloads", source="master")

    Args:
        section: Section to retrieve: "info", "paths", or "schemas" (lists names,
                 not full bodies). There is no full-spec dump — use targeted queries.
        search: Search for a keyword in schema/field names (case-insensitive)
        schema_name: Get a specific schema definition by exact name
        path: Get details for a specific API path (e.g., "/workloads")
        source: Which spec to query: "local" (bundled, default) or "remote"/"master"/
                "live" (fetched from {DATAROBOT_API_ENDPOINT}/openapi.yaml).

    Returns formatted spec information.
    """
    use_remote = source.lower() in server.REMOTE_SOURCE_ALIASES
    try:
        spec = await server._load_openapi_spec_remote() if use_remote else server._load_openapi_spec()
    except FileNotFoundError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error fetching master OpenAPI spec: {e}"

    source_label = "MASTER (live)" if use_remote else "local (bundled)"

    # Handle specific schema lookup
    if schema_name:
        schemas = spec.get("components", {}).get("schemas", {})
        if schema_name in schemas:
            return f"=== SCHEMA: {schema_name} ===\n\n{server._dump_capped(schemas[schema_name])}"
        for name, schema in schemas.items():
            if name.lower() == schema_name.lower():
                return f"=== SCHEMA: {name} ===\n\n{server._dump_capped(schema)}"
        similar = [n for n in schemas.keys() if schema_name.lower() in n.lower()]
        if similar:
            return f"Schema '{schema_name}' not found. Similar schemas:\n" + "\n".join(f"  - {n}" for n in similar[:10])
        return f"Schema '{schema_name}' not found. Use read_openapi_spec(section='schemas') to see all."

    # Handle specific path lookup
    if path:
        paths = spec.get("paths", {})
        if not path.startswith("/"):
            path = "/" + path
        if path in paths:
            return f"=== PATH: {path} ===\n\n{server._dump_capped(paths[path])}"
        matching = [p for p in paths.keys() if path in p]
        if matching:
            result = f"Paths matching '{path}':\n\n"
            for p in matching[:5]:
                result += f"=== {p} ===\n{server._dump_capped(paths[p])}\n\n"
            return result
        return f"Path '{path}' not found. Use read_openapi_spec(section='paths') to see all."

    # Handle search
    if search:
        search_lower = search.lower()
        results: dict[str, list[str]] = {"schemas": [], "paths": [], "fields": []}

        schemas = spec.get("components", {}).get("schemas", {})
        for name, schema in schemas.items():
            if search_lower in name.lower():
                results["schemas"].append(name)
            props = schema.get("properties", {})
            for prop_name in props.keys():
                if search_lower in prop_name.lower():
                    results["fields"].append(f"{name}.{prop_name}")

        paths = spec.get("paths", {})
        for path_name, path_def in paths.items():
            if search_lower in path_name.lower():
                results["paths"].append(path_name)
            for method, op in path_def.items():
                if isinstance(op, dict):
                    op_id = op.get("operationId", "")
                    summary = op.get("summary", "")
                    if search_lower in op_id.lower() or search_lower in summary.lower():
                        results["paths"].append(f"{method.upper()} {path_name}: {summary}")

        output = f"=== SEARCH RESULTS FOR '{search}' ===\n\n"
        if results["schemas"]:
            output += f"Matching schemas ({len(results['schemas'])}):\n"
            for s in results["schemas"][:15]:
                output += f"  - {s}\n"
            output += "\n"
        if results["paths"]:
            output += f"Matching paths ({len(results['paths'])}):\n"
            for p in results["paths"][:15]:
                output += f"  - {p}\n"
            output += "\n"
        if results["fields"]:
            output += f"Matching fields ({len(results['fields'])}):\n"
            for f in results["fields"][:20]:
                output += f"  - {f}\n"

        if not any(results.values()):
            output += "No matches found."

        return output

    # Handle section retrieval. Note: there is intentionally no "dump the whole
    # spec" option — the full spec is ~160KB and would flood the agent context.
    # Use targeted queries (schema_name, path, search) or the section lists below.
    if section == "all":
        return (
            "The full spec is too large to return (it would flood context). Query it "
            "in pieces instead:\n"
            "  read_openapi_spec(section='paths')   - list endpoints\n"
            "  read_openapi_spec(section='schemas') - list schemas\n"
            "  read_openapi_spec(schema_name='X')   - one schema\n"
            "  read_openapi_spec(path='/workloads') - one endpoint\n"
            "  read_openapi_spec(search='replica')  - search by keyword"
        )

    if section == "info":
        info = spec.get("info", {})
        return f"=== API INFO ===\n\n{server._dump_capped(info)}"

    if section == "schemas":
        schemas = spec.get("components", {}).get("schemas", {})
        output = f"=== AVAILABLE SCHEMAS ({len(schemas)}) ===\n\n"
        grouped: dict[str, list[str]] = {}
        for name in sorted(schemas.keys()):
            prefix = name.split("-")[0].rstrip("0123456789")
            if prefix not in grouped:
                grouped[prefix] = []
            grouped[prefix].append(name)

        for prefix in sorted(grouped.keys()):
            output += f"{prefix}:\n"
            for name in grouped[prefix]:
                desc = schemas[name].get("description", "")[:60]
                output += f"  - {name}"
                if desc:
                    output += f": {desc}"
                output += "\n"
            output += "\n"
        output += "\nUse read_openapi_spec(schema_name='SchemaName') to get full details."
        return output

    if section == "paths":
        paths = spec.get("paths", {})
        output = f"=== AVAILABLE PATHS ({len(paths)}) ===\n\n"
        for path_name in sorted(paths.keys()):
            methods = [m.upper() for m in paths[path_name].keys() if m in ("get", "post", "put", "patch", "delete")]
            output += f"  {', '.join(methods):20} {path_name}\n"
        output += "\nUse read_openapi_spec(path='/path') to get full details."
        return output

    # Default: show overview
    info = spec.get("info", {})
    paths = spec.get("paths", {})
    schemas = spec.get("components", {}).get("schemas", {})

    output = f"""=== WORKLOAD API OPENAPI SPEC OVERVIEW ===
Source: {source_label}

Title: {info.get('title', 'N/A')}
Version: {info.get('version', 'N/A')}

Available endpoints: {len(paths)}
Schema definitions: {len(schemas)}

COMMON QUERIES:
  read_openapi_spec(section="paths")     - List all API endpoints
  read_openapi_spec(section="schemas")   - List all schema definitions
  read_openapi_spec(schema_name="X")     - Get specific schema
  read_openapi_spec(path="/workloads")   - Get endpoint details
  read_openapi_spec(search="replica")    - Search for keyword
  read_openapi_spec(search="X", source="remote") - Query the live master spec

KEY PATHS:
"""
    for path_name in sorted(paths.keys())[:10]:
        methods = [m.upper() for m in paths[path_name].keys() if m in ("get", "post", "put", "patch", "delete")]
        output += f"  {', '.join(methods):20} {path_name}\n"

    if len(paths) > 10:
        output += f"  ... and {len(paths) - 10} more paths\n"

    return output


__all__ = ["read_openapi_spec"]
