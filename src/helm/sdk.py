"""Python client for the Sandbox Agent SDK REST API.

Wraps the SDK daemon that provides a universal interface to coding agents.
The daemon is spawned as a subprocess and communicates via ACP (Agent Client
Protocol) JSON-RPC over HTTP.

v0.2.x uses the ACP endpoint (``/v1/acp/{server_id}``) with JSON-RPC
envelopes instead of the old per-session REST routes.
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import subprocess
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator

import httpx
from httpx_sse import aconnect_sse


@dataclass
class SDKConfig:
    """Configuration for the SDK daemon."""

    binary_path: Path
    host: str = "127.0.0.1"
    port: int = 8765
    timeout_ms: int = 30000
    log_level: str = "silent"


@dataclass
class SessionConfig:
    """Configuration for creating a session."""

    agent: str = "claude"
    permission_mode: str = "default"
    allowed_commands: list[str] | None = None
    cwd: str | None = None
    session_marker: str | None = None
    disallowed_tools: list[str] = field(default_factory=list)


class SDKEvent:
    """An event from the SDK event stream."""

    def __init__(self, event_type: str, data: dict[str, Any]):
        self.type = event_type
        self.data = data

    def __repr__(self) -> str:
        return f"SDKEvent({self.type!r}, {self.data!r})"


class FollowUpMessageUnsupportedError(RuntimeError):
    """Raised when a harness cannot accept another message mid-session."""


# Env vars set by Claude Code that trigger nested-session detection.
# Must be stripped before spawning subprocesses that run Claude CLI.
_CLAUDE_SESSION_VARS = {
    "CLAUDECODE",
    "CLAUDE_CODE_ENTRYPOINT",
    "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS",
}

API_PREFIX = "/v1"


class SDKClient:
    """Python client for the Sandbox Agent SDK (v0.2.x ACP protocol).

    Manages the SDK daemon lifecycle and provides methods for:
    - Session management via ACP servers (create, terminate)
    - Message posting via JSON-RPC ``session/prompt``
    - Event streaming via SSE on ``/v1/acp/{server_id}``
    - Permission/question handling via JSON-RPC responses
    """

    def __init__(self, config: SDKConfig):
        self.config = config
        self._process: subprocess.Popen | None = None
        self._client: httpx.AsyncClient | None = None
        # Maps session_id -> { server_id, acp_session_id, agent }
        self._sessions: dict[str, dict[str, str]] = {}
        self._rpc_counter = 0

    @property
    def base_url(self) -> str:
        return f"http://{self.config.host}:{self.config.port}"

    @property
    def api_url(self) -> str:
        return f"{self.base_url}{API_PREFIX}"

    def _next_rpc_id(self) -> str:
        self._rpc_counter += 1
        return str(self._rpc_counter)

    async def _rpc(
        self,
        server_id: str,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        query: dict[str, str] | None = None,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        """Send a JSON-RPC request to an ACP server and return the result.

        Raises RuntimeError on JSON-RPC errors.
        """
        if self._client is None:
            raise RuntimeError("Client not started")

        envelope: dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": self._next_rpc_id(),
            "method": method,
        }
        if params is not None:
            envelope["params"] = params

        response = await self._client.post(
            f"{API_PREFIX}/acp/{server_id}",
            json=envelope,
            params=query,
            timeout=timeout,
        )
        response.raise_for_status()
        body = response.json()

        if "error" in body and body["error"] is not None:
            err = body["error"]
            detail = err.get("data", {}).get("details", err.get("message", "unknown"))
            raise RuntimeError(
                f"ACP RPC error (method={method}): {err.get('message')} — {detail}"
            )

        return body.get("result", {})

    async def start(self) -> None:
        """Start the SDK daemon and wait for it to be ready."""
        if self._process is not None:
            return

        import os

        # Spawn the daemon process with server subcommand
        cmd = [
            str(self.config.binary_path),
            "server",
            "--host", self.config.host,
            "--port", str(self.config.port),
            "--no-token",  # Disable token auth for local use
        ]

        # Strip Claude Code session env vars to prevent nested-session
        # detection when the ACP bridge spawns a Claude CLI subprocess.
        env = {k: v for k, v in os.environ.items() if k not in _CLAUDE_SESSION_VARS}

        self._process = subprocess.Popen(
            cmd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        # Create HTTP client
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(30.0),
        )

        # Wait for daemon to be ready
        await self._wait_for_health()

        # Install agents that are available but not yet installed
        await self._ensure_agents_installed()

    async def _wait_for_health(self, max_attempts: int = 30) -> None:
        """Wait for the daemon health endpoint to respond."""
        for attempt in range(max_attempts):
            try:
                if self._client is None:
                    raise RuntimeError("Client not initialized")
                response = await self._client.get(f"{API_PREFIX}/health")
                if response.status_code == 200:
                    return
            except httpx.ConnectError:
                pass
            await asyncio.sleep(0.5)

        raise TimeoutError(f"SDK daemon did not start within {max_attempts * 0.5}s")

    async def _ensure_agents_installed(self) -> None:
        """Install any agents that have credentials but aren't installed."""
        if self._client is None:
            return
        try:
            response = await self._client.get(f"{API_PREFIX}/agents")
            if response.status_code != 200:
                return
            agents = response.json().get("agents", [])
            for agent in agents:
                if not agent.get("installed", True):
                    agent_id = agent.get("id")
                    if agent_id:
                        try:
                            await self._client.post(
                                f"{API_PREFIX}/agents/{agent_id}/install",
                                json={},
                            )
                        except Exception:
                            pass  # Best effort
        except Exception:
            pass

    async def create_session(
        self,
        session_id: str,
        config: SessionConfig | None = None,
    ) -> dict[str, Any]:
        """Create a new agent session via ACP.

        This creates an ACP server bound to the agent, initializes it,
        then creates a session within it.
        """
        if self._client is None:
            raise RuntimeError("Client not started")

        config = config or SessionConfig()
        server_id = session_id  # Use session_id as the ACP server_id

        # Step 1: Initialize ACP server with agent binding
        init_result = await self._rpc(
            server_id,
            "initialize",
            {"protocolVersion": 1},
            query={"agent": config.agent},
            timeout=15.0,
        )

        # Step 2: Create a session within the ACP server
        session_params: dict[str, Any] = {"mcpServers": []}
        if config.cwd:
            session_params["cwd"] = config.cwd

        session_result = await self._rpc(
            server_id,
            "session/new",
            session_params,
            timeout=30.0,
        )

        acp_session_id = session_result.get("sessionId", session_id)

        # Track the session mapping
        self._sessions[session_id] = {
            "server_id": server_id,
            "acp_session_id": acp_session_id,
            "agent": config.agent,
        }

        return {
            "session_id": session_id,
            "acp_session_id": acp_session_id,
            "agent_info": init_result.get("agentInfo", {}),
            "capabilities": init_result.get("agentCapabilities", {}),
        }

    async def terminate_session(self, session_id: str) -> None:
        """Terminate an agent session by closing its ACP server."""
        if self._client is None:
            raise RuntimeError("Client not started")

        session = self._sessions.get(session_id)
        server_id = session["server_id"] if session else session_id

        try:
            # Try session/cancel first if we have an ACP session ID
            if session and session.get("acp_session_id"):
                try:
                    await self._rpc(
                        server_id,
                        "session/cancel",
                        {"sessionId": session["acp_session_id"]},
                        timeout=5.0,
                    )
                except Exception:
                    pass

            # Then close the ACP server
            response = await self._client.delete(
                f"{API_PREFIX}/acp/{server_id}",
                timeout=5.0,
            )
            # 204 = success, 404 = already gone
        except Exception:
            pass  # Session may already be terminated

        self._sessions.pop(session_id, None)

    async def post_message(self, session_id: str, message: str) -> None:
        """Send a message to an agent session via ACP session/prompt."""
        if self._client is None:
            raise RuntimeError("Client not started")

        session = self._sessions.get(session_id)
        if session is None:
            raise RuntimeError(f"Unknown session: {session_id}")

        await self._rpc(
            session["server_id"],
            "session/prompt",
            {
                "sessionId": session["acp_session_id"],
                "prompt": [{"type": "text", "text": message}],
            },
            timeout=60.0,
        )

    def supports_follow_up_messages(self, session_id: str) -> bool:
        """Return whether a session can accept another prompt mid-run."""
        return session_id in self._sessions

    async def stream_events(
        self,
        session_id: str,
        signal: asyncio.Event | None = None,
        stream_timeout: float = 300.0,
    ) -> AsyncIterator[SDKEvent]:
        """Stream events from an agent session via SSE.

        Connects to ``GET /v1/acp/{server_id}`` which streams JSON-RPC
        notifications as ACP envelopes.

        Yields SDKEvent objects for each event received.
        Stops when session.ended is received, signal is set, or
        stream_timeout seconds elapse with no data from the server.
        """
        if self._client is None:
            raise RuntimeError("Client not started")

        session = self._sessions.get(session_id)
        server_id = session["server_id"] if session else session_id

        url = f"{self.api_url}/acp/{server_id}"

        timeout = httpx.Timeout(
            connect=30.0,
            read=stream_timeout,
            write=30.0,
            pool=30.0,
        )
        async with httpx.AsyncClient(timeout=timeout) as stream_client:
            try:
                async with aconnect_sse(stream_client, "GET", url) as event_source:
                    async for sse in event_source.aiter_sse():
                        if signal and signal.is_set():
                            break

                        if sse.data:
                            try:
                                data = json.loads(sse.data)
                            except json.JSONDecodeError:
                                continue

                            # ACP sends JSON-RPC notifications with method = "session/update"
                            # The actual event is nested in params.update
                            event = self._parse_acp_event(data)
                            if event is None:
                                continue

                            yield event

                            if event.type == "session.ended":
                                break
            except httpx.ReadTimeout:
                return  # Stream timed out — no data for stream_timeout seconds

    @staticmethod
    def _parse_acp_event(data: dict[str, Any]) -> SDKEvent | None:
        """Parse an ACP JSON-RPC envelope into an SDKEvent.

        ACP notifications look like:
        {
          "jsonrpc": "2.0",
          "method": "session/update",
          "params": {
            "sessionId": "...",
            "update": { "type": "...", ... }
          }
        }

        We also handle the old-style flat format for compatibility:
        { "type": "...", "data": { ... } }
        """
        # New ACP format: JSON-RPC notification
        if "method" in data:
            params = data.get("params", {})
            if isinstance(params, dict):
                update = params.get("update", {})
                if isinstance(update, dict) and "type" in update:
                    return SDKEvent(
                        update["type"],
                        {k: v for k, v in update.items() if k != "type"},
                    )

        # Old/flat format fallback
        if "type" in data:
            return SDKEvent(data["type"], data.get("data", {}))

        return None

    async def reply_permission(
        self,
        session_id: str,
        permission_id: str,
        reply: str = "once",
    ) -> None:
        """Reply to a permission request.

        In ACP, permission replies are JSON-RPC responses sent back
        to the server with the matching request ID.

        Args:
            session_id: The session ID
            permission_id: The permission request ID (JSON-RPC id)
            reply: One of "once", "always", "deny"
        """
        if self._client is None:
            raise RuntimeError("Client not started")

        session = self._sessions.get(session_id)
        if session is None:
            raise RuntimeError(f"Unknown session: {session_id}")

        # Send a JSON-RPC response (not a request) back to the ACP server
        envelope: dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": permission_id,
            "result": {"outcome": reply},
        }

        response = await self._client.post(
            f"{API_PREFIX}/acp/{session['server_id']}",
            json=envelope,
        )
        response.raise_for_status()

    async def reply_question(
        self,
        session_id: str,
        question_id: str,
        answer: str,
    ) -> None:
        """Reply to a question from the agent."""
        if self._client is None:
            raise RuntimeError("Client not started")

        session = self._sessions.get(session_id)
        if session is None:
            raise RuntimeError(f"Unknown session: {session_id}")

        envelope: dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": question_id,
            "result": {"answer": answer},
        }

        response = await self._client.post(
            f"{API_PREFIX}/acp/{session['server_id']}",
            json=envelope,
        )
        response.raise_for_status()

    async def reject_question(self, session_id: str, question_id: str) -> None:
        """Reject a question from the agent."""
        if self._client is None:
            raise RuntimeError("Client not started")

        session = self._sessions.get(session_id)
        if session is None:
            raise RuntimeError(f"Unknown session: {session_id}")

        envelope: dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": question_id,
            "error": {"code": -32600, "message": "Question rejected"},
        }

        response = await self._client.post(
            f"{API_PREFIX}/acp/{session['server_id']}",
            json=envelope,
        )
        response.raise_for_status()

    async def dispose(self) -> None:
        """Stop the SDK daemon and clean up resources."""
        if self._client:
            await self._client.aclose()
            self._client = None

        if self._process:
            self._process.terminate()
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()
            self._process = None

        self._sessions.clear()


