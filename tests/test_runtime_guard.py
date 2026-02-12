from __future__ import annotations

import asyncio

from helm.config import OrchestratorAction, OrchestratorConfig, OrchestratorRule
from helm.runtime_guard import RuntimeGuard
from helm.sdk import SDKEvent


class DummySDK:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []
        self.permissions: list[tuple[str, str, str]] = []

    async def post_message(self, session_id: str, message: str) -> None:
        self.messages.append((session_id, message))

    async def reply_permission(self, session_id: str, permission_id: str, reply: str) -> None:
        self.permissions.append((session_id, permission_id, reply))


def _event(event_type: str, **data: str) -> SDKEvent:
    return SDKEvent(event_type, data)


def test_from_worker_rule_only_matches_workers() -> None:
    rule = OrchestratorRule(
        on="question.requested",
        from_agent="worker",
        then=OrchestratorAction.LOG,
    )
    orchestrator = RuntimeGuard(OrchestratorConfig(rules=[rule]), DummySDK())
    orchestrator.register_agent("coordinator", "s-hub", role="hub")
    orchestrator.register_agent("worker-a", "s-worker", role="worker")

    event = _event("question.requested", prompt="help")

    assert orchestrator._matches_rule(rule, event, "worker-a")
    assert not orchestrator._matches_rule(rule, event, "coordinator")


def test_from_coordinator_rule_only_matches_hub() -> None:
    rule = OrchestratorRule(
        on="question.requested",
        from_agent="coordinator",
        then=OrchestratorAction.ESCALATE_TO_HUMAN,
    )
    orchestrator = RuntimeGuard(OrchestratorConfig(rules=[rule]), DummySDK())
    orchestrator.register_agent("orchestrator", "s-hub", role="hub")
    orchestrator.register_agent("worker-a", "s-worker", role="worker")

    event = _event("question.requested", prompt="help")

    assert orchestrator._matches_rule(rule, event, "orchestrator")
    assert not orchestrator._matches_rule(rule, event, "worker-a")


def test_or_condition_matches_second_clause() -> None:
    rule = OrchestratorRule(
        on="permission.requested",
        if_condition='action contains "curl" or action contains "wget"',
        then=OrchestratorAction.ESCALATE,
    )
    orchestrator = RuntimeGuard(OrchestratorConfig(rules=[rule]), DummySDK())
    orchestrator.register_agent("peer", "s-peer", role="peer")

    assert orchestrator._matches_rule(
        rule,
        _event("permission.requested", action="wget https://example.com"),
        "peer",
    )
    assert not orchestrator._matches_rule(
        rule,
        _event("permission.requested", action="echo hi"),
        "peer",
    )


def test_nudge_coordinator_targets_hub_session() -> None:
    rule = OrchestratorRule(
        on="no_activity",
        then=OrchestratorAction.NUDGE_COORDINATOR,
        message="check status",
    )
    sdk = DummySDK()
    orchestrator = RuntimeGuard(OrchestratorConfig(rules=[rule]), sdk)
    orchestrator.register_agent("orchestrator", "s-hub", role="hub")
    orchestrator.register_agent("worker-a", "s-worker", role="worker")

    worker_state = orchestrator.get_agent_by_session("s-worker")
    assert worker_state is not None

    asyncio.run(orchestrator._apply_rule(rule, _event("no_activity"), worker_state))

    assert sdk.messages == [("s-hub", "check status")]
