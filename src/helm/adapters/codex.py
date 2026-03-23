"""Codex harness adapter."""

from __future__ import annotations

from typing import Any

from helm.adapters.base import HarnessAdapter, SDKEvent, SessionConfig


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
