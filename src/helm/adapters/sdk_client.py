"""SDKClient -- ACP daemon client for the Sandbox Agent SDK."""

from __future__ import annotations

import asyncio
import json
import subprocess
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

import httpx
from httpx_sse import aconnect_sse

from helm.adapters.base import (
    API_PREFIX,
    SDKConfig,
    SDKEvent,
    SessionConfig,
    _CLAUDE_SESSION_VARS,
)


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
                return  # Stream timed out -- no data for stream_timeout seconds

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
