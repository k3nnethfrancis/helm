from __future__ import annotations

import asyncio
from datetime import datetime

from helm.coordination.base import CoordinationMessage, MessageType
from helm.coordination.filesystem_nudge import FilesystemNudgeBackend


def test_find_hub_uses_role_metadata_not_agent_order(tmp_path) -> None:
    backend = FilesystemNudgeBackend()

    config = {
        "paths": {
            "base": "coordination/",
            "tasks": "coordination/tasks/",
            "signals": "coordination/signals/",
        },
        "agent_roles": {
            "worker-a": "worker",
            "coordinator": "hub",
        },
        "hub_agent_id": "coordinator",
    }

    # Intentionally put worker first to verify we do not rely on list order.
    asyncio.run(backend.setup(tmp_path, ["worker-a", "coordinator"], config))

    assert backend._find_hub() == "coordinator"


def test_coordination_message_to_dict_is_lossless() -> None:
    msg = CoordinationMessage(
        timestamp=datetime.now(),
        sender="researcher",
        recipient="implementer",
        message_type=MessageType.PEER_MESSAGE,
        content="x" * 1200,
        source_path="messages/long.md",
        delivered=True,
        delivery_timestamp=datetime.now(),
        nudge_text="y" * 2200,
    )

    payload = msg.to_dict()
    assert payload["content"] == "x" * 1200
    assert payload["nudge_text"] == "y" * 2200


class _FakeSDK:
    async def post_message(self, session_id: str, message: str) -> None:
        return None


def test_stop_watching_flushes_last_coordination_files(tmp_path) -> None:
    async def _run() -> list[CoordinationMessage]:
        backend = FilesystemNudgeBackend(poll_interval=5.0)
        config = {
            "paths": {
                "base": "coordination/",
                "messages": "coordination/messages/",
                "signals": "coordination/signals/",
            },
        }
        await backend.setup(tmp_path, ["researcher", "implementer"], config)

        seen: list[CoordinationMessage] = []
        await backend.start_watching(
            _FakeSDK(),
            {
                "researcher": "session-researcher",
                "implementer": "session-implementer",
            },
            on_message=seen.append,
        )

        # Create a coordination file after watcher start; final flush in
        # stop_watching() should still capture it.
        signal = tmp_path / "coordination" / "signals" / "implementer.done"
        signal.parent.mkdir(parents=True, exist_ok=True)
        signal.write_text("done\n")
        message = tmp_path / "coordination" / "messages" / "001-researcher-all.md"
        message.parent.mkdir(parents=True, exist_ok=True)
        message.write_text("m" * 700)

        await backend.stop_watching()
        return seen

    messages = asyncio.run(_run())
    assert any(m.source_path == "signals/implementer.done" for m in messages)
    long_msg = next(m for m in messages if m.source_path == "messages/001-researcher-all.md")
    assert len(long_msg.content) == 700
