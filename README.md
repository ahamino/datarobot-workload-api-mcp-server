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

Create a workload with an inline artifact. The artifact is created with `status=draft` by default, allowing iteration.

**First, create a DataRobot credential to store your API token:**

```bash
# Create an api_token credential with your current token
CREDENTIAL_ID=$(curl -s -X POST "${DATAROBOT_API_ENDPOINT}/credentials/" \
  -H "Authorization: Bearer ${DATAROBOT_API_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
    "credentialType": "api_token",
    "name": "WAPI MCP Server Token",
    "apiToken": "'"${DATAROBOT_API_TOKEN}"'",
    "description": "API token for WAPI MCP Server workload"
  }' | jq -r '.credentialId')

# Verify it was created
echo "Created credential ID: ${CREDENTIAL_ID}"
```

This creates an `api_token` credential that securely stores your token for injection into the workload.

**Then create the workload using credential injection:**

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
          "containers": [{
            "name": "main",
            "imageUri": "ghcr.io/ahamino/datarobot-workload-api-mcp-server:latest",
            "port": 8000,
            "primary": true,
            "resourceRequest": {"cpu": 2, "memory": "4GB"},
            "environmentVars": [
              {"name": "DATAROBOT_API_ENDPOINT", "value": "'"${DATAROBOT_API_ENDPOINT}"'"},
              {
                "source": "dr-credential",
                "name": "DATAROBOT_API_TOKEN",
                "drCredentialId": "'"${CREDENTIAL_ID}"'",
                "key": "apiToken"
              }
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
        "replicaCount": 1
      }]
    }
  }'
```

**Benefits of credential injection:**
- Secrets are securely stored and never visible in workload specs
- Credential rotation is centralized (update once, affects all workloads)
- Audit trail for credential usage

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
        "containers": [{
          "name": "main",
          "imageUri": "ghcr.io/ahamino/datarobot-workload-api-mcp-server:v2",
          "port": 8000,
          "primary": true,
          "resourceRequest": {"cpu": 2, "memory": "4GB"},
          "environmentVars": [
            {"name": "DATAROBOT_API_ENDPOINT", "value": "'"${DATAROBOT_API_ENDPOINT}"'"},
            {
              "source": "dr-credential",
              "name": "DATAROBOT_API_TOKEN",
              "drCredentialId": "'"${CREDENTIAL_ID}"'",
              "key": "apiToken"
            }
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

### Example: Create a Workload with Credentials

> "Create a workload called 'data-processor' using image `myregistry/processor:v1` on port 8000. Inject my S3 credential with ID 'cred-abc123' as AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY environment variables."

The assistant will use `workload_create` with `credential_env_vars` to securely inject the credentials.

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

### Example: Work with Credentials

> "List all available credentials"
> "Show me the field names for S3 credentials"
> "Create a workload that injects my AWS credentials as environment variables"

### Example: Debug Workload Issues

> "My workload is in errored state. Show me the status details and logs"
> "Check the proton status details for workload abc123 to see why containers are failing"
> "Show me the events for workload xyz to understand what went wrong"

**Debugging workflow:**
1. **Check workload status**: `workload_status(workload_id)` - Shows conditions, log tail, and error messages
2. **List protons**: `proton_list(workload_id)` - Find which proton is having issues
3. **Check proton details**: `proton_status_details(workload_id, proton_id)` - See per-replica status, container states, restart counts
4. **View application logs**: `otel_logs(workload_id)` - See full application logs from stdout/stderr
5. **Check events**: `workload_events(workload_id)` - See workload lifecycle events

**Common issues detected:**
- **CrashLoopBackOff** - Container keeps crashing, check logs for error
- **ImagePullBackOff** - Can't pull container image, check image URI and credentials
- **OOMKilled** - Out of memory, increase memory allocation
- **Pending** - Can't schedule, check resource availability
- **Failed probes** - Readiness/liveness probes failing, check probe configuration

### Available MCP Tools for Workload Management

| Tool | Use Case |
|------|----------|
| `workload_create` | Create new workloads with inline or existing artifacts |
| `workload_list` | List workloads with filters (status, importance) |
| `workload_get` | Get detailed workload info including endpoint URL |
| `workload_start` / `workload_stop` | Control workload lifecycle |
| `workload_delete` | Remove workloads |
| `workload_settings_get` / `workload_settings_update` | View/change replicas, resources, autoscaling |
| `workload_stats` | Get performance statistics (requests, errors, latency) |
| `workload_history` | View artifact deployment history |
| `artifact_update` | Update container spec (image, env vars, probes) |
| `artifact_build_trigger` / `artifact_build_logs` | Trigger builds and view build logs |
| `bundle_list` | See available CPU/GPU resource bundles |
| `credential_list` / `credential_get` | Work with DataRobot credentials |

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

## Troubleshooting & Debugging

When workloads fail to start or enter an errored state, use these tools to diagnose issues:

### Debugging Tools Summary

| Tool | What It Shows | When to Use |
|------|---------------|-------------|
| `workload_status` | Overall status, conditions, log tail | First step: get high-level view |
| `proton_list` | All deployment instances (protons) | Find which proton is having issues |
| `proton_get` | Proton details with status | Get overview of a specific proton |
| `proton_status_details` | Per-replica status, container states, restart counts | Deep dive into pod/container issues |
| `workload_events` | Lifecycle events (created, started, errors) | Understand event timeline |
| `otel_logs` | Full application logs (stdout/stderr) | See what your application logged |

### Example Debugging Session

**Scenario**: Workload stuck in "initializing" or shows "errored" status

```python
# Step 1: Check overall status
workload_status("wkld-abc123")
# Shows: status, conditions, recent log tail
# Look for: error messages, crash reasons, probe failures

