"""Pulumi program that stands up the WAPI MCP Server as a DataRobot workload."""

import pulumi
import pulumi_datarobot as datarobot

# Only the container-side API token stays as a Pulumi secret — embedding it in
# source would land it in git and Pulumi state in plaintext. The provider's own
# auth (datarobot:endpoint, datarobot:apikey) still comes from stack config —
# the pulumi-datarobot plugin reads it directly.
datarobot_token = pulumi.Config().require_secret("datarobotToken")
datarobot_endpoint = pulumi.Config("datarobot").require("endpoint")

credential = datarobot.ApiTokenCredential(
    "wapi-mcp-server-token",
    name="wapi-mcp-server-token",
    description="API token used by the WAPI MCP Server workload",
    api_token=datarobot_token,
)

artifact = datarobot.Artifact(
    "wapi-mcp-server-artifact",
    name="wapi-mcp-server-artifact",
    description="WAPI MCP Server container artifact",
    type="service",
    spec={
        "container_groups": [
            {
                "containers": [
                    {
                        "name": "main",
                        "image_uri": "ghcr.io/ahamino/datarobot-workload-api-mcp-server:0e90773",
                        "port": 8000,
                        "primary": True,
                        "environment_vars": [
                            {"name": "DATAROBOT_API_ENDPOINT", "value": datarobot_endpoint},
                            {"name": "DATAROBOT_API_TOKEN", "value": datarobot_token}
                        ],
                    },
                ],
            },
        ],
    },
)

workload = datarobot.Workload(
    "wapi-mcp-server",
    name="wapi-mcp-server",
    description="WAPI MCP Server",
    importance="low",
    artifact_id=artifact.artifact_id,
    runtime={
        "container_groups": [
            {
                "replica_count": 1,
                "containers": [
                    {
                        "name": "main",
                        "resource_allocation": {
                            "cpu": 2.0,
                            "memory": 5096 * 1024 * 1024,
                        },
                    },
                ],
            },
        ],
    },
    opts=pulumi.ResourceOptions(replace_on_changes=["artifact_id"]),
)

pulumi.export("credentialId", credential.id)
pulumi.export("artifactId", artifact.artifact_id)
pulumi.export("workloadId", workload.id)
pulumi.export(
    "mcpUrl",
    pulumi.Output.concat(workload.endpoint, "mcp"),
)
