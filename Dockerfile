FROM python:3.12-slim

# uv for dependency management (pinned, copied from the official image)
COPY --from=ghcr.io/astral-sh/uv:0.10 /uv /uvx /bin/

# Create non-root user
RUN groupadd --gid 1000 appuser && \
    useradd --uid 1000 --gid 1000 --create-home appuser

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH="/app/.venv/bin:$PATH"

# Install runtime dependencies from the lockfile (no dev tools). The server runs
# via `python wapi_mcp_server.py` with the source on disk, so the project itself
# isn't installed — keeping this layer cached across source-only changes.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Copy the MCP server. The OpenAPI spec is fetched live from
# {DATAROBOT_API_ENDPOINT}/openapi.yaml at runtime — nothing to bundle.
COPY wapi_mcp_server.py ./
COPY wapi_mcp/ ./wapi_mcp/

RUN chown -R appuser:appuser /app

# Switch to non-root user
USER appuser

# Expose port for HTTP transport
EXPOSE 8000

# Liveness check for HTTP mode (the default CMD). Uses stdlib so no extra deps.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/healthz', timeout=4).status==200 else 1)"]

# Default entrypoint - can be overridden in workload config
ENTRYPOINT ["python", "wapi_mcp_server.py"]
CMD ["--mode", "http", "--host", "0.0.0.0", "--port", "8000"]
