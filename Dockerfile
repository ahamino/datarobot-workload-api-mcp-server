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

# Copy OpenAPI spec and point the server at it explicitly.
# read_openapi_spec() reads OPENAPI_SPEC_PATH (defaults to /app/openapi.yaml).
COPY --chown=appuser:appuser openapi.yaml .
ENV OPENAPI_SPEC_PATH=/app/openapi.yaml

# Switch to non-root user
USER appuser

# Expose port for HTTP transport
EXPOSE 8000

# Default entrypoint - can be overridden in workload config
ENTRYPOINT ["python", "wapi_mcp_server.py"]
CMD ["--mode", "http", "--host", "0.0.0.0", "--port", "8000"]
