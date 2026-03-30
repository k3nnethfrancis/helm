from __future__ import annotations

import asyncio
import json
import sqlite3

from helm.adapters import (
    DIRECTCLI_STREAM_READER_LIMIT,
    DirectCLIClient,
    FollowUpMessageUnsupportedError,
    OpenCodeAdapter,
    SessionConfig,
)


def test_direct_cli_rejects_follow_up_messages(monkeypatch) -> None:
    class _DummyProcess:
        stdout = None
        stderr = None
        returncode = None

        def terminate(self) -> None:
            return None

        async def wait(self) -> None:
            return None

    async def _fake_create_subprocess_exec(*args, **kwargs):  # type: ignore[no-untyped-def]
        return _DummyProcess()

    async def _run() -> None:
        client = DirectCLIClient()
        await client.create_session("session-1", SessionConfig(agent="claude"))
        session = client._sessions["session-1"]
        monkeypatch.setattr(session.adapter, "build_command", lambda message, config: (["echo"], None))
        monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_create_subprocess_exec)

        assert client.supports_follow_up_messages("session-1") is True
        await client.post_message("session-1", "first")
        assert client.supports_follow_up_messages("session-1") is False

        try:
            await client.post_message("session-1", "second")
        except FollowUpMessageUnsupportedError:
            return
        raise AssertionError("expected FollowUpMessageUnsupportedError")

    asyncio.run(_run())


def test_direct_cli_uses_large_stream_reader_limit(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class _DummyProcess:
        stdout = None
        stderr = None
        returncode = None

        def terminate(self) -> None:
            return None

        async def wait(self) -> None:
            return None

    async def _fake_create_subprocess_exec(*args, **kwargs):  # type: ignore[no-untyped-def]
        captured["limit"] = kwargs.get("limit")
        captured["start_new_session"] = kwargs.get("start_new_session")
        return _DummyProcess()

    async def _run() -> None:
        client = DirectCLIClient()
        await client.create_session("session-1", SessionConfig(agent="claude"))
        session = client._sessions["session-1"]
        monkeypatch.setattr(session.adapter, "build_command", lambda message, config: (["echo"], None))
        monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_create_subprocess_exec)
        await client.post_message("session-1", "first")

    asyncio.run(_run())
    assert captured["limit"] == DIRECTCLI_STREAM_READER_LIMIT
    assert captured["start_new_session"] is True


def test_direct_cli_kills_process_group(monkeypatch) -> None:
    events: list[tuple[int, int]] = []

    class _DummyProcess:
        pid = 4242
        returncode = None

        async def wait(self) -> None:
            return None

    class _DummySession:
        process = _DummyProcess()

    monkeypatch.setattr("helm.adapters.direct_cli.os.killpg", lambda pid, sig: events.append((pid, sig)))

    asyncio.run(DirectCLIClient._kill_process(_DummySession()))  # type: ignore[arg-type]

    assert len(events) == 1


def test_opencode_adapter_uses_session_marker_to_select_correct_session(tmp_path) -> None:
    db_dir = tmp_path / ".opencode"
    db_dir.mkdir(parents=True)
    db_path = db_dir / "opencode.db"

    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE sessions ("
        "id TEXT PRIMARY KEY, parent_session_id TEXT, title TEXT NOT NULL, "
        "message_count INTEGER NOT NULL DEFAULT 0, prompt_tokens INTEGER NOT NULL DEFAULT 0, "
        "completion_tokens INTEGER NOT NULL DEFAULT 0, cost REAL NOT NULL DEFAULT 0.0, "
        "updated_at INTEGER NOT NULL, created_at INTEGER NOT NULL, summary_message_id TEXT)"
    )
    conn.execute(
        "CREATE TABLE messages ("
        "id TEXT PRIMARY KEY, session_id TEXT NOT NULL, role TEXT NOT NULL, "
        "parts TEXT NOT NULL default '[]', model TEXT, created_at INTEGER NOT NULL, "
        "updated_at INTEGER NOT NULL, finished_at INTEGER)"
    )

    adapter = OpenCodeAdapter()
    marker = "helm-session-a"

    conn.execute(
        "INSERT INTO sessions (id, title, prompt_tokens, completion_tokens, cost, updated_at, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("session-a", "match", 11, 22, 0.5, 1000, 1000),
    )
    conn.execute(
        "INSERT INTO messages (id, session_id, role, parts, model, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            "msg-a1",
            "session-a",
            "user",
            json.dumps([
                {
                    "type": "text",
                    "data": {
                        "text": adapter._inject_session_marker("Solve task", marker),
                    },
                }
            ]),
            "opencode-model",
            1000,
            1000,
        ),
    )
    conn.execute(
        "INSERT INTO messages (id, session_id, role, parts, model, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            "msg-a2",
            "session-a",
            "assistant",
            json.dumps([
                {"type": "text", "data": {"text": "Matched session output"}},
                {"type": "finish", "data": {"reason": "end_turn"}},
            ]),
            "opencode-model",
            1001,
            1001,
        ),
    )

    conn.execute(
        "INSERT INTO sessions (id, title, prompt_tokens, completion_tokens, cost, updated_at, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("session-b", "latest", 99, 88, 1.25, 2000, 2000),
    )
    conn.execute(
        "INSERT INTO messages (id, session_id, role, parts, model, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            "msg-b1",
            "session-b",
            "user",
            json.dumps([
                {"type": "text", "data": {"text": "Different prompt"}},
            ]),
            "opencode-model",
            2000,
            2000,
        ),
    )
    conn.commit()
    conn.close()

    events = adapter.post_process_events(
        SessionConfig(
            agent="opencode",
            cwd=str(tmp_path),
            session_marker=marker,
        )
    )

    assert events[0].type == "session.started"
    assert events[0].data["session_id"] == "session-a"
    user_event = next(
        event for event in events
        if event.type == "item.completed"
        and event.data["item"]["role"] == "user"
    )
    assert user_event.data["item"]["content"][0]["text"] == "Solve task"
    assistant_event = next(
        event for event in events
        if event.type == "item.completed"
        and event.data["item"]["role"] == "assistant"
    )
    assert assistant_event.data["item"]["content"][0]["text"] == "Matched session output"
    assert events[-1].type == "session.ended"
    assert events[-1].data["session_id"] == "session-a"
