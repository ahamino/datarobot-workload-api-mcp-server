#!/usr/bin/env python3
"""
Claude Desktop Proxy - Translates MCP session headers for DataRobot gateway compatibility.

Problem:
    Claude Desktop and other MCP clients send session IDs via the standard
    `mcp-session-id` header. However, the DataRobot gateway strips non-standard
    headers, preventing session continuity for remote MCP workloads.

Solution:
    This proxy translates headers between MCP clients and DataRobot workloads:
    - Outgoing: Converts `mcp-session-id` to `x-datarobot-mcp-session-id`
    - Incoming: Reads session ID from `x-datarobot-mcp-session-id` response header

    The `x-datarobot-*` prefix is preserved by the gateway, enabling proper
    session tracking for stateful MCP interactions.

Usage:
    python claude_desktop_proxy.py --url <workload-mcp-url> --token <api-token>

The proxy runs in stdio mode, so configure Claude Desktop to use it as the command.
"""

import argparse
import asyncio
import json
import sys
import aiohttp


# Tool calls can take 10-30 minutes (workload creation, waiting for running status)
DEFAULT_TIMEOUT_SECONDS = 1800  # 30 minutes


async def proxy_request(
    session: aiohttp.ClientSession,
    url: str,
    token: str,
    request: dict,
    current_session_id: str | None,
    is_session_locked: bool = False,
) -> tuple[dict | None, str | None, bool]:
    """Send request to remote server and return response with session ID.

    Returns (response, session_id, is_session_locked).
    Response is None for notifications (messages without 'id').
    Session ID is only updated from 'initialize' response, then locked.
    """

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "Authorization": f"Bearer {token}",
    }

    # Add session ID header if we have one (using x-datarobot prefix for gateway)
    if current_session_id:
        headers["x-datarobot-mcp-session-id"] = current_session_id

    # Check if this is a notification (no id = no response expected)
    is_notification = "id" not in request
    request_id = request.get("id")

    # Log requests to stderr for debugging
    method = request.get("method", "")
    tool_name = None
    tool_args = None

    if method == "tools/call":
        params = request.get("params", {})
        tool_name = params.get("name", "unknown")
        tool_args = params.get("arguments", {})

        # Log tool call with key arguments (redact tokens/secrets)
        safe_args = {k: v for k, v in tool_args.items() if "token" not in k.lower() and "secret" not in k.lower()}
        # Truncate long values for logging
        for k, v in safe_args.items():
            if isinstance(v, str) and len(v) > 100:
                safe_args[k] = v[:100] + "..."
            elif isinstance(v, list) and len(v) > 3:
                safe_args[k] = f"[{len(v)} items]"

        sys.stderr.write(f"[proxy] 🔧 Tool: {tool_name}\n")
        if safe_args:
            sys.stderr.write(f"[proxy]    Args: {safe_args}\n")
        sys.stderr.flush()
    else:
        # Debug: log session ID being sent for non-tool methods
        sys.stderr.write(f"[proxy] {method} (session: {current_session_id[:16] + '...' if current_session_id else 'none'})\n")
        sys.stderr.flush()

    try:
        async with session.post(url, json=request, headers=headers) as resp:
            # Only capture session ID from initialize response, then lock it
            # This prevents subsequent responses from overwriting our session
            # (which happens when gateway strips our session header on inbound)
            new_session_id = current_session_id
            new_locked = is_session_locked

            if method == "initialize" and not is_session_locked:
                # Get session ID from initialize response
                new_session_id = (
                    resp.headers.get("x-datarobot-mcp-session-id") or
                    resp.headers.get("mcp-session-id") or
                    resp.headers.get("Mcp-Session-Id")
                )
                if new_session_id:
                    new_locked = True  # Lock after initialize
                    sys.stderr.write(f"[proxy] Response headers: {dict(resp.headers)}\n")
                    sys.stderr.write(f"[proxy] Session ID captured and locked: {new_session_id}\n")
                    sys.stderr.flush()

            # Notifications don't expect a response
            if is_notification:
                return None, new_session_id, new_locked

            # Check content type - FastMCP can return JSON or SSE
            content_type = resp.headers.get("Content-Type", "")

            # Handle SSE (Server-Sent Events) responses
            if "text/event-stream" in content_type:
                response = None
                # Read entire response content to avoid generator issues
                content = await resp.content.read()
                for line in content.decode().split("\n"):
                    line = line.strip()
                    if line.startswith("data:"):
                        data = line[5:].strip()
                        if data:
                            try:
                                parsed = json.loads(data)
                                # Return first complete JSON-RPC response
                                if "jsonrpc" in parsed:
                                    response = parsed
                                    break
                            except json.JSONDecodeError:
                                pass

                # If we got here without a response, return error
                if response is None:
                    return {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "error": {"code": -32000, "message": "No valid response in SSE stream"}
                    }, new_session_id, new_locked
                # Log tool completion
                if tool_name:
                    if response and "error" in response:
                        sys.stderr.write(f"[proxy] ❌ Tool {tool_name} failed: {response.get('error', {}).get('message', 'unknown')[:100]}\n")
                    else:
                        sys.stderr.write(f"[proxy] ✓ Tool {tool_name} completed\n")
                    sys.stderr.flush()

                return response, new_session_id, new_locked

            # Handle JSON responses
            try:
                response = await resp.json()
            except Exception:
                text = await resp.text()
                # Return proper JSON-RPC error for non-JSON responses
                if tool_name:
                    sys.stderr.write(f"[proxy] ❌ Tool {tool_name} failed: non-JSON response\n")
                    sys.stderr.flush()
                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {"code": -32000, "message": f"Server error: {text[:500]}"}
                }, new_session_id, new_locked

            # Check if response is a valid JSON-RPC response (has jsonrpc field)
            if "jsonrpc" not in response:
                # Server returned non-JSON-RPC response (like {"detail": "..."})
                error_msg = response.get("detail") or response.get("error") or str(response)
                if tool_name:
                    sys.stderr.write(f"[proxy] ❌ Tool {tool_name} failed: {str(error_msg)[:100]}\n")
                    sys.stderr.flush()
                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {"code": -32000, "message": f"Server error: {error_msg}"}
                }, new_session_id, new_locked

            # Log tool completion for JSON responses
            if tool_name:
                if "error" in response:
                    sys.stderr.write(f"[proxy] ❌ Tool {tool_name} failed: {response.get('error', {}).get('message', 'unknown')[:100]}\n")
                else:
                    sys.stderr.write(f"[proxy] ✓ Tool {tool_name} completed\n")
                sys.stderr.flush()

            return response, new_session_id, new_locked

    except asyncio.TimeoutError:
        if tool_name:
            sys.stderr.write(f"[proxy] ⏱️ Tool {tool_name} timed out after {DEFAULT_TIMEOUT_SECONDS}s\n")
            sys.stderr.flush()
        if is_notification:
            return None, current_session_id, is_session_locked
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32000, "message": f"Request timed out after {DEFAULT_TIMEOUT_SECONDS}s"}
        }, current_session_id, is_session_locked

    except Exception as e:
        if tool_name:
            sys.stderr.write(f"[proxy] ❌ Tool {tool_name} connection error: {str(e)[:100]}\n")
            sys.stderr.flush()
        # Return proper JSON-RPC error for connection errors
        if is_notification:
            return None, current_session_id, is_session_locked
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32000, "message": f"Connection error: {str(e)}"}
        }, current_session_id, is_session_locked


