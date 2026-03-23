"""OpenCode harness adapter."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from helm.adapters.base import HarnessAdapter, SDKEvent, SessionConfig


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
                        # Skip finish markers -- they're metadata
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
