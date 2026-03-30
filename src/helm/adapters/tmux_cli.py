"""TmuxCLIClient -- runs agent CLIs in persistent tmux sessions.

Each agent runs interactive ``claude`` inside a tmux pane. Messages
are injected via ``tmux load-buffer`` + ``paste-buffer``. This gives
push delivery — the broker can inject messages into running sessions
without the agent needing to poll.

The TUI bypass-permissions prompt is navigated automatically.
Events are not streamed from interactive mode (no clean NDJSON).
Instead, the experiment runner tracks completion via the broker's
done signal and coordination messages.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shlex
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncIterator

from helm.adapters.base import (
    HarnessAdapter,
    SDKConfig,
    SDKEvent,
    SessionConfig,
)
from helm.adapters.direct_cli import get_harness_adapter

logger = logging.getLogger(__name__)

TMUX_WIDTH = "220"
TMUX_HEIGHT = "50"


@dataclass
class _TmuxSession:
    """Internal state for a single tmux-managed agent session."""

    session_id: str
    config: SessionConfig
    adapter: HarnessAdapter
    tmux_name: str
    started: bool = False
    message_count: int = 0
    _stop: bool = False


class TmuxCLIClient:
    """Agent client using persistent interactive tmux sessions.

    Each agent gets its own tmux session running interactive ``claude``
    with ``--permission-mode bypassPermissions`` and ``--mcp-config``.
    Messages are injected via tmux paste-buffer for push delivery.

    Lifecycle::

        create_session  -> stores config (no tmux yet)
        post_message    -> first: spawns tmux + claude + accepts perms dialog
                        -> subsequent: injects message via paste-buffer
        stream_events   -> yields synthetic events based on session state
        terminate       -> tmux kill-session
    """

    def __init__(self, config: SDKConfig | None = None):
        self._sessions: dict[str, _TmuxSession] = {}

        if not self._tmux_available():
            raise RuntimeError(
                "tmux not found in PATH. Install tmux for push message delivery. "
                "On macOS: brew install tmux"
            )

    @staticmethod
    def _tmux_available() -> bool:
        try:
            subprocess.run(["tmux", "-V"], capture_output=True, timeout=5)
            return True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    async def start(self) -> None:
        """No-op."""

    async def dispose(self) -> None:
        """Kill all helm-prefixed tmux sessions."""
        for session in list(self._sessions.values()):
            self._kill_tmux(session.tmux_name)
        self._sessions.clear()

    async def create_session(
        self,
        session_id: str,
        config: SessionConfig | None = None,
    ) -> dict[str, Any]:
        """Register a session. Tmux is spawned on first post_message."""
        config = config or SessionConfig()
        if not config.session_marker:
            config.session_marker = session_id
        adapter = get_harness_adapter(config.agent)

        # Sanitize tmux name
        safe_id = session_id.replace("/", "-").replace(".", "-")
        tmux_name = f"helm-{safe_id}"
        if len(tmux_name) > 80:
            tmux_name = tmux_name[:80]

        self._sessions[session_id] = _TmuxSession(
            session_id=session_id,
            config=config,
            adapter=adapter,
            tmux_name=tmux_name,
        )

        return {
            "session_id": session_id,
            "acp_session_id": session_id,
            "agent_info": {"backend": "tmux-cli", "adapter": adapter.name},
            "capabilities": {"follow_up_messages": True},
        }

    async def post_message(self, session_id: str, message: str) -> None:
        """Send a message to an agent session.

        First call spawns the tmux session and claude, navigates the
        bypass permissions prompt, then sends the message.
        Subsequent calls inject messages via paste-buffer.
        """
        session = self._sessions.get(session_id)
        if session is None:
            raise RuntimeError(f"Unknown session: {session_id}")

        if not session.started:
            await self._start_tmux_session(session, message)
        else:
            await self._inject_message(session, message)

    async def _start_tmux_session(
        self, session: _TmuxSession, first_message: str
    ) -> None:
        """Spawn tmux, start claude, navigate perms dialog, send first message."""
        import shutil

        claude_bin = shutil.which("claude")
        if not claude_bin:
            raise RuntimeError("claude CLI not found in PATH")

        # 1. Create tmux session
        subprocess.run(
            ["tmux", "new-session", "-d", "-s", session.tmux_name,
             "-x", TMUX_WIDTH, "-y", TMUX_HEIGHT],
            check=True,
            capture_output=True,
        )

        # 2. Build claude command
        cmd_parts = [claude_bin, "--permission-mode", "bypassPermissions"]
        if session.config.mcp_config_path:
            cmd_parts.extend(["--mcp-config", session.config.mcp_config_path])
        if session.config.model:
            cmd_parts.extend(["--model", session.config.model])
        if session.config.disallowed_tools:
            cmd_parts.extend([
                "--disallowedTools",
                ",".join(session.config.disallowed_tools),
            ])

        cmd_str = " ".join(shlex.quote(p) for p in cmd_parts)

        # 3. Send claude command to tmux
        subprocess.run(
            ["tmux", "send-keys", "-t", session.tmux_name, cmd_str, "Enter"],
            check=True,
            capture_output=True,
        )

        # 4. Wait for and navigate the bypass permissions dialog
        await self._navigate_bypass_dialog(session)

        # 5. Wait for claude to be fully ready
        await asyncio.sleep(3)

        # 6. Send first message
        session.started = True
        await self._inject_message(session, first_message)

        logger.info(
            "Started tmux session %s for %s",
            session.tmux_name,
            session.session_id,
        )

    async def _navigate_bypass_dialog(self, session: _TmuxSession) -> None:
        """Wait for and accept the bypass permissions confirmation dialog."""
        for attempt in range(20):  # Up to 10 seconds
            await asyncio.sleep(0.5)
            pane = self._capture_pane(session.tmux_name)
            if "Yes, I accept" in pane:
                # Navigate to "Yes, I accept" and press Enter
                subprocess.run(
                    ["tmux", "send-keys", "-t", session.tmux_name, "Down"],
                    capture_output=True,
                )
                await asyncio.sleep(0.3)
                subprocess.run(
                    ["tmux", "send-keys", "-t", session.tmux_name, "Enter"],
                    capture_output=True,
                )
                logger.debug(
                    "Accepted bypass permissions for %s", session.tmux_name
                )
                return
            if "❯" in pane and "Yes, I accept" not in pane and "WARNING" not in pane:
                # Already past the dialog
                return

        logger.warning(
            "Bypass dialog not found for %s, proceeding anyway",
            session.tmux_name,
        )

    async def _inject_message(
        self, session: _TmuxSession, message: str
    ) -> None:
        """Inject a message into a running tmux session via paste-buffer."""
        fd, tmp_name = tempfile.mkstemp(
            prefix=f"helm_msg_{session.session_id[-8:]}_",
            suffix=".txt",
        )
        tmp_path = Path(tmp_name)
        try:
            with os.fdopen(fd, "w") as handle:
                handle.write(message)
            buf_name = f"helm_{session.session_id[-8:]}"

            subprocess.run(
                ["tmux", "load-buffer", "-b", buf_name, str(tmp_path)],
                check=True,
                capture_output=True,
            )
            subprocess.run(
                ["tmux", "paste-buffer", "-b", buf_name,
                 "-t", session.tmux_name],
                check=True,
                capture_output=True,
            )
            subprocess.run(
                ["tmux", "send-keys", "-t", session.tmux_name, "Enter"],
                check=True,
                capture_output=True,
            )

            session.message_count += 1
            logger.debug(
                "Injected message #%d (%d chars) into %s",
                session.message_count,
                len(message),
                session.tmux_name,
            )
        finally:
            tmp_path.unlink(missing_ok=True)

    def supports_follow_up_messages(self, session_id: str) -> bool:
        """Tmux sessions always support follow-up messages."""
        session = self._sessions.get(session_id)
        if session is None:
            return False
        return session.started

    async def stream_events(
        self,
        session_id: str,
        signal: asyncio.Event | None = None,
        stream_timeout: float = 300.0,
    ) -> AsyncIterator[SDKEvent]:
        """Yield events by monitoring the tmux session.

        Interactive claude doesn't produce NDJSON to stdout, so we
        monitor the tmux pane for completion signals and yield
        synthetic events.
        """
        session = self._sessions.get(session_id)
        if session is None:
            return

        # Yield a synthetic session.started
        yield SDKEvent("session.started", {"tmux_session": session.tmux_name})

        # Monitor until session ends or stop signal
        idle = 0.0
        while not session._stop:
            if signal and signal.is_set():
                break

            await asyncio.sleep(1.0)
            idle += 1.0

            if idle >= stream_timeout:
                break

            # Check if tmux session still exists
            if idle > 5.0 and idle % 10.0 < 1.5:
                if not self._tmux_session_exists(session.tmux_name):
                    break

        yield SDKEvent("session.ended", {"reason": "tmux_session_ended"})

    async def terminate_session(self, session_id: str) -> None:
        """Kill the tmux session."""
        session = self._sessions.pop(session_id, None)
        if session:
            session._stop = True
            self._kill_tmux(session.tmux_name)

    async def reply_permission(
        self, session_id: str, permission_id: str, reply: str = "once"
    ) -> None:
        """No-op."""

    async def reply_question(
        self, session_id: str, question_id: str, answer: str
    ) -> None:
        """No-op."""

    async def reject_question(self, session_id: str, question_id: str) -> None:
        """No-op."""

    # ── Internal helpers ──

    @staticmethod
    def _capture_pane(tmux_name: str) -> str:
        """Capture the visible content of a tmux pane."""
        result = subprocess.run(
            ["tmux", "capture-pane", "-t", tmux_name, "-p", "-S", "-50"],
            capture_output=True,
            text=True,
        )
        return result.stdout if result.returncode == 0 else ""

    @staticmethod
    def _kill_tmux(tmux_name: str) -> None:
        """Kill a tmux session by name."""
        try:
            subprocess.run(
                ["tmux", "kill-session", "-t", tmux_name],
                capture_output=True,
                timeout=5,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

    @staticmethod
    def _tmux_session_exists(tmux_name: str) -> bool:
        """Check if a tmux session exists."""
        result = subprocess.run(
            ["tmux", "has-session", "-t", tmux_name],
            capture_output=True,
        )
        return result.returncode == 0
