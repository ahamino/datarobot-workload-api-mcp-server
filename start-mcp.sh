#!/bin/zsh
source ~/.zshrc
SCRIPT_DIR="${0:A:h}"
exec "${SCRIPT_DIR}/.venv/bin/python" \
  "${SCRIPT_DIR}/claude_desktop_proxy.py" \
  --url "${DATAROBOT_API_ENDPOINT}/endpoints/workloads/${WAPI_MCP_SERVER_WORKLOAD_ID}/mcp" \
  --token "${DATAROBOT_API_TOKEN}"