@asynccontextmanager
async def sdk_client(config: SDKConfig) -> AsyncIterator[SDKClient]:
    """Context manager for SDK client lifecycle."""
    client = SDKClient(config)
    try:
        await client.start()
        yield client
    finally:
        await client.dispose()


# ---------------------------------------------------------------------------
# DirectCLIClient — runs agent CLI subprocesses instead of the SDK daemon
# ---------------------------------------------------------------------------


class HarnessAdapter:
    """Per-harness adapter for DirectCLIClient.

    Subclasses define how to build the subprocess command and how to
    parse NDJSON output into ``SDKEvent`` objects.
    """

    name: str = "base"

    def build_command(
        self, message: str, config: SessionConfig
    ) -> tuple[list[str], dict[str, str] | None]:
        """Return (cmd_args, env_overrides|None) for the subprocess."""
        raise NotImplementedError

    def parse_event(self, data: dict[str, Any]) -> SDKEvent | None:
        """Parse one NDJSON line into an SDKEvent, or None to skip."""
        raise NotImplementedError

    def post_process_events(self, config: SessionConfig) -> list[SDKEvent]:
        """Yield additional events after the subprocess exits.

        Called by DirectCLIClient after EOF on stdout, before the
        synthetic ``session.ended`` event.  Useful for harnesses like
        OpenCode that store the full conversation in a DB rather than
        streaming it to stdout.

        Default: no extra events.
        """
        return []


