"""Data types, constants, and base adapter class for Helm SDK adapters."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


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

DIRECTCLI_STREAM_READER_LIMIT = 8 * 1024 * 1024


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
