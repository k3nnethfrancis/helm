"""DirectCLIClient -- runs agent CLI subprocesses instead of the SDK daemon."""

from __future__ import annotations

import asyncio
import json
import os
import signal
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

from helm.adapters.base import (
    DIRECTCLI_STREAM_READER_LIMIT,
    FollowUpMessageUnsupportedError,
    HarnessAdapter,
    SDKConfig,
    SDKEvent,
    SessionConfig,
    _CLAUDE_SESSION_VARS,
)
from helm.adapters.claude import ClaudeAdapter


def get_harness_adapter(agent: str) -> HarnessAdapter:
    """Look up the adapter for a harness agent ID."""
    # Import here to access the populated registry
    from helm.adapters import _HARNESS_ADAPTERS

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


class DirectCLIClient:
    """Drop-in replacement for SDKClient that runs agent CLIs directly.

    Spawns one headless CLI process per agent session, using per-harness
    adapters to construct commands and parse NDJSON output.

    Supports: Claude (``claude -p``), Codex (``codex exec --json``),
    OpenCode (``opencode -p -f json -q``).
    Each harness handles its own auth -- no SDK daemon needed.

    Lifecycle mapping::

        create_session -> stores config + selects adapter (no subprocess yet)
        post_message   -> first call spawns the CLI; subsequent calls error
        stream_events  -> reads NDJSON from stdout, adapter parses to SDKEvent
        terminate      -> sends SIGTERM to the subprocess
        reply_permission -> no-op (permissions bypassed via CLI flags)
    """

    def __init__(self, config: SDKConfig | None = None):
        self._sessions: dict[str, _CLISession] = {}

    async def start(self) -> None:
        """No-op -- no daemon to start."""

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
                break  # EOF -- process finished

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
        """No-op -- permissions are bypassed via CLI flag."""

    async def reply_question(
        self,
        session_id: str,
        question_id: str,
        answer: str,
    ) -> None:
        """No-op -- questions don't arise in headless mode."""

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
