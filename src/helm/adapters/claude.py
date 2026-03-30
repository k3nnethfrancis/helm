"""Claude Code harness adapter."""

from __future__ import annotations

from typing import Any

from helm.adapters.base import HarnessAdapter, SDKEvent, SessionConfig


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
        if config.model:
            cmd.extend(["--model", config.model])
        if config.mcp_config_path:
            cmd.extend(["--mcp-config", config.mcp_config_path])
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
