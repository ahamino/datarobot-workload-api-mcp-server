"""Tests for credential-related functionality."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import yaml


class TestCredentialSchemaFetching:
    """Tests for dynamic credential schema fetching."""

    @pytest.mark.asyncio
    async def test_get_credential_schemas_caches_result(self):
        """Test that credential schemas are cached after first fetch."""
        import wapi_mcp_server as mcp

        # Reset cache
        mcp._credential_schemas_cache = None

        mock_client = MagicMock()
        mock_client.base_url = "https://test.datarobot.com/api/v2"

        openapi_spec = """
components:
  schemas:
    S3Credential:
      properties:
        credentialType:
          enum: ["s3"]
        awsAccessKeyId:
          type: string
        awsSecretAccessKey:
          type: string
        awsSessionToken:
          type: string
"""

        with patch('wapi_mcp_server.get_client', return_value=mock_client):
            with patch('aiohttp.ClientSession') as mock_session_class:
                mock_session = AsyncMock()
                mock_resp = AsyncMock()
                mock_resp.status = 200
                mock_resp.text = AsyncMock(return_value=openapi_spec)
                mock_session.__aenter__ = AsyncMock(return_value=mock_session)
                mock_session.__aexit__ = AsyncMock()
                mock_session.get = MagicMock(return_value=mock_resp)
                mock_session_class.return_value = mock_session

                # First call should fetch from API
                result1 = await mcp.get_credential_schemas()
                assert result1 is not None

                # Second call should use cache (no new API call)
                result2 = await mcp.get_credential_schemas()
                assert result2 is result1  # Same object reference

    @pytest.mark.asyncio
    async def test_get_credential_schemas_fallback_on_error(self):
        """Test that fallback credential keys are used when OpenAPI fetch fails."""
        import wapi_mcp_server as mcp

        # Reset cache
        mcp._credential_schemas_cache = None

        mock_client = MagicMock()
        mock_client.base_url = "https://test.datarobot.com/api/v2"

        with patch('wapi_mcp_server.get_client', return_value=mock_client):
            with patch('aiohttp.ClientSession') as mock_session_class:
                mock_session = AsyncMock()
                mock_resp = AsyncMock()
                mock_resp.status = 500  # Simulate error
                mock_session.__aenter__ = AsyncMock(return_value=mock_session)
                mock_session.__aexit__ = AsyncMock()
                mock_session.get = MagicMock(return_value=mock_resp)
                mock_session_class.return_value = mock_session

                result = await mcp.get_credential_schemas()
                # Should return fallback keys
                assert result == mcp.FALLBACK_CREDENTIAL_KEYS

    @pytest.mark.asyncio
    async def test_get_credential_schemas_parses_response_schemas(self):
        """Test parsing of credential schemas with credentialType property."""
        import wapi_mcp_server as mcp

        # Reset cache
        mcp._credential_schemas_cache = None

        mock_client = MagicMock()
        mock_client.base_url = "https://test.datarobot.com/api/v2"

        openapi_spec = """
components:
  schemas:
    S3CredentialResponse:
      properties:
        credentialId:
          type: string
        credentialType:
          enum: ["s3"]
        name:
          type: string
        awsAccessKeyId:
          type: string
        awsSecretAccessKey:
          type: string
        awsSessionToken:
          type: string
    BasicAuthResponse:
      properties:
        credentialId:
          type: string
        credentialType:
          enum: ["basic"]
        name:
          type: string
        user:
          type: string
        password:
          type: string
"""

        with patch('wapi_mcp_server.get_client', return_value=mock_client):
            with patch('aiohttp.ClientSession') as mock_session_class:
                mock_session = AsyncMock()
                mock_resp = AsyncMock()
                mock_resp.status = 200
                mock_resp.text = AsyncMock(return_value=openapi_spec)
                mock_session.__aenter__ = AsyncMock(return_value=mock_session)
                mock_session.__aexit__ = AsyncMock()
                mock_session.get = MagicMock(return_value=mock_resp)
                mock_session_class.return_value = mock_session

                result = await mcp.get_credential_schemas()

                # Should extract field names excluding metadata
                assert "s3" in result
                assert "awsAccessKeyId" in result["s3"]
                assert "awsSecretAccessKey" in result["s3"]
                assert "awsSessionToken" in result["s3"]
                assert "credentialId" not in result["s3"]
                assert "name" not in result["s3"]

                assert "basic" in result
                assert "user" in result["basic"]
                assert "password" in result["basic"]

    @pytest.mark.asyncio
    async def test_get_credential_schemas_parses_input_schemas(self):
        """Test parsing of input credential schemas (ending with Credential/Credentials)."""
        import wapi_mcp_server as mcp

        # Reset cache
        mcp._credential_schemas_cache = None

        mock_client = MagicMock()
        mock_client.base_url = "https://test.datarobot.com/api/v2"

        openapi_spec = """
components:
  schemas:
    S3Credentials:
      properties:
        awsAccessKeyId:
          type: string
        awsSecretAccessKey:
          type: string
    GCPCredential:
      properties:
        gcpKey:
          type: string
