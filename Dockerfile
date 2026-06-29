FROM python:3.12-slim

# Create non-root user
RUN groupadd --gid 1000 appuser && \
    useradd --uid 1000 --gid 1000 --create-home appuser

WORKDIR /app

# Copy and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the MCP server
COPY --chown=appuser:appuser wapi_mcp_server.py .
COPY --chown=appuser:appuser wapi_mcp/ ./wapi_mcp/

# The OpenAPI spec is fetched live from {DATAROBOT_API_ENDPOINT}/openapi.yaml at
# runtime by read_openapi_spec() — nothing to bundle into the image.

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
