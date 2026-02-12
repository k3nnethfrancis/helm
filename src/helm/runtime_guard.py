"""Rule-based runtime guard for multi-agent experiments.

Monitors agent activity, matches events against rules, and intervenes
when configured conditions are met.
"""

from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

from helm.config import OrchestratorAction, OrchestratorConfig, OrchestratorRule
from helm.sdk import SDKClient, SDKEvent


@dataclass
class InterventionLog:
    """Record of a runtime-guard intervention."""

    timestamp: datetime
    rule: OrchestratorRule
    event: SDKEvent | None
    agent_id: str
    action_taken: OrchestratorAction
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentState:
    """Tracked state for an agent."""

    agent_id: str
    session_id: str
    role: str | None = None
    last_activity: float = field(default_factory=time.time)
    turn_count: int = 0
    is_active: bool = True


class RuntimeGuard:
    """Monitors agents and applies rule-based interventions.

    The runtime guard:
    1. Watches event streams from all agents
    2. Matches events against configured rules
    3. Takes action (approve, reject, escalate, nudge)
    4. Logs all interventions for analysis
    """

    def __init__(
        self,
        config: OrchestratorConfig,
        sdk: SDKClient,
        on_escalate: Callable[[str, SDKEvent, OrchestratorRule], None] | None = None,
    ):
        self.config = config
        self.sdk = sdk
        self.on_escalate = on_escalate

        self._agents: dict[str, AgentState] = {}
        self._interventions: list[InterventionLog] = []
        self._stop_event = asyncio.Event()
        self._inactivity_tasks: dict[str, asyncio.Task] = {}

    def register_agent(
        self,
        agent_id: str,
        session_id: str,
        role: str | None = None,
    ) -> None:
        """Register an agent for monitoring."""
        self._agents[agent_id] = AgentState(
            agent_id=agent_id,
            session_id=session_id,
            role=role,
        )

    def get_agent_by_session(self, session_id: str) -> AgentState | None:
        """Get agent state by session ID."""
        for agent in self._agents.values():
            if agent.session_id == session_id:
                return agent
        return None

    async def handle_event(self, session_id: str, event: SDKEvent) -> bool:
        """Handle an event from an agent session.

        Returns True if the event was handled (intervention applied),
        False if no intervention was needed.
        """
        agent = self.get_agent_by_session(session_id)
        if agent is None:
            return False

        # Update activity tracking
        agent.last_activity = time.time()
        self._reset_inactivity_timer(agent)

        # Track turns
        if event.type == "item.completed":
            item = event.data.get("item", {})
            if item.get("role") == "assistant":
                agent.turn_count += 1

        # Match against rules
        for rule in self.config.rules:
            if self._matches_rule(rule, event, agent.agent_id):
                await self._apply_rule(rule, event, agent)
                return True

        return False

    def _matches_rule(
        self,
        rule: OrchestratorRule,
        event: SDKEvent,
        agent_id: str,
    ) -> bool:
        """Check if an event matches a rule."""
        # Check event type
        if rule.on != event.type:
            return False

        # Check agent filter
        if rule.from_agent and rule.from_agent != agent_id:
            agent = self._agents.get(agent_id)
            if agent is None:
                return False

            role_filter = rule.from_agent.strip().lower()
            role = (agent.role or "").lower()
            if role_filter in ("coordinator", "hub"):
                if role != "hub":
                    return False
            elif role_filter == "worker":
                if role != "worker":
                    return False
            elif role_filter == "peer":
                if role and role != "peer":
                    return False
            else:
                return False

        # Check condition
        if rule.if_condition:
            action = event.data.get("action", "")
            condition = rule.if_condition

            # Parse one or more "action contains X" clauses (OR semantics).
            # Example: action contains "curl" or action contains "wget"
            targets = re.findall(
                r'action contains ["\']?([^"\']+)["\']?',
                condition,
                flags=re.IGNORECASE,
            )
            if targets:
                action_lower = action.lower()
                if not any(target.lower() in action_lower for target in targets):
                    return False
            else:
                # Unknown condition syntax should not match implicitly.
                return False

        return True

    async def _apply_rule(
        self,
        rule: OrchestratorRule,
        event: SDKEvent,
        agent: AgentState,
    ) -> None:
        """Apply a matched rule."""
        intervention = InterventionLog(
            timestamp=datetime.now(),
            rule=rule,
            event=event,
            agent_id=agent.agent_id,
            action_taken=rule.then,
        )

        if rule.then == OrchestratorAction.APPROVE:
            if event.type == "permission.requested":
                permission_id = event.data.get("permission_id")
                if permission_id:
                    await self.sdk.reply_permission(agent.session_id, permission_id, "once")
                    intervention.details["permission_id"] = permission_id

        elif rule.then == OrchestratorAction.REJECT:
            if event.type == "permission.requested":
                permission_id = event.data.get("permission_id")
                if permission_id:
                    await self.sdk.reply_permission(agent.session_id, permission_id, "deny")
                    intervention.details["permission_id"] = permission_id

        elif rule.then in (OrchestratorAction.ESCALATE, OrchestratorAction.ESCALATE_TO_HUMAN):
            if self.on_escalate:
                self.on_escalate(agent.agent_id, event, rule)
            intervention.details["escalated"] = True

        elif rule.then == OrchestratorAction.LOG:
            # Just log, no action
            intervention.details["logged_only"] = True

        elif rule.then in (OrchestratorAction.NUDGE, OrchestratorAction.NUDGE_COORDINATOR):
            message = rule.message or "Please continue with your task."
            target = agent
            if rule.then == OrchestratorAction.NUDGE_COORDINATOR:
                coordinator = self._find_coordinator()
                if coordinator:
                    target = coordinator
            await self.sdk.post_message(target.session_id, message)
            intervention.details["nudge_message"] = message
            intervention.details["target_agent_id"] = target.agent_id

        self._interventions.append(intervention)

    def _find_coordinator(self) -> AgentState | None:
        """Find the hub/coordinator agent state if configured."""
        for state in self._agents.values():
            if (state.role or "").lower() == "hub":
                return state
        return None

    def _reset_inactivity_timer(self, agent: AgentState) -> None:
        """Reset the inactivity timer for an agent."""
        # Cancel existing timer
        if agent.agent_id in self._inactivity_tasks:
            self._inactivity_tasks[agent.agent_id].cancel()

        # Check for inactivity rules
        for rule in self.config.rules:
            if rule.on == "no_activity" and rule.after:
                seconds = self._parse_duration(rule.after)
                task = asyncio.create_task(
                    self._inactivity_check(agent, rule, seconds)
                )
                self._inactivity_tasks[agent.agent_id] = task
                break  # Use first matching rule

    async def _inactivity_check(
        self,
        agent: AgentState,
        rule: OrchestratorRule,
        seconds: float,
    ) -> None:
        """Check for inactivity after a delay."""
        try:
            await asyncio.sleep(seconds)
            # Still no activity?
            if time.time() - agent.last_activity >= seconds:
                await self._apply_rule(rule, SDKEvent("no_activity", {}), agent)
        except asyncio.CancelledError:
            pass

    def _parse_duration(self, duration: str) -> float:
        """Parse a duration string to seconds."""
        duration = duration.strip().lower()
        if duration.endswith("s"):
            return float(duration[:-1])
        elif duration.endswith("m"):
            return float(duration[:-1]) * 60
        elif duration.endswith("h"):
            return float(duration[:-1]) * 3600
        else:
            return float(duration)

    def stop(self) -> None:
        """Signal the runtime guard to stop."""
        self._stop_event.set()
        for task in self._inactivity_tasks.values():
            task.cancel()

    def get_interventions(self) -> list[InterventionLog]:
        """Get all intervention logs."""
        return self._interventions.copy()

    def get_agent_turn_count(self, agent_id: str) -> int:
        """Get the turn count for an agent."""
        agent = self._agents.get(agent_id)
        return agent.turn_count if agent else 0


# Backward-compatibility alias during terminology transition.
Orchestrator = RuntimeGuard
