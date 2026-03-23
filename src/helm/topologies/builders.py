"""Orchestrator and coordination config builders."""

from __future__ import annotations

from typing import Any

def build_orchestrator(family: str) -> dict[str, Any]:
    rules: list[dict[str, Any]] = [
        {
            "on": "permission.requested",
            "if": 'action contains "rm -rf"',
            "then": "reject",
            "reason": "Dangerous command pattern",
        },
        {
            "on": "permission.requested",
            "if": 'action contains "curl" or action contains "wget"',
            "then": "escalate",
            "reason": "Network action needs review",
        },
        {
            "on": "no_activity",
            "after": "180s",
            "then": "log",
            "message": "No activity detected. Check for blockers or closure drift.",
        },
    ]

    if family in {"independent", "centralized", "hybrid"}:
        rules.extend(
            [
                {
                    "on": "question.requested",
                    "from": "coordinator" if family != "independent" else "selector",
                    "then": "escalate_to_human",
                    "reason": "Lead-role questions go to human",
                },
                {
                    "on": "question.requested",
                    "from": "worker",
                    "then": "log",
                    "reason": "Worker questions should stay in-system first",
                },
            ]
        )

    return {"role": "observer", "rules": rules}


def build_coordination(family: str) -> dict[str, Any]:
    if family == "single":
        return {
            "mechanism": "filesystem",
            "paths": {
                "base": "coordination/",
                "signals": "coordination/signals/",
            },
            "channels": [
                {
                    "id": "completion_signal",
                    "medium": "filesystem",
                    "persistence": "persistent",
                    "scope": "broadcast",
                    "paths": ["coordination/signals/"],
                    "description": "Durable verification summary and completion record.",
                },
                {
                    "id": "live_followup_messages",
                    "medium": "live_message",
                    "persistence": "ephemeral",
                    "scope": "targeted",
                    "availability": "harness_dependent",
                    "description": "Fast transient follow-up messages when supported by the harness.",
                },
            ],
        }

    if family in {"independent", "centralized"}:
        return {
            "mechanism": "filesystem",
            "paths": {
                "base": "coordination/",
                "tasks": "coordination/tasks/",
                "status": "coordination/status/",
                "blocked": "coordination/blocked/",
                "questions": "coordination/questions/",
                "decisions": "coordination/decisions/",
                "signals": "coordination/signals/",
            },
            "channels": [
                {
                    "id": "task_assignments",
                    "medium": "filesystem",
                    "persistence": "persistent",
                    "scope": "targeted",
                    "paths": ["coordination/tasks/"],
                    "description": "Durable assignments and completed handoffs.",
                },
                {
                    "id": "status_and_blockers",
                    "medium": "filesystem",
                    "persistence": "persistent",
                    "scope": "mixed",
                    "paths": [
                        "coordination/status/",
                        "coordination/blocked/",
                        "coordination/questions/",
                    ],
                    "description": "Durable status, blockers, and clarification requests.",
                },
                {
                    "id": "lead_decisions",
                    "medium": "filesystem",
                    "persistence": "persistent",
                    "scope": "broadcast",
                    "paths": ["coordination/decisions/"],
                    "description": "Durable selector/coordinator decisions.",
                },
                {
                    "id": "completion_signals",
                    "medium": "filesystem",
                    "persistence": "persistent",
                    "scope": "broadcast",
                    "paths": ["coordination/signals/"],
                    "description": "Durable verification and completion markers.",
                },
                {
                    "id": "live_followup_messages",
                    "medium": "live_message",
                    "persistence": "ephemeral",
                    "scope": "targeted",
                    "availability": "harness_dependent",
                    "description": "Fast transient follow-up messages when supported by the harness.",
                },
            ],
        }

    if family == "decentralized":
        return {
            "mechanism": "filesystem",
            "paths": {
                "base": "coordination/",
                "messages": "coordination/messages/",
                "state": "coordination/state.json",
                "signals": "coordination/signals/",
                "reviews": "coordination/reviews/",
            },
            "channels": [
                {
                    "id": "persistent_peer_messages",
                    "medium": "filesystem",
                    "persistence": "persistent",
                    "scope": "mixed",
                    "paths": ["coordination/messages/"],
                    "description": "Durable targeted or broadcast peer handoffs.",
                },
                {
                    "id": "shared_coordination_state",
                    "medium": "filesystem",
                    "persistence": "persistent",
                    "scope": "shared",
                    "paths": ["coordination/state.json"],
                    "description": "Durable shared state about current work and plan.",
                },
                {
                    "id": "review_artifacts",
                    "medium": "filesystem",
                    "persistence": "persistent",
                    "scope": "mixed",
                    "paths": ["coordination/reviews/"],
                    "description": "Durable review and verification artifacts.",
                },
                {
                    "id": "completion_signals",
                    "medium": "filesystem",
                    "persistence": "persistent",
                    "scope": "broadcast",
                    "paths": ["coordination/signals/"],
                    "description": "Durable readiness and completion markers.",
                },
                {
                    "id": "live_followup_messages",
                    "medium": "live_message",
                    "persistence": "ephemeral",
                    "scope": "mixed",
                    "availability": "harness_dependent",
                    "description": "Fast transient follow-up messages when supported by the harness.",
                },
            ],
        }

    return {
        "mechanism": "filesystem",
        "paths": {
            "base": "coordination/",
            "tasks": "coordination/tasks/",
            "status": "coordination/status/",
            "blocked": "coordination/blocked/",
            "questions": "coordination/questions/",
            "decisions": "coordination/decisions/",
            "messages": "coordination/messages/",
            "reviews": "coordination/reviews/",
            "signals": "coordination/signals/",
            "state": "coordination/state.json",
        },
        "channels": [
            {
                "id": "task_assignments",
                "medium": "filesystem",
                "persistence": "persistent",
                "scope": "targeted",
                "paths": ["coordination/tasks/"],
                "description": "Durable coordinator assignments and worker handoffs.",
            },
            {
                "id": "status_and_blockers",
                "medium": "filesystem",
                "persistence": "persistent",
                "scope": "mixed",
                "paths": [
                    "coordination/status/",
                    "coordination/blocked/",
                    "coordination/questions/",
                ],
                "description": "Durable worker status, blockers, and questions.",
            },
            {
                "id": "peer_review_messages",
                "medium": "filesystem",
                "persistence": "persistent",
                "scope": "mixed",
                "paths": ["coordination/messages/", "coordination/reviews/"],
                "description": "Durable lateral peer exchange and review artifacts.",
            },
            {
                "id": "shared_coordination_state",
                "medium": "filesystem",
                "persistence": "persistent",
                "scope": "shared",
                "paths": ["coordination/state.json"],
                "description": "Durable shared state about active work and review status.",
            },
            {
                "id": "coordinator_decisions",
                "medium": "filesystem",
                "persistence": "persistent",
                "scope": "broadcast",
                "paths": ["coordination/decisions/"],
                "description": "Durable coordinator decisions and synthesis steps.",
            },
            {
                "id": "completion_signals",
                "medium": "filesystem",
                "persistence": "persistent",
                "scope": "broadcast",
                "paths": ["coordination/signals/"],
                "description": "Durable verification and completion markers.",
            },
            {
                "id": "live_followup_messages",
                "medium": "live_message",
                "persistence": "ephemeral",
                "scope": "mixed",
                "availability": "harness_dependent",
                "description": "Fast transient follow-up messages when supported by the harness.",
            },
        ],
    }