class ClaudeAdapter(HarnessAdapter):
    """Adapter for ``claude -p --output-format stream-json``."""

    name = "claude"

    def build_command(
        self, message: str, config: SessionConfig
    ) -> tuple[list[str], dict[str, str] | None]:
        import shutil

        claude_bin = shutil.which("claude")
        if claude_bin is None:
            raise RuntimeError("claude CLI not found in PATH")

        cmd = [
            claude_bin,
            "-p", message,
            "--output-format", "stream-json",
            "--verbose",
            "--dangerously-skip-permissions",
            "--no-session-persistence",
        ]
        if config.cwd:
            cmd.extend(["--add-dir", config.cwd])
        if config.disallowed_tools:
            cmd.extend(["--disallowedTools", ",".join(config.disallowed_tools)])
        return cmd, None

    def parse_event(self, data: dict[str, Any]) -> SDKEvent | None:
        msg_type = data.get("type")
        if msg_type is None:
            return None

        if msg_type == "system":
            return SDKEvent("session.started", data)

        if msg_type == "assistant":
            message = data.get("message", {})
            content = message.get("content", [])
            return SDKEvent("item.completed", {
                "item": {
                    "type": "message",
                    "role": "assistant",
                    "content": content,
                    "model": message.get("model"),
                    "stop_reason": message.get("stop_reason"),
                    "usage": message.get("usage", {}),
                },
                "raw": data,
            })

        if msg_type == "user":
            message = data.get("message", {})
            content = message.get("content", [])
            return SDKEvent("item.completed", {
                "item": {
                    "type": "message",
                    "role": "user",
                    "content": content,
                },
                "raw": data,
            })

        if msg_type == "result":
            return SDKEvent("session.ended", {
                "result": data.get("result"),
                "cost_usd": data.get("cost_usd"),
                "duration_ms": data.get("duration_ms"),
                "session_id": data.get("session_id"),
            })

        # Pass through unknown types (e.g. rate_limit_event)
        return SDKEvent(msg_type, data)


