#!/usr/bin/env python3
"""Helm MCP server — per-agent messaging bridge.

Stdio-based MCP server spawned by Claude Code via --mcp-config.
One instance per agent. Connects to the Helm broker for message
routing and provides native MCP tools for inter-agent communication.

Config via environment variables:
    HELM_AGENT_ID       - This agent's ID
    HELM_BROKER_URL     - Broker HTTP URL (e.g. http://127.0.0.1:54321)
    HELM_EXPERIMENT_DIR - Experiment directory path
    HELM_PEERS          - JSON list of peer agent IDs and roles

Usage (from --mcp-config JSON):
    {
        "mcpServers": {
            "helm-messaging": {
                "command": "python",
                "args": ["-m", "helm.coordination.mcp_server"],
                "env": {
                    "HELM_AGENT_ID": "researcher_a",
                    "HELM_BROKER_URL": "http://127.0.0.1:54321",
                    "HELM_EXPERIMENT_DIR": "/path/to/experiment",
                    "HELM_PEERS": "[{\\"id\\": \\"coordinator\\", \\"role\\": \\"hub\\"}]"
                }
            }
        }
    }
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
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
# Per-agent capability flags (set by broker_backend based on topology/role)
CAN_SPAWN = os.environ.get("HELM_CAN_SPAWN", "false").lower() == "true"
CAN_SIGNAL_DONE = os.environ.get("HELM_CAN_SIGNAL_DONE", "true").lower() == "true"

# Track last seen message ID for incremental polling
_last_seen_id = 0

TMUX_WIDTH = "220"
TMUX_HEIGHT = "50"
TMUX_READY_TIMEOUT_SECONDS = 10.0
TMUX_READY_POLL_SECONDS = 0.5


def _log(msg: str) -> None:
    sys.stderr.write(f"[helm-mcp:{AGENT_ID}] {msg}\n")
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


def _capture_tmux_pane(tmux_name: str) -> str:
    """Capture the visible content of a tmux pane."""
    result = subprocess.run(
        ["tmux", "capture-pane", "-t", tmux_name, "-p", "-S", "-50"],
        capture_output=True,
        text=True,
    )
    return result.stdout if result.returncode == 0 else ""


def _pane_is_ready(pane: str) -> bool:
    """Best-effort readiness signal for the Claude TUI."""
    return "❯" in pane and "WARNING" not in pane


def _wait_for_bypass_dialog(tmux_name: str) -> None:
    """Wait for Claude's bypass dialog and accept it when it appears."""
    deadline = time.time() + TMUX_READY_TIMEOUT_SECONDS
    while time.time() < deadline:
        pane = _capture_tmux_pane(tmux_name)
        if "Yes, I accept" in pane:
            subprocess.run(
                ["tmux", "send-keys", "-t", tmux_name, "Down"],
                capture_output=True,
            )
            time.sleep(0.3)
            subprocess.run(
                ["tmux", "send-keys", "-t", tmux_name, "Enter"],
                capture_output=True,
            )
            return
        if _pane_is_ready(pane):
            return
        time.sleep(TMUX_READY_POLL_SECONDS)


def _wait_for_tmux_ready(tmux_name: str) -> None:
    """Wait until the Claude TUI looks ready for message injection."""
    deadline = time.time() + TMUX_READY_TIMEOUT_SECONDS
    while time.time() < deadline:
        if _pane_is_ready(_capture_tmux_pane(tmux_name)):
            return
        time.sleep(TMUX_READY_POLL_SECONDS)


def _paste_buffer_into_tmux(tmux_name: str, content: str, prefix: str) -> None:
    """Send arbitrary text into a tmux session via tmux buffer paste."""
    fd, tmp_name = tempfile.mkstemp(prefix=prefix, suffix=".txt")
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w") as handle:
            handle.write(content)
        buffer_name = prefix.rstrip("_")
        subprocess.run(
            ["tmux", "load-buffer", "-b", buffer_name, str(tmp_path)],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["tmux", "paste-buffer", "-b", buffer_name, "-t", tmux_name],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["tmux", "send-keys", "-t", tmux_name, "Enter"],
            check=True,
            capture_output=True,
        )
    finally:
        tmp_path.unlink(missing_ok=True)


def _tmux_session_name(*parts: str) -> str:
    """Create a tmux-safe session name."""
    joined = "-".join(part.replace("/", "-").replace(".", "-") for part in parts if part)
    name = f"helm-{joined}" if joined else "helm-agent"
    return name[:80]


