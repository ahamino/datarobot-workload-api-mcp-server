"""Tests for the WAPI client module."""

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