class CodexAdapter(HarnessAdapter):
    """Adapter for ``codex exec --json``."""

    name = "codex"

    def build_command(
        self, message: str, config: SessionConfig
    ) -> tuple[list[str], dict[str, str] | None]:
        import shutil

        codex_bin = shutil.which("codex")
        if codex_bin is None:
            raise RuntimeError("codex CLI not found in PATH")

        cmd = [
            codex_bin, "exec",
            "--json",
            "--dangerously-bypass-approvals-and-sandbox",
            "--skip-git-repo-check",
            "-c", 'model_reasoning_effort="high"',
            message,
        ]
        if config.cwd:
            cmd.extend(["-C", config.cwd])
        if config.disallowed_tools:
            import logging
            logging.getLogger(__name__).warning(
                "Codex does not support --disallowedTools; "
                "tool restrictions for agent will be prompt-only: %s",
                config.disallowed_tools,
            )
        return cmd, None

    def parse_event(self, data: dict[str, Any]) -> SDKEvent | None:
        # Codex has three line formats:
        # 1. Config line: {"sandbox": ..., "model": ...}  (no "id" key)
        # 2. Prompt line: {"prompt": "..."}
        # 3. Event line:  {"id": "0", "msg": {"type": "...", ...}}

        if "msg" not in data:
            # Config or prompt metadata line
            if "sandbox" in data or "model" in data:
                return SDKEvent("session.started", data)
            if "prompt" in data:
                return None  # Skip prompt echo
            return None

        msg = data["msg"]
        msg_type = msg.get("type", "")

        if msg_type == "task_started":
            return SDKEvent("session.started", {
                "model_context_window": msg.get("model_context_window"),
            })

        if msg_type == "agent_message":
            return SDKEvent("item.completed", {
                "item": {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "text", "text": msg.get("message", "")}],
                },
                "raw": data,
            })

        if msg_type == "patch_apply_begin":
            changes = msg.get("changes", {})
            return SDKEvent("item.completed", {
                "item": {
                    "type": "message",
                    "role": "assistant",
                    "content": [{
                        "type": "tool_use",
                        "name": "patch_apply",
                        "id": msg.get("call_id", ""),
                        "input": {"changes": changes},
                    }],
                },
                "raw": data,
            })

        if msg_type == "patch_apply_end":
            return SDKEvent("item.completed", {
                "item": {
                    "type": "message",
                    "role": "user",
                    "content": [{
                        "type": "tool_result",
                        "tool_use_id": msg.get("call_id", ""),
                        "content": msg.get("stdout", ""),
                    }],
                },
                "raw": data,
            })

        if msg_type == "exec_command_begin":
            return SDKEvent("item.completed", {
                "item": {
                    "type": "message",
                    "role": "assistant",
                    "content": [{
                        "type": "tool_use",
                        "name": "exec_command",
                        "id": msg.get("call_id", ""),
                        "input": {"command": msg.get("command", [])},
                    }],
                },
                "raw": data,
            })

        if msg_type == "exec_command_end":
            return SDKEvent("item.completed", {
                "item": {
                    "type": "message",
                    "role": "user",
                    "content": [{
                        "type": "tool_result",
                        "tool_use_id": msg.get("call_id", ""),
                        "content": msg.get("stdout", ""),
                    }],
                },
                "raw": data,
            })

        if msg_type == "token_count":
            info = msg.get("info", {})
            usage = info.get("total_token_usage", {})
            return SDKEvent("token_count", {"usage": usage, "raw": data})

        if msg_type == "turn_diff":
            return SDKEvent("turn_diff", {
                "unified_diff": msg.get("unified_diff", ""),
                "raw": data,
            })

        # Pass through unknown types
        return SDKEvent(msg_type, msg)


