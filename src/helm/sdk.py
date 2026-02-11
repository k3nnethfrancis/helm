"""Python client for the Sandbox Agent SDK REST API.

Wraps the SDK daemon that provides a universal interface to coding agents.
The daemon is spawned as a subprocess and communicates via REST/SSE.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
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


class SDKEvent:
    """An event from the SDK event stream."""

    def __init__(self, event_type: str, data: dict[str, Any]):
        self.type = event_type
        self.data = data

    def __repr__(self) -> str:
        return f"SDKEvent({self.type!r}, {self.data!r})"


API_PREFIX = "/v1"


class SDKClient:
    """Python client for the Sandbox Agent SDK.

    Manages the SDK daemon lifecycle and provides methods for:
    - Session management (create, terminate)
    - Message posting
    - Event streaming (SSE)
    - Permission/question handling
    """

    def __init__(self, config: SDKConfig):
        self.config = config
        self._process: subprocess.Popen | None = None
        self._client: httpx.AsyncClient | None = None

    @property
    def base_url(self) -> str:
        return f"http://{self.config.host}:{self.config.port}"

    @property
    def api_url(self) -> str:
        return f"{self.base_url}{API_PREFIX}"

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

        self._process = subprocess.Popen(
            cmd,
            env={**os.environ},  # Inherit full environment for credentials
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

    async def create_session(
        self,
        session_id: str,
        config: SessionConfig | None = None,
    ) -> dict[str, Any]:
        """Create a new agent session."""
        if self._client is None:
            raise RuntimeError("Client not started")

        config = config or SessionConfig()
        payload: dict[str, Any] = {
            "agent": config.agent,
            "permissionMode": config.permission_mode,
        }
        if config.allowed_commands:
            payload["allowedCommands"] = config.allowed_commands
        if config.cwd:
            payload["cwd"] = config.cwd

        response = await self._client.post(
            f"{API_PREFIX}/sessions/{session_id}",
            json=payload,
        )
        response.raise_for_status()
        return response.json()

    async def terminate_session(self, session_id: str) -> None:
        """Terminate an agent session."""
        if self._client is None:
            raise RuntimeError("Client not started")

        try:
            response = await self._client.post(f"{API_PREFIX}/sessions/{session_id}/terminate")
            response.raise_for_status()
        except httpx.HTTPStatusError:
            pass  # Session may already be terminated

    async def post_message(self, session_id: str, message: str) -> None:
        """Send a message to an agent session."""
        if self._client is None:
            raise RuntimeError("Client not started")

        response = await self._client.post(
            f"{API_PREFIX}/sessions/{session_id}/messages",
            json={"message": message},
        )
        response.raise_for_status()

    async def stream_events(
        self,
        session_id: str,
        signal: asyncio.Event | None = None,
        stream_timeout: float = 300.0,
    ) -> AsyncIterator[SDKEvent]:
        """Stream events from an agent session via SSE.

        Yields SDKEvent objects for each event received.
        Stops when session.ended is received, signal is set, or
        stream_timeout seconds elapse with no data from the server.
        """
        if self._client is None:
            raise RuntimeError("Client not started")

        url = f"{self.api_url}/sessions/{session_id}/events/sse"

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

                        if sse.event == "message" and sse.data:
                            try:
                                data = json.loads(sse.data)
                                event = SDKEvent(data.get("type", "unknown"), data.get("data", {}))
                                yield event

                                if event.type == "session.ended":
                                    break
                            except json.JSONDecodeError:
                                continue
            except httpx.ReadTimeout:
                return  # Stream timed out — no data for stream_timeout seconds

    async def reply_permission(
        self,
        session_id: str,
        permission_id: str,
        reply: str = "once",
    ) -> None:
        """Reply to a permission request.

        Args:
            session_id: The session ID
            permission_id: The permission request ID
            reply: One of "once", "always", "deny"
        """
        if self._client is None:
            raise RuntimeError("Client not started")

        response = await self._client.post(
            f"{API_PREFIX}/sessions/{session_id}/permissions/{permission_id}/reply",
            json={"reply": reply},
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

        response = await self._client.post(
            f"{API_PREFIX}/sessions/{session_id}/questions/{question_id}/reply",
            json={"answer": answer},
        )
        response.raise_for_status()

    async def reject_question(self, session_id: str, question_id: str) -> None:
        """Reject a question from the agent."""
        if self._client is None:
            raise RuntimeError("Client not started")

        response = await self._client.post(
            f"{API_PREFIX}/sessions/{session_id}/questions/{question_id}/reject",
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


@asynccontextmanager
async def sdk_client(config: SDKConfig) -> AsyncIterator[SDKClient]:
    """Context manager for SDK client lifecycle."""
    client = SDKClient(config)
    try:
        await client.start()
        yield client
    finally:
        await client.dispose()