"""

        with patch('wapi_mcp_server.get_client', return_value=mock_client):
            with patch('aiohttp.ClientSession') as mock_session_class:
                mock_session = AsyncMock()
                mock_resp = AsyncMock()
                mock_resp.status = 200
                mock_resp.text = AsyncMock(return_value=openapi_spec)
                mock_session.__aenter__ = AsyncMock(return_value=mock_session)
                mock_session.__aexit__ = AsyncMock()
                mock_session.get = MagicMock(return_value=mock_resp)
                mock_session_class.return_value = mock_session

                result = await mcp.get_credential_schemas()

                # Should infer credential type from schema name
                assert "s3" in result or "s_3" in result  # snake_case conversion
                assert "gcp" in result or "g_c_p" in result


class TestCredentialListTool:
    """Tests for credential_list tool."""

    @pytest.mark.asyncio
    async def test_credential_list_returns_string(self):
        """Test that credential_list returns a formatted string."""
        import wapi_mcp_server as mcp

        mock_client = AsyncMock()
        mock_client.list_credentials = AsyncMock(return_value={
            "data": [
                {
                    "credentialId": "cred123",
                    "name": "Test S3 Credential",
                    "credentialType": "s3",
                    "description": "Test description"
                }
            ]
        })

        mcp._credential_schemas_cache = {
            "s3": ["awsAccessKeyId", "awsSecretAccessKey"]
        }

        with patch('wapi_mcp_server.get_client', return_value=mock_client):
            result = await mcp.credential_list(limit=10)

        assert isinstance(result, str)
        assert "Test S3 Credential" in result
        assert "cred123" in result
        assert "s3" in result
        assert "awsAccessKeyId" in result

    @pytest.mark.asyncio
    async def test_credential_list_handles_no_credentials(self):
        """Test credential_list when no credentials exist."""
        import wapi_mcp_server as mcp

        mock_client = AsyncMock()
        mock_client.list_credentials = AsyncMock(return_value={"data": []})

        with patch('wapi_mcp_server.get_client', return_value=mock_client):
            result = await mcp.credential_list()

        assert isinstance(result, str)
        assert "No credentials found" in result

    @pytest.mark.asyncio
    async def test_credential_list_filters_by_type(self):
        """Test credential_list with type filter."""
        import wapi_mcp_server as mcp

        mock_client = AsyncMock()
        mock_client.list_credentials = AsyncMock(return_value={"data": []})

        with patch('wapi_mcp_server.get_client', return_value=mock_client):
            await mcp.credential_list(credential_type="s3")

        mock_client.list_credentials.assert_called_once()
        call_args = mock_client.list_credentials.call_args
        assert call_args.kwargs["types"] == ["s3"]


class TestCredentialGetTool:
    """Tests for credential_get tool."""

    @pytest.mark.asyncio
    async def test_credential_get_returns_details(self):
        """Test that credential_get returns credential details."""
        import wapi_mcp_server as mcp

        mock_client = AsyncMock()
        mock_client.get_credential = AsyncMock(return_value={
            "credentialId": "cred123",
            "name": "My S3 Creds",
            "credentialType": "s3",
            "description": "Production S3 credentials",
            "creationDate": "2024-01-15T10:00:00Z"
        })

        mcp._credential_schemas_cache = {
            "s3": ["awsAccessKeyId", "awsSecretAccessKey", "awsSessionToken"]
        }

        with patch('wapi_mcp_server.get_client', return_value=mock_client):
            result = await mcp.credential_get("cred123")

        assert isinstance(result, str)
        assert "My S3 Creds" in result
        assert "cred123" in result
        assert "s3" in result
        assert "awsAccessKeyId" in result
        assert "awsSecretAccessKey" in result

    @pytest.mark.asyncio
    async def test_credential_get_handles_unknown_type(self):
        """Test credential_get with unknown credential type."""
        import wapi_mcp_server as mcp

        mock_client = AsyncMock()
        mock_client.get_credential = AsyncMock(return_value={
            "credentialId": "cred456",
            "name": "Unknown Cred",
            "credentialType": "unknown_type",
            "description": "",
            "creationDate": "2024-01-15T10:00:00Z"
        })

        mcp._credential_schemas_cache = {}

        with patch('wapi_mcp_server.get_client', return_value=mock_client):
            result = await mcp.credential_get("cred456")

        assert isinstance(result, str)
        assert "Unknown Cred" in result
        assert "unknown_type" in result


class TestCredentialKeysTool:
    """Tests for credential_keys tool."""

    @pytest.mark.asyncio
    async def test_credential_keys_returns_all_types(self):
        """Test that credential_keys returns all credential types."""
        import wapi_mcp_server as mcp

        mcp._credential_schemas_cache = {
            "s3": ["awsAccessKeyId", "awsSecretAccessKey"],
            "basic": ["user", "password"],
            "api_token": ["apiToken"]
        }

        result = await mcp.credential_keys()

        assert isinstance(result, str)
        assert "s3" in result
        assert "awsAccessKeyId" in result
        assert "basic" in result
        assert "user" in result
        assert "password" in result
        assert "api_token" in result
        assert "apiToken" in result

    @pytest.mark.asyncio
    async def test_credential_keys_includes_usage_example(self):
        """Test that credential_keys includes usage examples."""
        import wapi_mcp_server as mcp

        mcp._credential_schemas_cache = {"s3": ["awsAccessKeyId"]}

        result = await mcp.credential_keys()

        assert "USAGE" in result or "credential_env_vars" in result


class TestCredentialEnvVarsValidation:
    """Tests for credential_env_vars parameter validation."""

    def test_credential_env_var_structure(self):
        """Test that credential env var structure is documented properly."""
        import wapi_mcp_server as mcp

        # Verify the workload_create function has the credential_env_vars parameter
        import inspect
        sig = inspect.signature(mcp.workload_create)
        assert 'credential_env_vars' in sig.parameters

        # Verify documentation mentions credential_env_vars
        assert 'credential_env_vars' in mcp.workload_create.__doc__.lower()