class OpenCodeAdapter(HarnessAdapter):
    """Adapter for ``opencode -p ... -f json -q``.

    OpenCode v0.0.55 does not stream NDJSON events.  Its ``-f json``
    flag emits a single ``{"response": "..."}`` object on stdout.
    The full conversation (tool calls, tool results, model info) is
    persisted in a SQLite database at ``{cwd}/.opencode/opencode.db``.

    Strategy:
    - ``parse_event`` handles the single stdout JSON line.
    - ``post_process_events`` reads the SQLite DB after the process
      exits and reconstructs the full trace as SDKEvent objects.
    """

    name = "opencode"
    SESSION_MARKER_PREFIX = "<!-- HELM_SESSION_MARKER:"
    SESSION_MARKER_SUFFIX = " -->"

    def build_command(
        self, message: str, config: SessionConfig
    ) -> tuple[list[str], dict[str, str] | None]:
        import shutil

        opencode_bin = shutil.which("opencode")
        if opencode_bin is None:
            raise RuntimeError("opencode CLI not found in PATH")

        prompt = message
        if config.session_marker:
            prompt = self._inject_session_marker(message, config.session_marker)

        cmd = [
            opencode_bin,
            "-p", prompt,
            "-f", "json",
            "-q",
        ]
        if config.cwd:
            cmd.extend(["-c", config.cwd])
        return cmd, None

    def parse_event(self, data: dict[str, Any]) -> SDKEvent | None:
        # OpenCode emits a single JSON object: {"response": "..."}
        if "response" in data:
            return SDKEvent("item.completed", {
                "item": {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "text", "text": data["response"]}],
                },
                "raw": data,
            })
        return None

    def post_process_events(self, config: SessionConfig) -> list[SDKEvent]:
        """Read OpenCode's SQLite DB and reconstruct the full trace."""
        import sqlite3

        cwd = config.cwd or "."
        db_path = Path(cwd) / ".opencode" / "opencode.db"
        if not db_path.exists():
            return []

        events: list[SDKEvent] = []

        try:
            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row

            row = self._find_session_row(conn, config.session_marker)
            if row is None:
                conn.close()
                return []

            session_id = row["id"]

            # Emit session.started
            events.append(SDKEvent("session.started", {
                "session_id": session_id,
                "backend": "opencode",
            }))

            # Read all messages for this session
            messages = conn.execute(
                "SELECT role, parts, model FROM messages "
                "WHERE session_id = ? ORDER BY created_at ASC",
                (session_id,),
            ).fetchall()

            for msg in messages:
                role = msg["role"]
                parts = json.loads(msg["parts"]) if msg["parts"] else []
                model = msg["model"]

                content: list[dict[str, Any]] = []
                for part in parts:
                    ptype = part.get("type")
                    pdata = part.get("data", {})

                    if ptype == "text":
                        text = pdata.get("text", "")
                        if role == "user" and config.session_marker:
                            text = self._strip_session_marker(text, config.session_marker)
                        content.append({
                            "type": "text",
                            "text": text,
                        })
                    elif ptype == "tool_call":
                        content.append({
                            "type": "tool_use",
                            "name": pdata.get("name", ""),
                            "id": pdata.get("id", ""),
                            "input": pdata.get("input", ""),
                        })
                    elif ptype == "tool_result":
                        content.append({
                            "type": "tool_result",
                            "tool_use_id": pdata.get("tool_call_id", ""),
                            "content": pdata.get("content", ""),
                            "is_error": pdata.get("is_error", False),
                        })
                    elif ptype == "finish":
                        # Skip finish markers — they're metadata
                        continue

                if not content:
                    continue

                event_role = role
                if role == "tool":
                    event_role = "user"  # Normalize to user/assistant

                events.append(SDKEvent("item.completed", {
                    "item": {
                        "type": "message",
                        "role": event_role,
                        "content": content,
                        "model": model,
                    },
                    "raw": {"role": role, "parts": parts},
                }))

            # Emit session.ended with usage info
            events.append(SDKEvent("session.ended", {
                "session_id": session_id,
                "usage": {
                    "prompt_tokens": row["prompt_tokens"],
                    "completion_tokens": row["completion_tokens"],
                },
                "cost_usd": row["cost"],
            }))

            conn.close()
        except Exception:
            # If DB read fails, fall through to synthetic session.ended
            pass

        return events

    def _find_session_row(
        self,
        conn: Any,
        session_marker: str | None,
    ) -> Any:
        """Find the session row for this run.

        OpenCode persists all sessions for a cwd in one SQLite DB. We inject a
        unique marker into the initial prompt so we can recover the exact
        session instead of guessing with "latest session wins".
        """
        if session_marker:
            marker = f"{self.SESSION_MARKER_PREFIX}{session_marker}"
            row = conn.execute(
                "SELECT DISTINCT s.id, s.prompt_tokens, s.completion_tokens, s.cost "
                "FROM sessions s "
                "JOIN messages m ON m.session_id = s.id "
                "WHERE m.role = 'user' AND m.parts LIKE ? "
                "ORDER BY s.created_at DESC LIMIT 1",
                (f"%{marker}%",),
            ).fetchone()
            if row is not None:
                return row

        return conn.execute(
            "SELECT id, prompt_tokens, completion_tokens, cost "
            "FROM sessions ORDER BY created_at DESC LIMIT 1"
        ).fetchone()

    @classmethod
    def _inject_session_marker(cls, message: str, session_marker: str) -> str:
        marker = f"{cls.SESSION_MARKER_PREFIX}{session_marker}{cls.SESSION_MARKER_SUFFIX}"
        return f"{marker}\n{message}"

    @classmethod
    def _strip_session_marker(cls, text: str, session_marker: str) -> str:
        marker = f"{cls.SESSION_MARKER_PREFIX}{session_marker}{cls.SESSION_MARKER_SUFFIX}"
        if text.startswith(marker):
            return text[len(marker):].lstrip("\n")
        return text