# ── Tool handlers ──

TOOLS = [
    {
        "name": "helm_send_message",
        "description": (
            "Send a message to another agent in the experiment. "
            "Messages are delivered through the Helm coordination broker. "
            "The broker enforces topology rules — you can only message "
            "agents you are allowed to communicate with."
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
        "name": "helm_check_inbox",
        "description": (
            "Check for new messages from other agents. "
            "Returns only messages received since your last check. "
            "Call this periodically to see if other agents have sent you anything."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "helm_list_peers",
        "description": (
            "List the other agents in this experiment and their roles."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "helm_signal_done",
        "description": (
            "Signal that the experiment is complete. Writes the verification "
            "summary and done signal. Only the coordinator should call this."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "summary": {
                    "type": "string",
                    "description": "Verification summary text",
                },
            },
            "required": ["summary"],
        },
    },
    {
        "name": "helm_spawn_agent",
        "description": (
            "Spawn a new agent in the experiment. Creates a new Claude Code "
            "session in a tmux pane with messaging tools configured. "
            "The spawned agent can send/receive messages but cannot spawn "
            "further agents. Only available to agents with spawn permission."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "agent_id": {
                    "type": "string",
                    "description": "Unique ID for the new agent (e.g. 'worker-3')",
                },
                "task": {
                    "type": "string",
                    "description": "The initial task/prompt for the new agent",
                },
                "role": {
                    "type": "string",
                    "description": "Role label for the agent (default: 'worker')",
                    "default": "worker",
                },
            },
            "required": ["agent_id", "task"],
        },
    },
]


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
            error_msg = f"Topology violation: {error_msg}"
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


def _handle_list_peers(args: dict) -> dict:
    peers = _current_peers()

    if not peers:
        return {
            "content": [{"type": "text", "text": "No peers configured."}]
        }

    lines = [f"You are: {AGENT_ID}\n", "Peers:"]
    for p in peers:
        pid = p.get("id", "?")
        role = p.get("role", "peer")
        lines.append(f"  - {pid} ({role})")

    return {"content": [{"type": "text", "text": "\n".join(lines)}]}


def _handle_signal_done(args: dict) -> dict:
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
                    "text": "Error: HELM_EXPERIMENT_DIR not set.",
                }
            ],
            "isError": True,
        }

    signals_dir = Path(EXPERIMENT_DIR) / "coordination" / "signals"
    signals_dir.mkdir(parents=True, exist_ok=True)

    # Write verification summary
    (signals_dir / "verification-summary.md").write_text(summary)
    # Write done signal
    (signals_dir / "done").write_text("done\n")

    return {
        "content": [
            {
                "type": "text",
                "text": "Experiment marked as complete. Verification summary written.",
            }
        ]
    }


