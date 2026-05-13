#!/bin/zsh
source ~/.zshrc
exec /Users/abdo.mahmoud/dev/scratchpad/workload-api-mcp/.venv/bin/python \
  /Users/abdo.mahmoud/dev/scratchpad/workload-api-mcp/claude_desktop_proxy.py \
  --url "${DATAROBOT_API_ENDPOINT}/endpoints/workloads/${WAPI_MCP_SERVER_WORKLOAD_ID}/mcp" \
  --token "${DATAROBOT_API_TOKEN}"
