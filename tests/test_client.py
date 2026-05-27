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


class _FakeResp:
    """Minimal aiohttp response/context-manager double for client.request tests."""
    def __init__(self, status=200, payload=None):
        self.status = status
        self.content_length = 1
        self._payload = payload if payload is not None else {"data": []}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def json(self):
        return self._payload

    async def text(self):
        return "error body"


class _FakeSession:
    def __init__(self, resp):
        self._resp = resp

    def request(self, **kwargs):
        return self._resp


def _in_memory_tracer(monkeypatch):
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
    import wapi_mcp.telemetry as telemetry
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(telemetry, "_tracer", provider.get_tracer("test"))
    return exporter


class TestHttpClientInstrumentation:
    """Outbound calls emit OTel HTTP CLIENT spans (semconv attributes)."""

    @pytest.mark.asyncio
    async def test_request_emits_client_span(self, monkeypatch):
        from opentelemetry.trace import SpanKind
        exporter = _in_memory_tracer(monkeypatch)

        client = WapiClient(base_url="https://example.com/api/v2", token="t")
        client._session = _FakeSession(_FakeResp(200, {"data": []}))
        await client.request("GET", "/api/v2/workloads/6a1594ddcb9c82214b5caf75/")

        span = next(s for s in exporter.get_finished_spans()
                    if dict(s.attributes).get("http.request.method") == "GET")
        attrs = dict(span.attributes)
        assert span.kind == SpanKind.CLIENT
        assert attrs["http.route"] == "/api/v2/workloads/{id}/"   # id normalized
        assert attrs["http.response.status_code"] == 200
        assert attrs["server.address"] == "example.com"

    @pytest.mark.asyncio
    async def test_request_error_span(self, monkeypatch):
        from wapi_mcp.exceptions import WapiAPIError
        exporter = _in_memory_tracer(monkeypatch)

        client = WapiClient(base_url="https://example.com/api/v2", token="t")
        client._session = _FakeSession(_FakeResp(500))
        with pytest.raises(WapiAPIError):
            await client.request("GET", "/api/v2/workloads/")

        span = next(s for s in exporter.get_finished_spans()
                    if dict(s.attributes).get("http.request.method") == "GET")
        attrs = dict(span.attributes)
        assert attrs["http.response.status_code"] == 500
        assert attrs["error.type"] == "HTTP 500"
