#!/usr/bin/env python3
"""Agent orchestration MCP server — per-agent coordination tools.

Stdio-based MCP server providing inter-agent messaging and coordination
tools. One instance per agent. Routes messages through a coordination
broker and provides tools for sending messages, checking for new
messages, listing other agents, and signaling task completion.

Config via environment variables:
    HELM_AGENT_ID       - This agent's ID
    HELM_BROKER_URL     - Broker HTTP URL (e.g. http://127.0.0.1:54321)
    HELM_EXPERIMENT_DIR - Working directory for coordination signals
    HELM_PEERS          - JSON list of peer agent IDs and roles

Usage (from --mcp-config JSON):
    {
        "mcpServers": {
            "agent-orchestrator": {
                "command": "python",
                "args": ["-m", "helm.coordination.mcp_server"],
                "env": {
                    "HELM_AGENT_ID": "researcher_a",
                    "HELM_BROKER_URL": "http://127.0.0.1:54321",
                    "HELM_EXPERIMENT_DIR": "/path/to/workdir",
                    "HELM_PEERS": "[{\\"id\\": \\"coordinator\\", \\"role\\": \\"hub\\"}]"
                }
            }
        }
    }
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

# ── Config from environment ──

AGENT_ID = os.environ.get("HELM_AGENT_ID", "unknown")
BROKER_URL = os.environ.get("HELM_BROKER_URL", "http://127.0.0.1:7899")
EXPERIMENT_DIR = os.environ.get("HELM_EXPERIMENT_DIR", "")
EXPERIMENT_ID = os.environ.get("HELM_EXPERIMENT_ID", "")
PEERS_JSON = os.environ.get("HELM_PEERS", "[]")
AGENT_ROLE = os.environ.get("HELM_AGENT_ROLE", "peer")
# Per-agent capability flag (controls tool visibility)
CAN_SIGNAL_DONE = os.environ.get("HELM_CAN_SIGNAL_DONE", "true").lower() == "true"

# Track last seen message ID for incremental polling
_last_seen_id = 0


def _log(msg: str) -> None:
    sys.stderr.write(f"[orchestrator:{AGENT_ID}] {msg}\n")
    sys.stderr.flush()


# ── Broker HTTP client ──


def _broker_post(path: str, body: dict) -> dict:
    """POST JSON to the broker."""
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        f"{BROKER_URL}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body_text = e.read().decode() if e.fp else ""
        try:
            return json.loads(body_text)
        except json.JSONDecodeError:
            return {"error": body_text, "status": e.code}
    except Exception as e:
        return {"error": str(e)}


def _broker_get(path: str) -> dict:
    """GET JSON from the broker."""
    req = urllib.request.Request(
        f"{BROKER_URL}{path}",
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read())
    except Exception as e:
        return {"error": str(e)}


# ── JSON-RPC stdio transport ──


def _write_jsonrpc(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def _read_jsonrpc() -> dict | None:
    try:
        line = sys.stdin.readline()
        if not line:
            return None
        return json.loads(line.strip())
    except (json.JSONDecodeError, EOFError):
        return None


def _load_static_peers() -> list[dict]:
    """Parse the static peer list from the agent environment."""
    try:
        peers = json.loads(PEERS_JSON)
    except json.JSONDecodeError:
        return []
    return peers if isinstance(peers, list) else []


def _current_peers() -> list[dict]:
    """Return the current peer list, preferring broker state when available."""
    result = _broker_get(f"/peers/{AGENT_ID}")
    peers = result.get("peers")
    if isinstance(peers, list):
        return peers
    return _load_static_peers()


# ── Tool definitions ──

TOOLS = [
    {
        "name": "send_message",
        "description": (
            "Send a message to another agent. Messages are routed through "
            "the coordination system. You can only message agents you are "
            "permitted to communicate with."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "to": {
                    "type": "string",
                    "description": "The agent ID to send the message to",
                },
                "content": {
                    "type": "string",
                    "description": "The message content",
                },
            },
            "required": ["to", "content"],
        },
    },
    {
        "name": "check_inbox",
        "description": (
            "Check for new messages from other agents. Returns messages "
            "received since your last check."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "list_agents",
        "description": "List the other agents in this system and their roles.",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "signal_complete",
        "description": (
            "Signal that the work is complete. Provide a summary of what "
            "was accomplished and the final status."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "summary": {
                    "type": "string",
                    "description": "Summary of work completed and final status",
                },
            },
            "required": ["summary"],
        },
    },
]


# ── Tool handlers ──


def _handle_send_message(args: dict) -> dict:
    to_id = args.get("to", "")
    content = args.get("content", "")
    if not to_id or not content:
        return {
            "content": [
                {"type": "text", "text": "Error: 'to' and 'content' are required."}
            ],
            "isError": True,
        }

    result = _broker_post("/send", {
        "from_id": AGENT_ID,
        "to_id": to_id,
        "content": content,
    })

    if result.get("error"):
        error_msg = result["error"]
        if result.get("topology_violation"):
            error_msg = f"Not permitted: {error_msg}"
        return {
            "content": [{"type": "text", "text": f"Error: {error_msg}"}],
            "isError": True,
        }

    return {
        "content": [
            {
                "type": "text",
                "text": f"Message sent to {to_id} (id={result.get('message_id')})",
            }
        ]
    }


def _handle_check_inbox(args: dict) -> dict:
    global _last_seen_id  # noqa: PLW0603

    result = _broker_get(f"/poll/{AGENT_ID}?after_id={_last_seen_id}")
    messages = result.get("messages", [])

    if result.get("error"):
        return {
            "content": [
                {"type": "text", "text": f"Error checking inbox: {result['error']}"}
            ],
            "isError": True,
        }

    if not messages:
        return {
            "content": [
                {"type": "text", "text": "No new messages."}
            ]
        }

    # Update cursor
    for m in messages:
        if m.get("id", 0) > _last_seen_id:
            _last_seen_id = m["id"]

    # Format messages
    lines = [f"{len(messages)} new message(s):\n"]
    for m in messages:
        lines.append(f"--- From: {m['from_id']} ---")
        lines.append(m["content"])
        lines.append("")

    return {
        "content": [{"type": "text", "text": "\n".join(lines)}]
    }


def _handle_list_agents(args: dict) -> dict:
    peers = _current_peers()

    if not peers:
        return {
            "content": [{"type": "text", "text": "No other agents found."}]
        }

    lines = [f"You are: {AGENT_ID}\n", "Other agents:"]
    for p in peers:
        pid = p.get("id", "?")
        role = p.get("role", "peer")
        lines.append(f"  - {pid} ({role})")

    return {"content": [{"type": "text", "text": "\n".join(lines)}]}


def _handle_signal_complete(args: dict) -> dict:
    summary = args.get("summary", "")
    if not summary:
        return {
            "content": [
                {"type": "text", "text": "Error: 'summary' is required."}
            ],
            "isError": True,
        }

    if not EXPERIMENT_DIR:
        return {
            "content": [
                {
                    "type": "text",
                    "text": "Error: working directory not configured.",
                }
            ],
            "isError": True,
        }

    signals_dir = Path(EXPERIMENT_DIR) / "coordination" / "signals"
    signals_dir.mkdir(parents=True, exist_ok=True)

    (signals_dir / "verification-summary.md").write_text(summary)
    (signals_dir / "done").write_text("done\n")

    return {
        "content": [
            {
                "type": "text",
                "text": "Work marked as complete. Summary written.",
            }
        ]
    }


TOOL_HANDLERS = {
    "send_message": _handle_send_message,
    "check_inbox": _handle_check_inbox,
    "list_agents": _handle_list_agents,
    "signal_complete": _handle_signal_complete,
}


# ── Main loop ──


def main() -> None:
    _log("starting")

    # Register with broker
    reg_result = _broker_post("/register", {
        "agent_id": AGENT_ID,
        "experiment_id": EXPERIMENT_ID,
        "role": AGENT_ROLE,
    })
    _log(f"registered: {reg_result}")

    while True:
        msg = _read_jsonrpc()
        if msg is None:
            _log("stdin closed, exiting")
            break

        method = msg.get("method", "")
        msg_id = msg.get("id")

        if method == "initialize":
            _write_jsonrpc({
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {
                        "tools": {},
                    },
                    "serverInfo": {
                        "name": "agent-orchestrator",
                        "version": "0.2.0",
                        "description": (
                            "Coordination tools for multi-agent systems. "
                            "Send and receive messages, list other agents, "
                            "and signal task completion."
                        ),
                    },
                },
            })
        elif method == "notifications/initialized":
            pass  # Client ack
        elif method == "tools/list":
            available = []
            for tool in TOOLS:
                if tool["name"] == "signal_complete" and not CAN_SIGNAL_DONE:
                    continue
                available.append(tool)
            _write_jsonrpc({
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {"tools": available},
            })
        elif method == "tools/call":
            tool_name = msg.get("params", {}).get("name", "")
            tool_args = msg.get("params", {}).get("arguments", {})
            handler = TOOL_HANDLERS.get(tool_name)
            if handler:
                result = handler(tool_args)
            else:
                result = {
                    "content": [
                        {
                            "type": "text",
                            "text": f"Unknown tool: {tool_name}",
                        }
                    ],
                    "isError": True,
                }
            _write_jsonrpc({
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": result,
            })
        elif method == "ping":
            _write_jsonrpc({
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {},
            })
        else:
            if msg_id is not None:
                _write_jsonrpc({
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "error": {
                        "code": -32601,
                        "message": f"Unknown method: {method}",
                    },
                })


if __name__ == "__main__":
    main()
