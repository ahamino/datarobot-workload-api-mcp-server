"""Tests for the WAPI client module."""

from unittest.mock import AsyncMock

import pytest
from wapi_mcp.client import WapiClient


class TestWapiClientInit:
    """Tests for WapiClient initialization."""

    def test_init_with_valid_params(self):
        """Test client initialization with valid parameters."""
        client = WapiClient(
            base_url="https://example.com/api/v2",
            token="test-token"
        )
        assert client.base_url == "https://example.com/api/v2"
        assert client.token == "test-token"

    def test_init_strips_trailing_slash(self):
        """Test that trailing slashes are stripped from base_url."""
        client = WapiClient(
            base_url="https://example.com/api/v2/",
            token="test-token"
        )
        assert client.base_url == "https://example.com/api/v2"

    def test_init_with_empty_token_raises(self):
        """Test client raises error with empty token."""
        from wapi_mcp.exceptions import WapiConfigError
        with pytest.raises(WapiConfigError):
            WapiClient(
                base_url="https://example.com/api/v2",
                token=""
            )


class TestWapiClientURLBuilding:
    """Tests for URL building in WapiClient."""

    def test_workload_endpoint_url(self):
        """Test workload endpoint URL construction."""
        client = WapiClient(
            base_url="https://example.com/api/v2",
            token="test-token"
        )
        # The client builds URLs internally, we test the base_url is correct
        assert "example.com" in client.base_url
        assert client.base_url.endswith("/api/v2")


class TestWapiClientHeaders:
    """Tests for header construction."""

    def test_auth_header_format(self):
        """Test that the client stores token for auth header."""
        client = WapiClient(
            base_url="https://example.com/api/v2",
            token="my-secret-token"
        )
        # Token should be stored for Bearer auth
        assert client.token == "my-secret-token"


class TestWapiClientOtelLogs:
    """Tests for get_otel_logs query-param mapping."""

    @pytest.mark.asyncio
    async def test_search_keys_values_mapped_to_query_params(self):
        """search_keys/search_values become searchKeys/searchValues query params."""
        client = WapiClient(base_url="https://example.com/api/v2", token="t")
        client.request = AsyncMock(return_value={"data": []})

        await client.get_otel_logs(
            "wkld123",
            level="error",
            search_keys=["proton_id"],
            search_values=["proton-9"],
        )

        args, kwargs = client.request.call_args
        assert args[0] == "GET"
        assert args[1] == "/api/v2/otel/workload/wkld123/logs/"
        params = kwargs["params"]
        assert params["searchKeys"] == ["proton_id"]
        assert params["searchValues"] == ["proton-9"]
        assert params["level"] == "error"

    @pytest.mark.asyncio
    async def test_no_search_params_when_unset(self):
        """Omitting search_keys/values leaves them out of the query params."""
        client = WapiClient(base_url="https://example.com/api/v2", token="t")
        client.request = AsyncMock(return_value={"data": []})

        await client.get_otel_logs("wkld123")

        params = client.request.call_args.kwargs["params"]
        assert "searchKeys" not in params
        assert "searchValues" not in params