def _handle_spawn_agent(args: dict) -> dict:
    if not CAN_SPAWN:
        return {
            "content": [
                {
                    "type": "text",
                    "text": "Error: You do not have permission to spawn agents. "
                    "Only agents with spawn capability can use this tool.",
                }
            ],
            "isError": True,
        }

    agent_id = args.get("agent_id", "")
    task = args.get("task", "")
    role = args.get("role", "worker")
    if not agent_id or not task:
        return {
            "content": [
                {"type": "text", "text": "Error: 'agent_id' and 'task' are required."}
            ],
            "isError": True,
        }

    # Register spawned agent with broker
    reg = _broker_post("/register", {
        "agent_id": agent_id,
        "experiment_id": EXPERIMENT_ID,
        "role": role,
    })
    if reg.get("error"):
        return {
            "content": [{"type": "text", "text": f"Error registering agent: {reg['error']}"}],
            "isError": True,
        }

    current_peers = _current_peers()
    parent_recipients = [
        peer.get("id")
        for peer in current_peers
        if isinstance(peer, dict) and isinstance(peer.get("id"), str)
    ]
    if agent_id not in parent_recipients:
        parent_recipients.append(agent_id)

    parent_update = _broker_post(
        "/update_topology",
        {
            "agent_id": AGENT_ID,
            "allowed_recipients": parent_recipients,
        },
    )
    if parent_update.get("error"):
        return {
            "content": [{"type": "text", "text": f"Error updating parent topology: {parent_update['error']}"}],
            "isError": True,
        }

    child_update = _broker_post(
        "/update_topology",
        {
            "agent_id": agent_id,
            "allowed_recipients": [AGENT_ID],
        },
    )
    if child_update.get("error"):
        return {
            "content": [{"type": "text", "text": f"Error updating child topology: {child_update['error']}"}],
            "isError": True,
        }

    spawned_peers = [{"id": AGENT_ID, "role": AGENT_ROLE}]

    # Write MCP config for the spawned agent (no spawn capability)
    mcp_dir = Path(EXPERIMENT_DIR) / "mcp-configs" if EXPERIMENT_DIR else Path("/tmp/helm-tmux-test/mcp-configs")
    mcp_dir.mkdir(parents=True, exist_ok=True)

    python_bin = sys.executable
    mcp_config = {
        "mcpServers": {
            "helm-messaging": {
                "command": python_bin,
                "args": ["-m", "helm.coordination.mcp_server"],
                "env": {
                    "HELM_AGENT_ID": agent_id,
                    "HELM_BROKER_URL": BROKER_URL,
                    "HELM_EXPERIMENT_DIR": EXPERIMENT_DIR,
                    "HELM_EXPERIMENT_ID": EXPERIMENT_ID,
                    "HELM_AGENT_ROLE": role,
                    "HELM_PEERS": json.dumps(spawned_peers),
                    "HELM_CAN_SPAWN": "false",  # Spawned agents cannot spawn further
                    "HELM_CAN_SIGNAL_DONE": "false",
                    "PYTHONPATH": os.environ.get("PYTHONPATH", ""),
                },
            }
        }
    }
    config_path = mcp_dir / f"{agent_id}.json"
    config_path.write_text(json.dumps(mcp_config, indent=2))

    # Find claude binary
    claude_bin = shutil.which("claude")
    if not claude_bin:
        return {
            "content": [{"type": "text", "text": "Error: claude CLI not found in PATH"}],
            "isError": True,
        }

    # Create tmux session name
    tmux_name = _tmux_session_name(EXPERIMENT_ID, agent_id)

    # Build the system prompt
    system_prompt = (
        f"You are agent '{agent_id}' (role: {role}) in a multi-agent experiment. "
        f"You were spawned by '{AGENT_ID}'. "
        f"Use helm_send_message to communicate with other agents. "
        f"Use helm_check_inbox to check for messages. "
        f"When done, send your results back to '{AGENT_ID}'."
    )

    # Spawn tmux session
    try:
        subprocess.run(
            ["tmux", "new-session", "-d", "-s", tmux_name, "-x", TMUX_WIDTH, "-y", TMUX_HEIGHT],
            check=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError as e:
        return {
            "content": [{"type": "text", "text": f"Error creating tmux session: {e.stderr.decode()}"}],
            "isError": True,
        }

    # Build claude command
    claude_cmd = (
        f"{claude_bin} --permission-mode bypassPermissions "
        f"--mcp-config {shlex.quote(str(config_path))}"
    )

    # Send the claude command to tmux
    subprocess.run(
        ["tmux", "send-keys", "-t", tmux_name, claude_cmd, "Enter"],
        check=True,
        capture_output=True,
    )

    _wait_for_bypass_dialog(tmux_name)
    _wait_for_tmux_ready(tmux_name)

    # Send the task via tmux paste-buffer
    full_prompt = f"{system_prompt}\n\n## Your Task\n{task}"
    _paste_buffer_into_tmux(
        tmux_name,
        full_prompt,
        f"helm_spawn_{agent_id[-8:]}_",
    )

    _log(f"spawned agent {agent_id} in tmux session {tmux_name}")
    return {
        "content": [
            {
                "type": "text",
                "text": (
                    f"Agent '{agent_id}' spawned in tmux session '{tmux_name}'. "
                    f"It has messaging tools but cannot spawn further agents. "
                    f"Send it messages with helm_send_message(to='{agent_id}', ...)."
                ),
            }
        ]
    }


TOOL_HANDLERS = {
    "helm_send_message": _handle_send_message,
    "helm_check_inbox": _handle_check_inbox,
    "helm_list_peers": _handle_list_peers,
    "helm_signal_done": _handle_signal_done,
    "helm_spawn_agent": _handle_spawn_agent,
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
                        "name": "helm-messaging",
                        "version": "0.1.0",
                    },
                },
            })
        elif method == "notifications/initialized":
            pass  # Client ack
        elif method == "tools/list":
            # Filter tools based on agent capabilities
            available = []
            for tool in TOOLS:
                if tool["name"] == "helm_spawn_agent" and not CAN_SPAWN:
                    continue
                if tool["name"] == "helm_signal_done" and not CAN_SIGNAL_DONE:
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