async def run_proxy(url: str, token: str, timeout: int):
    """Run the stdio proxy."""

    session_id: str | None = None
    session_locked: bool = False

    # Configure timeout for long-running operations (workload creation can take 10-30 min)
    client_timeout = aiohttp.ClientTimeout(total=timeout)

    async with aiohttp.ClientSession(timeout=client_timeout) as session:
        # Read from stdin line by line
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        await asyncio.get_event_loop().connect_read_pipe(lambda: protocol, sys.stdin)

        sys.stderr.write(f"[proxy] Connected to {url} (timeout: {timeout}s)\n")
        sys.stderr.flush()

        while True:
            try:
                line = await reader.readline()
                if not line:
                    break

                line = line.decode().strip()
                if not line:
                    continue

                # Parse JSON-RPC request
                try:
                    request = json.loads(line)
                except json.JSONDecodeError as e:
                    sys.stderr.write(f"[proxy] Invalid JSON: {e}\n")
                    sys.stderr.flush()
                    continue

                # Forward to remote server
                response, session_id, session_locked = await proxy_request(
                    session, url, token, request, session_id, session_locked
                )

                # Write response to stdout (skip for notifications which return None)
                if response is not None:
                    sys.stdout.write(json.dumps(response) + "\n")
                    sys.stdout.flush()

            except Exception as e:
                sys.stderr.write(f"[proxy] Error: {e}\n")
                sys.stderr.flush()


def main():
    parser = argparse.ArgumentParser(description="Claude Desktop Proxy for DataRobot MCP Workloads")
    parser.add_argument("--url", required=True, help="Remote MCP server URL")
    parser.add_argument("--token", required=True, help="API bearer token")
    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT_SECONDS,
        help=f"Request timeout in seconds (default: {DEFAULT_TIMEOUT_SECONDS})"
    )
    args = parser.parse_args()

    asyncio.run(run_proxy(args.url, args.token, args.timeout))


if __name__ == "__main__":
    main()
