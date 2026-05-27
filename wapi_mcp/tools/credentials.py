"""DataRobot credential tools.

Tools call ``server.get_client()`` so test patches of
``wapi_mcp_server.get_client`` take effect.
"""

from typing import Optional
import wapi_mcp_server as server

from wapi_mcp_server import get_credential_schemas  # noqa: E402

from wapi_mcp_server import mcp, traced_tool  # noqa: E402


@mcp.tool()
@traced_tool
async def credential_list(
    limit: int = 50,
    credential_type: Optional[str] = None,
) -> str:
    """List available DataRobot credentials that can be injected into workloads.

    Credentials are securely stored secrets (API keys, passwords, tokens) that can be
    injected as environment variables in workload containers. Use credential_keys()
    to see what keys are available for each credential type.

    Args:
        limit: Maximum number of credentials to return (default: 50)
        credential_type: Filter by type (s3, basic, gcp, api_token, bearer, oauth, etc.)

    Returns:
        List of credentials with ID, name, and type
    """
    client = await server.get_client()

    types = [credential_type] if credential_type else None
    result = await client.list_credentials(limit=limit, types=types)

    data = result.get("data", [])

    if not data:
        return "No credentials found. Create credentials in DataRobot's Credentials page first."

    # Fetch credential schemas from OpenAPI spec
    credential_schemas = await get_credential_schemas()

    output = f"Found {len(data)} credentials:\n\n"

    for cred in data:
        cred_id = cred.get("credentialId", "")
        name = cred.get("name", "")
        cred_type = cred.get("credentialType", "unknown")
        desc = cred.get("description", "")

        output += f"- {name}\n"
        output += f"  ID: {cred_id}\n"
        output += f"  Type: {cred_type}\n"
        if desc:
            output += f"  Description: {desc}\n"

        # Show available keys for this credential type
        keys = credential_schemas.get(cred_type, [])
        if keys:
            output += f"  Available keys: {', '.join(keys)}\n"
        output += "\n"

    output += """USAGE: To inject a credential as an environment variable in workload_create:

  credential_env_vars=[
      {"name": "AWS_ACCESS_KEY_ID", "credential_id": "<id>", "key": "awsAccessKeyId"},
      {"name": "AWS_SECRET_ACCESS_KEY", "credential_id": "<id>", "key": "awsSecretAccessKey"}
  ]"""

    return output


@mcp.tool()
@traced_tool
async def credential_get(credential_id: str) -> str:
    """Get details of a specific credential.

    Args:
        credential_id: The credential ID

    Returns:
        Credential details including available keys for injection
    """
    client = await server.get_client()
    cred = await client.get_credential(credential_id)

    # Fetch credential schemas from OpenAPI spec
    credential_schemas = await get_credential_schemas()

    cred_id = cred.get("credentialId", "")
    name = cred.get("name", "")
    cred_type = cred.get("credentialType", "unknown")
    desc = cred.get("description", "")
    created = cred.get("creationDate", "")

    output = f"Credential: {name}\n"
    output += f"ID: {cred_id}\n"
    output += f"Type: {cred_type}\n"
    if desc:
        output += f"Description: {desc}\n"
    output += f"Created: {created}\n\n"

    # Show available keys
    keys = credential_schemas.get(cred_type, [])
    if keys:
        output += "Available keys for injection:\n"
        for key in keys:
            output += f"  - {key}\n"

        output += "\nExample environment variable injection:\n"
        output += f'  {{"name": "MY_SECRET", "credential_id": "{cred_id}", "key": "{keys[0]}"}}'
    else:
        output += f"No known keys for credential type '{cred_type}'"

    return output


@mcp.tool()
@traced_tool
async def credential_keys() -> str:
    """Show available keys for each credential type.

    When injecting credentials as environment variables, you need to specify
    which 'key' (field) from the credential to use.

    Returns:
        Mapping of credential types to their available keys
    """
    # Fetch credential schemas from OpenAPI spec
    credential_schemas = await get_credential_schemas()

    output = "Credential Types and Available Keys:\n\n"

    for cred_type, keys in credential_schemas.items():
        output += f"{cred_type}:\n"
        for key in keys:
            output += f"  - {key}\n"
        output += "\n"

    output += """USAGE in workload_create:

credential_env_vars=[
    # S3 credentials example
    {"name": "AWS_ACCESS_KEY_ID", "credential_id": "<s3-cred-id>", "key": "awsAccessKeyId"},
    {"name": "AWS_SECRET_ACCESS_KEY", "credential_id": "<s3-cred-id>", "key": "awsSecretAccessKey"},

    # Basic auth example
    {"name": "DB_USER", "credential_id": "<basic-cred-id>", "key": "user"},
    {"name": "DB_PASSWORD", "credential_id": "<basic-cred-id>", "key": "password"},

    # API token example
    {"name": "API_KEY", "credential_id": "<api-token-cred-id>", "key": "apiToken"},
]"""

    return output


__all__ = [
    "credential_list",
    "credential_get",
    "credential_keys",
]
