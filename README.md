# DataRobot Workload API MCP Server

MCP server for the DataRobot Workload API. Manage workloads, artifacts, artifact repositories, and compute bundles through AI assistants.

Built with [FastMCP](https://github.com/jlowin/fastmcp) for clean, decorator-based tool definitions.

## Quick Start

### Environment Variables

```bash
export DATAROBOT_API_ENDPOINT="https://your-datarobot-instance.com/api/v2"
export DATAROBOT_API_TOKEN="your-api-token"
```

### Run Locally (stdio)

```bash
pip install -r requirements.txt
python wapi_mcp_server.py
```

### Run as Container (HTTP)

```bash
docker build -t wapi-mcp-server .
docker run -p 8000:8000 \
  -e DATAROBOT_API_ENDPOINT="$DATAROBOT_API_ENDPOINT" \
  -e DATAROBOT_API_TOKEN="$DATAROBOT_API_TOKEN" \
  wapi-mcp-server
```

## Deploy to DataRobot

This follows the development-to-production workflow: iterate on a workload with a draft artifact, then lock it for production use.

### Workflow Overview

| Phase | Action | Result |
|-------|--------|--------|
| Development | `POST /workloads` | Creates workload + draft artifact |
| Iteration | `PATCH /artifacts/{id}` | Update container spec, restart, test |
| Lock | `PATCH /artifacts/{id}` | Set `status: locked` (immutable) |
| Production | Deploy locked artifact | Production-ready workload |

### Step 1: Build and Push Docker Image

```bash
docker buildx build --platform linux/amd64 \
  -t ghcr.io/ahamino/datarobot-workload-api-mcp-server:dev \
  --push .
```

### Step 2: Create Development Workload

Create a workload with an inline artifact. The artifact is created with `status=draft` by default, allowing iteration:

```bash
curl -X POST "${DATAROBOT_API_ENDPOINT}/workloads/" \
  -H "Authorization: Bearer ${DATAROBOT_API_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "wapi-mcp-server-dev",
    "importance": "low",
    "artifact": {
      "name": "wapi-mcp-server-artifact",
      "description": "WAPI MCP Server - development",
      "spec": {
        "type": "service",
        "containerGroups": [{
          "name": "default",
          "containers": [{
            "name": "main",
            "imageUri": "ghcr.io/ahamino/datarobot-workload-api-mcp-server:latest",
            "port": 8000,
            "primary": true,
            "environmentVars": [
              {"name": "DATAROBOT_API_ENDPOINT", "value": "'"${DATAROBOT_API_ENDPOINT}"'"},
              {"name": "DATAROBOT_API_TOKEN", "value": "'"${DATAROBOT_API_TOKEN}"'"}
            ],
            "readinessProbe": {"path": "/readyz", "port": 8000, "initialDelaySeconds": 10},
            "livenessProbe": {"path": "/healthz", "port": 8000, "initialDelaySeconds": 30}
          }]
        }]
      }
    },
    "runtime": {
      "containerGroups": [{
        "name": "default",
        "replicaCount": 1,
        "containers": [{
          "name": "main",
          "resourceAllocation": {"cpu": 2, "memory": "4GB"}
        }]
      }]
    }
  }'
```

Save the returned IDs:

```bash
export WORKLOAD_ID=<id from response>
export ARTIFACT_ID=<artifactId from response>
```

Wait for running status:

```bash
curl -s "${DATAROBOT_API_ENDPOINT}/workloads/${WORKLOAD_ID}/" \
  -H "Authorization: Bearer ${DATAROBOT_API_TOKEN}" | jq '.status'
```

**Development URL:** `${DATAROBOT_API_ENDPOINT}/endpoints/workloads/${WORKLOAD_ID}/mcp`

### Step 3: Iterate on the Artifact

During development, update the artifact and restart the workload to test changes.

**Update artifact (PATCH):**

```bash
curl -X PATCH "${DATAROBOT_API_ENDPOINT}/artifacts/${ARTIFACT_ID}/" \
  -H "Authorization: Bearer ${DATAROBOT_API_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
    "description": "WAPI MCP Server - iteration 2",
    "spec": {
      "containerGroups": [{
        "name": "default",
        "containers": [{
          "name": "main",
          "imageUri": "ghcr.io/ahamino/datarobot-workload-api-mcp-server:v2",
          "port": 8000,
          "primary": true,
          "environmentVars": [
            {"name": "DATAROBOT_API_ENDPOINT", "value": "'"${DATAROBOT_API_ENDPOINT}"'"},
            {"name": "DATAROBOT_API_TOKEN", "value": "'"${DATAROBOT_API_TOKEN}"'"}
          ],
          "readinessProbe": {"path": "/readyz", "port": 8000, "initialDelaySeconds": 10},
          "livenessProbe": {"path": "/healthz", "port": 8000, "initialDelaySeconds": 30}
        }]
      }]
    }
  }'
```

**Restart workload to apply changes:**

```bash
curl -X POST "${DATAROBOT_API_ENDPOINT}/workloads/${WORKLOAD_ID}/stop/" \
  -H "Authorization: Bearer ${DATAROBOT_API_TOKEN}"

# Wait a few seconds, then start
curl -X POST "${DATAROBOT_API_ENDPOINT}/workloads/${WORKLOAD_ID}/start/" \
  -H "Authorization: Bearer ${DATAROBOT_API_TOKEN}"
```

Repeat until production-ready.

### Step 4: Lock Artifact for Production

When ready, change the artifact status from `draft` to `locked`:

```bash
curl -X PATCH "${DATAROBOT_API_ENDPOINT}/artifacts/${ARTIFACT_ID}/" \
  -H "Authorization: Bearer ${DATAROBOT_API_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"status": "locked"}'
```

**Important:** Once locked, the artifact is immutable and cannot be modified.

### Access URLs

| Resource | URL |
|----------|-----|
| Workload Endpoint | `${DATAROBOT_API_ENDPOINT}/endpoints/workloads/${WORKLOAD_ID}/mcp` |
| Console UI | `https://app.datarobot.com/console-nextgen/workloads/${WORKLOAD_ID}/overview` |

## Creating Workloads via MCP Tools

Once the MCP server is running, you can use AI assistants (like Claude) to create and manage workloads through natural language. The MCP tools provide a more intuitive interface than raw API calls.

### Example: Create a Workload

Ask your AI assistant:

> "Create a new workload called 'my-api-service' using the image `myregistry/my-app:latest` on port 8080 with 2 CPU cores and 2GB memory"

The assistant will use the `workload_create` tool with the appropriate parameters.

### Example: List and Search Workloads

> "List all running workloads"
> "Search for workloads with 'mcp' in the name"

### Example: Manage Workload Lifecycle

> "Stop the workload with ID abc123"
> "Start all stopped workloads"
> "Delete workloads that have been stopped for more than 7 days"

### Example: Update Resources

> "Scale the workload xyz to 3 replicas"
> "Update the workload to use 4GB memory"

### Example: Deploy New Versions

> "Deploy artifact version v2.0 to workload abc123"
> "Update the container image to myregistry/my-app:v2 and restart"

### Available MCP Tools for Workload Management

| Tool | Use Case |
|------|----------|
| `workload_create` | Create new workloads with inline or existing artifacts |
| `workload_list` | List workloads with filters (status, importance) |
| `workload_get` | Get detailed workload info including endpoint URL |
| `workload_start` / `workload_stop` | Control workload lifecycle |
| `workload_delete` | Remove workloads |
| `workload_settings_update` | Change replicas, resources |
| `artifact_update` | Update container spec (image, env vars, probes) |
| `bundle_list` | See available CPU/GPU resource bundles |

## Claude Desktop Configuration

### Local (stdio)

```json
{
  "mcpServers": {
    "wapi": {
      "command": "python",
      "args": ["/path/to/wapi_mcp_server.py"],
      "env": {
        "DATAROBOT_API_ENDPOINT": "https://your-instance.com/api/v2",
        "DATAROBOT_API_TOKEN": "your-token"
      }
    }
  }
}
```

### Remote (via Proxy)

The DataRobot gateway strips non-standard HTTP headers. The proxy translates MCP session headers:

- **Outgoing**: `mcp-session-id` -> `x-datarobot-mcp-session-id`
- **Incoming**: Reads from `x-datarobot-mcp-session-id` response header

**Option 1: Using start-mcp.sh (recommended)**

Set environment variables in your shell profile (`~/.zshrc` or `~/.bashrc`):

```bash
export DATAROBOT_API_ENDPOINT="https://your-instance.com/api/v2"
export DATAROBOT_API_TOKEN="your-token"
export WAPI_MCP_SERVER_WORKLOAD_ID="your-workload-id"
```

Then configure Claude Desktop:

```json
{
  "mcpServers": {
    "wapi": {
      "command": "/path/to/start-mcp.sh"
    }
  }
}
```

**Option 2: Direct configuration**

```json
{
  "mcpServers": {
    "wapi": {
      "command": "python",
      "args": [
        "/path/to/claude_desktop_proxy.py",
        "--url", "https://your-instance.com/api/v2/endpoints/workloads/WORKLOAD_ID/mcp",
        "--token", "your-token"
      ]
    }
  }
}
```

## Tools

### Workloads

| Tool | Description |
|------|-------------|
| `workload_list` | List workloads with pagination and filtering |
| `workload_search` | Search workloads by query |
| `workload_get` | Get workload details, status, and URLs |
| `workload_status` | Get detailed status with logs and conditions |
| `workload_create` | Create a new workload (supports autoscaling) |
| `workload_start` | Start a stopped workload |
| `workload_stop` | Stop running workloads |
| `workload_delete` | Delete workloads |
| `workload_update` | Update workload name, description, importance |
| `workload_settings_get` | Get workload runtime settings |
| `workload_settings_update` | Update replica count, resources, autoscaling |
| `workload_stats` | Get performance statistics |
| `workload_history` | Get artifact deployment/replacement history |
| `workload_events` | Get workload events |
| `workload_promote` | Promote draft artifact to locked (production) |
| `workload_related` | Get related entities (artifacts, etc.) |
| `workloads_stats_summary` | Get aggregated stats across all workloads |

### Protons (Deployment Instances)

| Tool | Description |
|------|-------------|
| `proton_list` | List protons for a workload |
| `proton_get` | Get proton details |
| `proton_status_details` | Get per-replica status (debugging) |

### Artifacts

| Tool | Description |
|------|-------------|
| `artifact_list` | List artifacts (filter by status: draft, locked) |
| `artifact_search` | Search artifacts |
| `artifact_get` | Get artifact details |
| `artifact_create` | Create an artifact |
| `artifact_update` | Update a draft artifact (PATCH) |
| `artifact_lock` | Lock an artifact (make immutable) |
| `artifact_delete` | Delete artifacts |
| `artifact_clone` | Clone an existing artifact |

### Artifact Builds (Image Building)

| Tool | Description |
|------|-------------|
| `artifact_build_list` | List image builds for an artifact |
| `artifact_build_trigger` | Trigger image build for draft artifact |
| `artifact_build_get` | Get build status |
| `artifact_build_logs` | Get build logs (for debugging)

### Artifact Repositories

| Tool | Description |
|------|-------------|
| `artifact_repo_list` | List artifact repositories |
| `artifact_repo_get` | Get repository details |
| `artifact_repo_delete` | Delete a repository |

### Bundles

| Tool | Description |
|------|-------------|
| `bundle_list` | List compute bundles (CPU/GPU configs) |

### OTEL (Observability)

| Tool | Description |
|------|-------------|
| `otel_logs` | Get application logs (auto-collected from stdout/stderr) |
| `otel_traces` | List request traces (requires app instrumentation) |
| `otel_trace_get` | Get detailed trace with spans |
| `otel_metrics` | Get resource metrics (requires app instrumentation) |

**Note:**
- **Logs** are automatically collected from all containers - no configuration needed
- **Traces** and **Metrics** require your application to be instrumented with OpenTelemetry
- All OTEL data is aggregated at the workload level across all protons

### OpenAPI Spec

| Tool | Description |
|------|-------------|
| `read_openapi_spec` | Query the Workload API OpenAPI specification |

The `read_openapi_spec` tool helps agents understand the API before making calls:

```python
# Get overview (paths, schemas count)
read_openapi_spec()

# List all endpoints
read_openapi_spec(section="paths")

# List all schema definitions
read_openapi_spec(section="schemas")

# Get specific schema details
read_openapi_spec(schema_name="CreateWorkloadRequest")

# Get endpoint details
read_openapi_spec(path="/workloads")

# Search for keywords
read_openapi_spec(search="replica")
```

## Project Structure

```
datarobot-workload-api-mcp-server/
├── wapi_mcp_server.py       # FastMCP server with tools
├── wapi_mcp/                # Core package
│   ├── client.py            # Async HTTP client (aiohttp)
│   ├── helpers.py           # Formatting and wait utilities
│   ├── exceptions.py        # Custom exceptions
│   └── telemetry.py         # OpenTelemetry integration
├── claude_desktop_proxy.py  # Proxy for remote MCP workloads
├── openapi.yaml             # Workload API OpenAPI spec
├── requirements.txt
├── Dockerfile
└── pyproject.toml
```

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `DATAROBOT_API_ENDPOINT` | Yes | Base URL of the API (e.g., `https://app.datarobot.com/api/v2`) |
| `DATAROBOT_API_TOKEN` | Yes | Bearer token for authentication |
| `WAPI_MCP_SERVER_WORKLOAD_ID` | For proxy | Workload ID for start-mcp.sh proxy script |
| `OPENAPI_SPEC_PATH` | No | Path to OpenAPI spec (default: /app/openapi.yaml) |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | No | OpenTelemetry collector endpoint |
| `OTEL_SERVICE_NAME` | No | Service name (default: wapi-mcp-server) |
| `LOG_LEVEL` | No | Logging level (default: INFO) |

## Health Endpoints

The server provides health check endpoints for container orchestration:

| Endpoint | Purpose | Success | Failure |
|----------|---------|---------|---------|
| `/healthz` | Liveness probe | `200 {"status": "ok"}` | - |
| `/readyz` | Readiness probe | `200 {"status": "ready"}` | `503 {"status": "not ready"}` |
| `/health` | Detailed status | `200` with full status | `503` if degraded |

**Example `/health` response:**

```json
{
  "status": "healthy",
  "service": "wapi-mcp-server",
  "uptime_seconds": 3600.5,
  "checks": {
    "api_connectivity": {
      "status": "ok",
      "error": null
    }
  }
}
```

## OpenTelemetry

### Platform Integration

When running as a DataRobot workload, the platform automatically injects:

```
OTEL_EXPORTER_OTLP_ENDPOINT=http://datarobot-otel-collector:4318
```

This points to the DataRobot HTTP OTEL collector (OTLP/HTTP protocol on port 4318).

### Enabling OTEL for Your Workloads

**Logs (automatic):** All workloads have log collection enabled by default. Logs from stdout/stderr are automatically captured - no configuration needed. Use `otel_logs(workload_id)` to view them.

**Traces and Metrics (requires instrumentation):** To enable tracing and metrics, your application must be instrumented with OpenTelemetry:

1. **Set service name:**
   ```json
   {"name": "OTEL_SERVICE_NAME", "value": "your-service"}
   ```

2. **Enable exporters** (check your container's documentation):
   ```json
   {"name": "OTEL_TRACES_EXPORTER", "value": "otlp"},
   {"name": "OTEL_METRICS_EXPORTER", "value": "otlp"},
   {"name": "OTEL_EXPORTER_OTLP_PROTOCOL", "value": "http/protobuf"}
   ```

3. **Collector endpoints:**
   - Traces: `http://datarobot-otel-collector:4318/v1/traces`
   - Metrics: `http://datarobot-otel-collector:4318/v1/metrics`

4. **View telemetry** using MCP tools:
   - `otel_logs(workload_id)` - Application logs (always available)
   - `otel_traces(workload_id)` - Request traces (requires instrumentation)
   - `otel_trace_get(workload_id, trace_id)` - Trace details
   - `otel_metrics(workload_id)` - Collected metrics (requires instrumentation)

### WAPI MCP Server Telemetry

This server exports the following when OTEL is configured:

**Traces:**
- `tool/{name}` - Spans for each tool call
- `HTTP {METHOD}` - Spans for API requests

**Metrics:**
- `mcp.tool.calls` - Tool call counter
- `mcp.tool.duration` - Tool call latency
- `mcp.api.requests` - API request counter
- `mcp.api.duration` - API request latency
