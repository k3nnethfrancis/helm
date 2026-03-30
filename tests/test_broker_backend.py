from __future__ import annotations

import asyncio
import json
import urllib.error
import urllib.request
from pathlib import Path

from helm.coordination.broker import BrokerState, HelmBroker, Message
from helm.coordination.broker_backend import BrokerBackend


def _post_json(url: str, payload: dict) -> dict:
    data = json.dumps(payload).encode()
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return json.loads(exc.read())


def _get_json(url: str) -> dict:
    request = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(request, timeout=5) as response:
        return json.loads(response.read())


def test_broker_state_denies_unknown_senders_when_mechanical_enforcement_enabled() -> None:
    state = BrokerState(
        topology_rules={"coordinator": ["worker"]},
        enforce_topology=True,
    )

    allowed, reason = state.can_message("coordinator", "worker")
    assert allowed is True
    assert reason == ""

    allowed, reason = state.can_message("worker", "coordinator")
    assert allowed is False
    assert "No topology rules registered for worker" in reason


def test_broker_backend_uses_agent_policies_for_topology_and_capabilities(tmp_path: Path) -> None:
    async def _run() -> None:
        backend = BrokerBackend()
        config = {
            "experiment_id": "exp-1",
            "delivery": "poll",
            "enforcement": "mechanical",
            "agent_policies": {
                "delegator": {
                    "role": "hub",
                    "can_spawn": True,
                    "can_signal_done": True,
                    "can_message": ["worker_a"],
                },
                "worker_a": {
                    "role": "worker",
                    "can_spawn": False,
                    "can_signal_done": False,
                    "can_message": ["delegator"],
                },
            },
        }

        await backend.setup(tmp_path, ["delegator", "worker_a"], config)
        assert backend._broker is not None
        assert backend._broker.state.topology_rules == {
            "delegator": ["worker_a"],
            "worker_a": ["delegator"],
        }

        delegator_config = json.loads((tmp_path / "mcp-configs" / "delegator.json").read_text())
        worker_config = json.loads((tmp_path / "mcp-configs" / "worker_a.json").read_text())

        delegator_env = delegator_config["mcpServers"]["helm-messaging"]["env"]
        worker_env = worker_config["mcpServers"]["helm-messaging"]["env"]

        assert delegator_env["HELM_CAN_SPAWN"] == "true"
        assert delegator_env["HELM_CAN_SIGNAL_DONE"] == "true"
        assert delegator_env["HELM_AGENT_ROLE"] == "hub"
        assert worker_env["HELM_CAN_SPAWN"] == "false"
        assert worker_env["HELM_CAN_SIGNAL_DONE"] == "false"
        assert worker_env["HELM_AGENT_ROLE"] == "worker"

        await backend.teardown()

    asyncio.run(_run())


def test_broker_update_topology_endpoint_supports_parent_child_spawn() -> None:
    async def _run() -> None:
        broker = HelmBroker()
        broker.configure_topology({"parent": []}, enforce=True)
        port = await broker.start()
        base_url = f"http://127.0.0.1:{port}"

        try:
            _post_json(
                f"{base_url}/register",
                {"agent_id": "parent", "experiment_id": "exp-1", "role": "hub"},
            )
            _post_json(
                f"{base_url}/register",
                {"agent_id": "child", "experiment_id": "exp-1", "role": "worker"},
            )
            _post_json(
                f"{base_url}/register",
                {"agent_id": "other", "experiment_id": "exp-1", "role": "worker"},
            )

            blocked = _post_json(
                f"{base_url}/send",
                {"from_id": "parent", "to_id": "child", "content": "before"},
            )
            assert blocked["topology_violation"] is True

            _post_json(
                f"{base_url}/update_topology",
                {"agent_id": "parent", "allowed_recipients": ["child"]},
            )
            _post_json(
                f"{base_url}/update_topology",
                {"agent_id": "child", "allowed_recipients": ["parent"]},
            )

            parent_to_child = _post_json(
                f"{base_url}/send",
                {"from_id": "parent", "to_id": "child", "content": "hello"},
            )
            child_to_parent = _post_json(
                f"{base_url}/send",
                {"from_id": "child", "to_id": "parent", "content": "done"},
            )
            child_to_other = _post_json(
                f"{base_url}/send",
                {"from_id": "child", "to_id": "other", "content": "nope"},
            )

            assert parent_to_child["ok"] is True
            assert child_to_parent["ok"] is True
            assert child_to_other["topology_violation"] is True

            peers = _get_json(f"{base_url}/peers/parent")
            assert peers["peers"] == [{"id": "child", "role": "worker"}]
        finally:
            await broker.stop()

    asyncio.run(_run())


def test_broker_backend_schedules_push_on_captured_loop() -> None:
    backend = BrokerBackend()
    scheduled: dict[str, object] = {}

    class _FakeLoop:
        def call_soon_threadsafe(self, callback, *args) -> None:  # type: ignore[no-untyped-def]
            scheduled["callback"] = callback
            scheduled["args"] = args

    async def _push(agent_id: str, content: str) -> None:
        return None

    backend._loop = _FakeLoop()  # type: ignore[assignment]
    backend._push_callback = _push
    backend._agent_sessions = {"worker": "session-1"}

    backend._on_broker_message(
        Message(
            id=1,
            from_id="parent",
            to_id="worker",
            content="hello",
            timestamp=0.0,
        )
    )

    assert scheduled["callback"] == backend._schedule_push_message
    assert scheduled["args"] == ("worker", "[Message from parent]:\nhello")