# Adapter registry — maps SDK agent IDs to adapters
_HARNESS_ADAPTERS: dict[str, type[HarnessAdapter]] = {
    "claude": ClaudeAdapter,
    "codex": CodexAdapter,
    "opencode": OpenCodeAdapter,
}


def get_harness_adapter(agent: str) -> HarnessAdapter:
    """Look up the adapter for a harness agent ID."""
    cls = _HARNESS_ADAPTERS.get(agent, ClaudeAdapter)
    return cls()


@dataclass
class _CLISession:
    """Internal state for a single agent CLI subprocess."""

    session_id: str
    config: SessionConfig
    adapter: HarnessAdapter = field(default_factory=ClaudeAdapter)
    process: asyncio.subprocess.Process | None = None
    started: bool = False


DIRECTCLI_STREAM_READER_LIMIT = 8 * 1024 * 1024


class DirectCLIClient:
    """Drop-in replacement for SDKClient that runs agent CLIs directly.

    Spawns one headless CLI process per agent session, using per-harness
    adapters to construct commands and parse NDJSON output.

    Supports: Claude (``claude -p``), Codex (``codex exec --json``),
    OpenCode (``opencode -p -f json -q``).
    Each harness handles its own auth — no SDK daemon needed.

    Lifecycle mapping::

        create_session → stores config + selects adapter (no subprocess yet)
        post_message   → first call spawns the CLI; subsequent calls error
        stream_events  → reads NDJSON from stdout, adapter parses to SDKEvent
        terminate      → sends SIGTERM to the subprocess
        reply_permission → no-op (permissions bypassed via CLI flags)
    """

    def __init__(self, config: SDKConfig | None = None):
        self._sessions: dict[str, _CLISession] = {}

    async def start(self) -> None:
        """No-op — no daemon to start."""

    async def dispose(self) -> None:
        """Terminate all running subprocess sessions."""
        for session in list(self._sessions.values()):
            await self._kill_process(session)
        self._sessions.clear()

    async def create_session(
        self,
        session_id: str,
        config: SessionConfig | None = None,
    ) -> dict[str, Any]:
        """Register a session.  The subprocess is spawned on ``post_message``."""
        config = config or SessionConfig()
        if not config.session_marker:
            config.session_marker = session_id
        adapter = get_harness_adapter(config.agent)
        self._sessions[session_id] = _CLISession(
            session_id=session_id,
            config=config,
            adapter=adapter,
        )
        return {
            "session_id": session_id,
            "acp_session_id": session_id,
            "agent_info": {"backend": "direct-cli", "adapter": adapter.name},
            "capabilities": {},
        }

    async def post_message(self, session_id: str, message: str) -> None:
        """Send a message by spawning the harness CLI.

        Only the first message per session actually launches the process.
        Subsequent calls raise because single-shot harnesses cannot accept
        follow-up nudges mid-run.
        """
        session = self._sessions.get(session_id)
        if session is None:
            raise RuntimeError(f"Unknown session: {session_id}")

        if session.started:
            raise FollowUpMessageUnsupportedError(
                f"Session {session_id} is already running; "
                "DirectCLI harnesses do not support follow-up messages."
            )

        import os

        cmd, env_overrides = session.adapter.build_command(message, session.config)

        # Strip nested-session env vars
        env = {
            k: v for k, v in os.environ.items()
            if k not in _CLAUDE_SESSION_VARS
        }
        if env_overrides:
            env.update(env_overrides)

        session.process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=session.config.cwd or None,
            env=env,
            limit=DIRECTCLI_STREAM_READER_LIMIT,
            start_new_session=True,
        )
        session.started = True

    def supports_follow_up_messages(self, session_id: str) -> bool:
        """Return whether a session can accept another prompt mid-run."""
        session = self._sessions.get(session_id)
        if session is None:
            return False
        return not session.started

    async def stream_events(
        self,
        session_id: str,
        signal: asyncio.Event | None = None,
        stream_timeout: float = 300.0,
    ) -> AsyncIterator[SDKEvent]:
        """Stream events from the CLI subprocess stdout.

        Reads NDJSON lines and uses the session's adapter to translate
        them into SDKEvent objects.
        """
        session = self._sessions.get(session_id)
        if session is None or session.process is None:
            return

        stdout = session.process.stdout
        if stdout is None:
            return

        got_session_ended = False

        while True:
            if signal and signal.is_set():
                break

            try:
                line = await asyncio.wait_for(
                    stdout.readline(), timeout=stream_timeout
                )
            except asyncio.TimeoutError:
                break
            except ValueError as exc:
                raise RuntimeError(
                    "DirectCLI stream line exceeded reader limit; "
                    "increase DIRECTCLI_STREAM_READER_LIMIT or reduce harness event size."
                ) from exc

            if not line:
                break  # EOF — process finished

            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue

            event = session.adapter.parse_event(data)
            if event is None:
                continue

            yield event

            if event.type == "session.ended":
                got_session_ended = True
                break

        # Let the adapter yield extra events reconstructed from
        # external sources (e.g. OpenCode's SQLite DB).
        if not got_session_ended and not (signal and signal.is_set()):
            for extra in session.adapter.post_process_events(session.config):
                yield extra
                if extra.type == "session.ended":
                    got_session_ended = True
                    break

        if not got_session_ended and not (signal and signal.is_set()):
            yield SDKEvent("session.ended", {"reason": "process_exit"})

    async def terminate_session(self, session_id: str) -> None:
        """Terminate the subprocess for a session."""
        session = self._sessions.pop(session_id, None)
        if session:
            await self._kill_process(session)

    async def reply_permission(
        self,
        session_id: str,
        permission_id: str,
        reply: str = "once",
    ) -> None:
        """No-op — permissions are bypassed via CLI flag."""

    async def reply_question(
        self,
        session_id: str,
        question_id: str,
        answer: str,
    ) -> None:
        """No-op — questions don't arise in headless mode."""

    async def reject_question(self, session_id: str, question_id: str) -> None:
        """No-op."""

    @staticmethod
    async def _kill_process(session: _CLISession) -> None:
        """Terminate a subprocess gracefully, then force-kill if needed."""
        proc = session.process
        if proc is None or proc.returncode is not None:
            return
        try:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                return
            try:
                await asyncio.wait_for(proc.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        except ProcessLookupError:
            pass  # Already exited