# Step 2: List protons to find the problematic one
proton_list("wkld-abc123")
# Shows: all deployment instances and their status

# Step 3: Get detailed proton status
proton_status_details("wkld-abc123", "proton-xyz")
# Shows:
# - Per-replica phase (pending, running, failed)
# - Container states (waiting, running, terminated)
# - Restart counts (indicates crash loops)
# - Ready conditions (PodScheduled, ContainersReady, Ready)
# - Node addresses

# Step 4: View application logs
otel_logs("wkld-abc123", limit=100)
# Shows: stdout/stderr from your application

# Step 5: Check event history
workload_events("wkld-abc123")
# Shows: workload lifecycle events
```

### Common Error Patterns

**CrashLoopBackOff**
```
Container State: waiting
Reason: CrashLoopBackOff
Restart Count: 5+
```
→ Your app is crashing. Check `otel_logs()` for errors.

**ImagePullBackOff**
```
Container State: waiting
Reason: ImagePullBackOff
Message: Failed to pull image "myregistry/myapp:v1"
```
→ Can't pull image. Check image URI, registry credentials, or image existence.

**OOMKilled**
```
Container State: terminated
Reason: OOMKilled
Exit Code: 137
```
→ Out of memory. Use `workload_settings_update()` to increase memory.

**Probe Failures**
```
Condition: ContainersReady = False
Reason: ReadinessProbe failed
```
→ Readiness probe failing. Check probe path/port configuration or app health endpoint.

**Pending Pod**
```
Replica Phase: pending
Condition: PodScheduled = False
```
→ Can't schedule pod. Check resource availability or constraints.

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

Protons are the actual deployment instances of your workload. Use these tools for debugging container/pod issues.

| Tool | Description |
|------|-------------|
| `proton_list` | List all protons for a workload |
| `proton_get` | Get proton details including status and runtime config |
| `proton_status_details` | **[DEBUG]** Get per-replica status with container states, restart counts, and conditions |

**Debugging tip**: When a workload fails, use `proton_status_details()` to see exactly why containers are failing (crash loops, image pull errors, OOM kills, probe failures, etc.).

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

### Credentials

Securely inject DataRobot credentials as environment variables into your workloads.

| Tool | Description |
|------|-------------|
| `credential_list` | List available credentials with their types and field names |
| `credential_get` | Get details of a specific credential |
| `credential_keys` | Show available field names for each credential type |

**Credential Types Supported:**
- `s3` - AWS S3 credentials (awsAccessKeyId, awsSecretAccessKey, awsSessionToken)
- `basic` - Basic auth (user, password)
- `api_token` - API tokens (apiToken)
- `bearer` - Bearer tokens (token)
- `oauth` - OAuth credentials (token, refreshToken)
- `gcp` - Google Cloud Platform (gcpKey)
- `azure_service_principal` - Azure SP (azureTenantId, clientId, clientSecret)
- `azure` - Azure connection strings (azureConnectionString)
- `databricks_access_token_account` - Databricks (databricksAccessToken)
- `snowflake_key_pair_user_account` - Snowflake (privateKeyStr, passphrase, user)
- And more...

**Example: Inject S3 credentials into a workload**

```python
# Using MCP tools via AI assistant
"Create a workload with S3 credentials injected as environment variables:
- credential_id: <your-s3-cred-id>
- AWS_ACCESS_KEY_ID from awsAccessKeyId
- AWS_SECRET_ACCESS_KEY from awsSecretAccessKey"

# The assistant will use workload_create with:
credential_env_vars=[
    {"name": "AWS_ACCESS_KEY_ID", "credential_id": "<id>", "key": "awsAccessKeyId"},
    {"name": "AWS_SECRET_ACCESS_KEY", "credential_id": "<id>", "key": "awsSecretAccessKey"}
]
```

**Note:** Credential field names are dynamically fetched from the DataRobot OpenAPI specification, so all current and future credential types are automatically supported.

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
