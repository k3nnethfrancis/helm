from __future__ import annotations

import asyncio
from datetime import datetime

from helm.coordination.base import CoordinationMessage, DeliveryStatus, MessageType
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
        channel_id="persistent_peer_messages",
        channel_medium="filesystem",
        channel_persistence="persistent",
        channel_scope="mixed",
        channel_availability="always",
        observed_via="filesystem_poll",
        delivered=True,
        delivery_status=DeliveryStatus.DELIVERED,
        delivery_timestamp=datetime.now(),
        nudge_text="y" * 2200,
    )

    payload = msg.to_dict()
    assert payload["content"] == "x" * 1200
    assert payload["nudge_text"] == "y" * 2200
    assert payload["channel_id"] == "persistent_peer_messages"
    assert payload["channel_medium"] == "filesystem"
    assert payload["delivery_status"] == "delivered"


class _FakeSDK:
    def __init__(self, *, supports_follow_up: bool = True) -> None:
        self.supports_follow_up = supports_follow_up

    async def post_message(self, session_id: str, message: str) -> None:
        return None

    def supports_follow_up_messages(self, session_id: str) -> bool:
        return self.supports_follow_up


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


def test_is_complete_accepts_global_done_in_peer_mode(tmp_path) -> None:
    backend = FilesystemNudgeBackend()
    config = {
        "paths": {
            "base": "coordination/",
            "messages": "coordination/messages/",
            "signals": "coordination/signals/",
        },
    }

    asyncio.run(backend.setup(tmp_path, ["agent-a", "agent-b"], config))
    signals_dir = tmp_path / "coordination" / "signals"
    signals_dir.mkdir(parents=True, exist_ok=True)
    (signals_dir / "done").write_text("done\n")

    assert backend.is_complete(["agent-a", "agent-b"])


def test_is_complete_uses_base_signals_fallback_when_not_configured(tmp_path) -> None:
    backend = FilesystemNudgeBackend()
    config = {
        "paths": {
            "base": "coordination/",
            "messages": "coordination/messages/",
            # signals path intentionally omitted
        },
    }

    asyncio.run(backend.setup(tmp_path, ["agent-a"], config))
    signals_dir = tmp_path / "coordination" / "signals"
    signals_dir.mkdir(parents=True, exist_ok=True)
    (signals_dir / "done").write_text("done\n")

    assert backend.is_complete(["agent-a"])


def test_workspace_broadcast_not_marked_delivered_when_follow_up_messages_unsupported(
    tmp_path,
) -> None:
    async def _run() -> CoordinationMessage:
        backend = FilesystemNudgeBackend()
        config = {
            "paths": {
                "base": "coordination/",
                "messages": "coordination/messages/",
            },
            "channels": [
                {
                    "id": "workspace_artifacts",
                    "medium": "filesystem",
                    "persistence": "persistent",
                    "scope": "broadcast",
                    "availability": "always",
                    "paths": ["workspace/"],
                }
            ],
            "workspace_watches": ["*.txt"],
        }
        await backend.setup(tmp_path, ["agent-a", "agent-b"], config)
        backend._sdk = _FakeSDK(supports_follow_up=False)
        backend._agent_sessions = {
            "agent-a": "session-a",
            "agent-b": "session-b",
        }

        seen: list[CoordinationMessage] = []
        backend._on_message = seen.append

        artifact = tmp_path / "workspace" / "artifact.txt"
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_text("ready\n")

        await backend._handle_workspace_file(artifact, deliver_nudges=True)
        return seen[0]

    message = asyncio.run(_run())
    assert message.delivered is False
    assert message.delivery_status == DeliveryStatus.FAILED
    assert message.channel_id == "workspace_artifacts"
    assert message.channel_medium == "filesystem"
    assert message.channel_persistence == "persistent"
    assert message.channel_scope == "broadcast"
    assert message.observed_via == "workspace_watch"
    assert message.metadata["delivery_attempted_to"] == ["agent-a", "agent-b"]
    assert message.metadata["delivered_to"] == []
    assert message.metadata["delivery_failures"] == {
        "agent-a": "follow_up_messages_unsupported",
        "agent-b": "follow_up_messages_unsupported",
    }
