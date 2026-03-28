#!/usr/bin/env python3
"""Spike: Test whether MCP channel push works with `claude -p`.

This script:
1. Writes a minimal MCP server to a temp file
2. Writes an MCP config JSON pointing to it
3. Launches `claude -p` with the config and channel flags
4. The MCP server pushes a notification after 10 seconds
5. We check if Claude received and responded to the push

Usage:
    python scripts/spike_channel_push.py
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# The MCP server script — a self-contained Python file that the MCP SDK runs.
# It declares channel capability, exposes a simple tool, and pushes a
# notification after a delay.
MCP_SERVER_SCRIPT = '''\
#!/usr/bin/env python3
"""Minimal MCP server for testing channel push into claude -p."""

import asyncio
import json
import sys
import threading
import time


def write_jsonrpc(obj: dict) -> None:
    """Write a JSON-RPC message to stdout."""
    data = json.dumps(obj)
    sys.stdout.write(data + "\\n")
    sys.stdout.flush()


def read_jsonrpc() -> dict | None:
    """Read a JSON-RPC message from stdin."""
    try:
        line = sys.stdin.readline()
        if not line:
            return None
        return json.loads(line.strip())
    except (json.JSONDecodeError, EOFError):
        return None


def handle_initialize(msg: dict) -> None:
    """Respond to initialize request."""
    write_jsonrpc({
        "jsonrpc": "2.0",
        "id": msg["id"],
        "result": {
            "protocolVersion": "2024-11-05",
            "capabilities": {
                "tools": {},
                "experimental": {
                    "claude/channel": {}
                }
            },
            "serverInfo": {
                "name": "helm-spike",
                "version": "0.1.0"
            }
        }
    })


def handle_tools_list(msg: dict) -> None:
    """Return available tools."""
    write_jsonrpc({
        "jsonrpc": "2.0",
        "id": msg["id"],
        "result": {
            "tools": [
                {
                    "name": "spike_ping",
                    "description": "Test tool that returns pong. Used to verify MCP connection.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {},
                    }
                }
            ]
        }
    })


def handle_tool_call(msg: dict) -> None:
    """Handle a tool call."""
    tool_name = msg.get("params", {}).get("name", "")
    if tool_name == "spike_ping":
        write_jsonrpc({
            "jsonrpc": "2.0",
            "id": msg["id"],
            "result": {
                "content": [
                    {"type": "text", "text": "pong — MCP connection is working"}
                ]
            }
        })
    else:
        write_jsonrpc({
            "jsonrpc": "2.0",
            "id": msg["id"],
            "error": {"code": -32601, "message": f"Unknown tool: {tool_name}"}
        })


def push_channel_message(delay: float = 10.0) -> None:
    """After a delay, push a channel notification."""
    time.sleep(delay)
    write_jsonrpc({
        "jsonrpc": "2.0",
        "method": "notifications/claude/channel",
        "params": {
            "content": "PUSH TEST: This message was pushed via MCP channel notification after a 10-second delay. If you can read this, channel push is working. Please respond with: PUSH_RECEIVED.",
            "meta": {
                "source": "helm-spike",
                "test_id": "channel-push-validation"
            }
        }
    })
    sys.stderr.write("[helm-spike] Channel notification sent\\n")
    sys.stderr.flush()


def main() -> None:
    sys.stderr.write("[helm-spike] MCP server starting\\n")
    sys.stderr.flush()

    # Start the push in a background thread
    push_thread = threading.Thread(target=push_channel_message, args=(10.0,), daemon=True)
    push_thread.start()

    # Main loop: handle JSON-RPC messages
    while True:
        msg = read_jsonrpc()
        if msg is None:
            break

        method = msg.get("method", "")
        sys.stderr.write(f"[helm-spike] Received: {method}\\n")
        sys.stderr.flush()

        if method == "initialize":
            handle_initialize(msg)
        elif method == "notifications/initialized":
            pass  # Client acknowledgment, no response needed
        elif method == "tools/list":
            handle_tools_list(msg)
        elif method == "tools/call":
            handle_tool_call(msg)
        elif method == "ping":
            write_jsonrpc({"jsonrpc": "2.0", "id": msg.get("id"), "result": {}})
        else:
            # Unknown method — respond with error if it has an ID
            if "id" in msg:
                write_jsonrpc({
                    "jsonrpc": "2.0",
                    "id": msg["id"],
                    "error": {"code": -32601, "message": f"Unknown method: {method}"}
                })


if __name__ == "__main__":
    main()
'''


def run_spike() -> bool:
    """Run the channel push spike test."""
    claude_bin = shutil.which("claude")
    if not claude_bin:
        print("ERROR: claude CLI not found in PATH")
        return False

    with tempfile.TemporaryDirectory(prefix="helm-spike-") as tmpdir:
        tmpdir_path = Path(tmpdir)

        # Write the MCP server script
        server_path = tmpdir_path / "mcp_server.py"
        server_path.write_text(MCP_SERVER_SCRIPT)
        server_path.chmod(0o755)

        # Write the MCP config
        python_bin = sys.executable
        mcp_config = {
            "mcpServers": {
                "helm-spike": {
                    "command": python_bin,
                    "args": [str(server_path)],
                }
            }
        }
        config_path = tmpdir_path / "mcp-config.json"
        config_path.write_text(json.dumps(mcp_config, indent=2))

        prompt = (
            "You have an MCP server connected called helm-spike. "
            "First, call the spike_ping tool to verify the connection works. "
            "Then wait — a push notification should arrive in about 10 seconds. "
            "When you receive any channel notification or push message, "
            "respond with exactly: PUSH_RECEIVED. "
            "If after 20 seconds you have not received anything, respond with: NO_PUSH."
        )

        cmd = [
            claude_bin,
            "-p", prompt,
            "--mcp-config", str(config_path),
            "--output-format", "stream-json",
            "--dangerously-skip-permissions",
            "--no-session-persistence",
        ]

        print(f"Running spike test...")
        print(f"  MCP server: {server_path}")
        print(f"  MCP config: {config_path}")
        print(f"  Command: {' '.join(cmd[:6])}...")
        print()

        # Run with timeout
        env = {k: v for k, v in os.environ.items()}
        # Remove nested-session detection vars
        for var in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "_CLAUDE_SESSION_VARS"):
            env.pop(var, None)

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
                env=env,
            )
        except subprocess.TimeoutExpired:
            print("TIMEOUT: Claude did not finish within 120 seconds")
            return False

        # Parse NDJSON output
        push_received = False
        tool_used = False
        channel_event_seen = False

        print("=== STDOUT (NDJSON events) ===")
        for line in result.stdout.strip().split("\n"):
            if not line.strip():
                continue
            try:
                event = json.loads(line)
                event_type = event.get("type", "")

                # Check for tool use (spike_ping)
                if event_type == "assistant":
                    content = event.get("message", {}).get("content", [])
                    for part in content:
                        if isinstance(part, dict):
                            if part.get("type") == "tool_use" and part.get("name") == "spike_ping":
                                tool_used = True
                                print(f"  [tool] spike_ping called")
                            if part.get("type") == "text":
                                text = part.get("text", "")
                                if "PUSH_RECEIVED" in text:
                                    push_received = True
                                print(f"  [text] {text[:200]}")

                # Check for channel events in the stream
                if "channel" in str(event).lower():
                    channel_event_seen = True
                    print(f"  [channel] {json.dumps(event)[:200]}")

            except json.JSONDecodeError:
                print(f"  [raw] {line[:200]}")

        print()
        print("=== STDERR ===")
        for line in result.stderr.strip().split("\n")[-20:]:
            if line.strip():
                print(f"  {line}")

        print()
        print("=== RESULTS ===")
        print(f"  Tool (spike_ping) used: {tool_used}")
        print(f"  Channel event seen in stream: {channel_event_seen}")
        print(f"  PUSH_RECEIVED in output: {push_received}")
        print(f"  Exit code: {result.returncode}")

        if push_received:
            print()
            print("SUCCESS: Channel push works with claude -p!")
            print("Phase 2 (push delivery) is viable.")
            return True
        elif tool_used:
            print()
            print("PARTIAL: MCP tools work but channel push did not arrive.")
            print("Phase 1 (MCP tools with polling) is viable. Phase 2 needs investigation.")
            return False
        else:
            print()
            print("FAILURE: MCP server did not connect properly.")
            return False


if __name__ == "__main__":
    success = run_spike()
    sys.exit(0 if success else 1)
