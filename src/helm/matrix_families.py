"""Architecture family layouts and prompt builders for experiment matrices."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

SUPPORTED_FAMILY_SIZES: dict[str, set[int]] = {
    "single": {1},
    "independent": {2, 3, 5, 8},
    "centralized": {2, 3, 5, 8},
    "decentralized": {2, 3, 5, 8},
    "hybrid": {2, 3, 5, 8},
    "delegating": {1, 3, 5},
}

COORDINATION_FAMILY_LABELS = {
    "single": "single_solver_persistent_v1",
    "independent": "independent_selector_v1",
    "centralized": "centralized_hub_v1",
    "decentralized": "peer_network_v1",
    "hybrid": "hybrid_hub_lateral_review_v1",
    "delegating": "delegating_hub_v1",
}

# Mechanical topology enforcement: tools blocked per (family, role).
# These are enforced via --disallowedTools, not just prompt instructions.
TOPOLOGY_RULES: dict[tuple[str, str], list[str]] = {
    # Single: true single agent, no delegation or messaging
    ("single", "solver"): ["Agent", "TeamCreate", "SendMessage"],
    # Independent: isolated candidates, no cross-communication
    ("independent", "candidate"): ["Agent", "TeamCreate", "SendMessage"],
    ("independent", "selector"): ["Agent", "TeamCreate", "SendMessage"],
    # Centralized: all coordination through filesystem, no native tools
    ("centralized", "hub"): ["Agent", "TeamCreate", "SendMessage"],
    ("centralized", "worker"): ["Agent", "TeamCreate", "SendMessage"],
    # Decentralized: peer filesystem coordination, no delegation
    ("decentralized", "peer"): ["Agent", "TeamCreate", "SendMessage"],
    # Hybrid: hub + lateral filesystem channels, no native tools
    ("hybrid", "hub"): ["Agent", "TeamCreate", "SendMessage"],
    ("hybrid", "worker"): ["Agent", "TeamCreate", "SendMessage"],
    # Delegating: hub CAN spawn via helm-agent CLI, workers cannot
    ("delegating", "hub"): ["TeamCreate", "SendMessage"],  # Agent allowed
    ("delegating", "worker"): ["Agent", "TeamCreate", "SendMessage"],
}


def get_disallowed_tools(family: str, role: str) -> list[str]:
    """Return the list of tools mechanically blocked for a given family/role."""
    return TOPOLOGY_RULES.get((family, role), ["Agent", "TeamCreate", "SendMessage"])


@dataclass(frozen=True)
class RoleSpec:
    agent_id: str
    runtime_role: str | None
    prompt_kind: str
    closer: bool = False


FAMILY_LAYOUTS: dict[str, dict[int, list[RoleSpec]]] = {
    "single": {
        1: [RoleSpec("solver", None, "single_solver", closer=True)],
    },
    "independent": {
        2: [
            RoleSpec("candidate", "worker", "independent_candidate"),
            RoleSpec("selector", "hub", "independent_selector", closer=True),
        ],
        3: [
            RoleSpec("candidate_a", "worker", "independent_candidate"),
            RoleSpec("candidate_b", "worker", "independent_candidate"),
            RoleSpec("selector", "hub", "independent_selector", closer=True),
        ],
        5: [
            RoleSpec("candidate_a", "worker", "independent_candidate"),
            RoleSpec("candidate_b", "worker", "independent_candidate"),
            RoleSpec("candidate_c", "worker", "independent_candidate"),
            RoleSpec("candidate_d", "worker", "independent_candidate"),
            RoleSpec("selector", "hub", "independent_selector", closer=True),
        ],
        8: [
            RoleSpec("candidate_a", "worker", "independent_candidate"),
            RoleSpec("candidate_b", "worker", "independent_candidate"),
            RoleSpec("candidate_c", "worker", "independent_candidate"),
            RoleSpec("candidate_d", "worker", "independent_candidate"),
            RoleSpec("candidate_e", "worker", "independent_candidate"),
            RoleSpec("candidate_f", "worker", "independent_candidate"),
            RoleSpec("candidate_g", "worker", "independent_candidate"),
            RoleSpec("selector", "hub", "independent_selector", closer=True),
        ],
    },
    "centralized": {
        2: [
            RoleSpec("coordinator", "hub", "centralized_coordinator", closer=True),
            RoleSpec("worker", "worker", "centralized_worker"),
        ],
        3: [
            RoleSpec("coordinator", "hub", "centralized_coordinator", closer=True),
            RoleSpec("researcher", "worker", "centralized_researcher"),
            RoleSpec("implementer", "worker", "centralized_implementer"),
        ],
        5: [
            RoleSpec("coordinator", "hub", "centralized_coordinator", closer=True),
            RoleSpec("researcher_a", "worker", "centralized_researcher"),
            RoleSpec("researcher_b", "worker", "centralized_researcher"),
            RoleSpec("implementer", "worker", "centralized_implementer"),
            RoleSpec("reviewer", "worker", "centralized_reviewer"),
        ],
        8: [
            RoleSpec("coordinator", "hub", "centralized_coordinator", closer=True),
            RoleSpec("researcher_a", "worker", "centralized_researcher"),
            RoleSpec("researcher_b", "worker", "centralized_researcher"),
            RoleSpec("researcher_c", "worker", "centralized_researcher"),
            RoleSpec("implementer_a", "worker", "centralized_implementer"),
            RoleSpec("implementer_b", "worker", "centralized_implementer"),
            RoleSpec("reviewer_a", "worker", "centralized_reviewer"),
            RoleSpec("reviewer_b", "worker", "centralized_reviewer"),
        ],
    },
    "decentralized": {
        2: [
            RoleSpec("solver_a", "peer", "peer_solver"),
            RoleSpec("solver_b", "peer", "peer_solver", closer=True),
        ],
        3: [
            RoleSpec("researcher", "peer", "peer_researcher"),
            RoleSpec("implementer", "peer", "peer_implementer"),
            RoleSpec("reviewer", "peer", "peer_reviewer", closer=True),
        ],
        5: [
            RoleSpec("researcher_a", "peer", "peer_researcher"),
            RoleSpec("researcher_b", "peer", "peer_researcher"),
            RoleSpec("implementer_a", "peer", "peer_implementer"),
            RoleSpec("implementer_b", "peer", "peer_implementer"),
            RoleSpec("reviewer", "peer", "peer_reviewer", closer=True),
        ],
        8: [
            RoleSpec("researcher_a", "peer", "peer_researcher"),
            RoleSpec("researcher_b", "peer", "peer_researcher"),
            RoleSpec("researcher_c", "peer", "peer_researcher"),
            RoleSpec("implementer_a", "peer", "peer_implementer"),
            RoleSpec("implementer_b", "peer", "peer_implementer"),
            RoleSpec("implementer_c", "peer", "peer_implementer"),
            RoleSpec("reviewer_a", "peer", "peer_reviewer"),
            RoleSpec("reviewer_b", "peer", "peer_reviewer", closer=True),
        ],
    },
    "hybrid": {
        2: [
            RoleSpec("coordinator", "hub", "hybrid_coordinator", closer=True),
            RoleSpec("solver", "worker", "hybrid_implementer"),
        ],
        3: [
            RoleSpec("coordinator", "hub", "hybrid_coordinator", closer=True),
            RoleSpec("implementer", "worker", "hybrid_implementer"),
            RoleSpec("reviewer", "worker", "hybrid_reviewer"),
        ],
        5: [
            RoleSpec("coordinator", "hub", "hybrid_coordinator", closer=True),
            RoleSpec("researcher_a", "worker", "hybrid_researcher"),
            RoleSpec("researcher_b", "worker", "hybrid_researcher"),
            RoleSpec("implementer", "worker", "hybrid_implementer"),
            RoleSpec("reviewer", "worker", "hybrid_reviewer"),
        ],
        8: [
            RoleSpec("coordinator", "hub", "hybrid_coordinator", closer=True),
            RoleSpec("researcher_a", "worker", "hybrid_researcher"),
            RoleSpec("researcher_b", "worker", "hybrid_researcher"),
            RoleSpec("researcher_c", "worker", "hybrid_researcher"),
            RoleSpec("implementer_a", "worker", "hybrid_implementer"),
            RoleSpec("implementer_b", "worker", "hybrid_implementer"),
            RoleSpec("reviewer_a", "worker", "hybrid_reviewer"),
            RoleSpec("reviewer_b", "worker", "hybrid_reviewer"),
        ],
    },
    "delegating": {
        1: [RoleSpec("delegator", "hub", "delegating_solo", closer=True)],
        3: [
            RoleSpec("delegator", "hub", "delegating_coordinator", closer=True),
            RoleSpec("worker_a", "worker", "delegating_worker"),
            RoleSpec("worker_b", "worker", "delegating_worker"),
        ],
        5: [
            RoleSpec("delegator", "hub", "delegating_coordinator", closer=True),
            RoleSpec("worker_a", "worker", "delegating_worker"),
            RoleSpec("worker_b", "worker", "delegating_worker"),
            RoleSpec("worker_c", "worker", "delegating_worker"),
            RoleSpec("worker_d", "worker", "delegating_worker"),
        ],
    },
}


def pattern_runtime_label(family: str) -> str:
    if family == "single":
        return "single-agent"
    if family == "decentralized":
        return "peer-network"
    if family == "delegating":
        return "delegating"
    return "hub-and-spoke"


def _team_listing(layout: list[RoleSpec]) -> str:
    lines: list[str] = []
    for role in layout:
        label = role.prompt_kind.replace("_", " ")
        lines.append(f"- `{role.agent_id}`: {label}")
    return "\n".join(lines)


def _coordination_overview(family: str, role: RoleSpec) -> str:
    if family == "single":
        return "\n".join(
            [
                "Persistent channel:",
                "- `coordination/signals/` for durable verification and completion records.",
                "",
                "Ephemeral channel:",
                "- Live follow-up messages may arrive when the harness supports them; they are fast but transient.",
            ]
        )
    if family == "delegating":
        return "\n".join(
            [
                "Persistent channels:",
                "- `coordination/tasks/` for durable assignments to pre-assigned workers.",
                "- `coordination/results/` for subagent output (written by spawned agents).",
                "- `coordination/signals/` for verification and completion markers.",
                "- `coordination/spawn_log.jsonl` for spawn audit trail.",
                "",
                "Coordination CLI (use via Bash):",
                "- `python -m helm.agent_cli spawn --parent {your_id} --task '...' --role worker`",
                "- `python -m helm.agent_cli send --from {your_id} --to {recipient} --msg '...'`",
                "- `python -m helm.agent_cli inbox --agent {your_id}`",
                "- `python -m helm.agent_cli status --agent {agent_id}`",
            ]
        )
    if family in {"independent", "centralized"}:
        return "\n".join(
            [
                "Persistent channels:",
                "- `coordination/tasks/` for durable assignments and completed handoffs.",
                "- `coordination/status/`, `coordination/blocked/`, and `coordination/questions/` for durable state and blockers.",
                "- `coordination/decisions/` and `coordination/signals/` for durable decisions and completion markers.",
                "",
                "Ephemeral channel:",
                "- Live follow-up messages may arrive when the harness supports them; they are fast but transient.",
            ]
        )
    if family == "decentralized":
        return "\n".join(
            [
                "Persistent channels:",
                "- `coordination/messages/` for durable targeted or broadcast peer handoffs.",
                "- `coordination/state.json` for durable shared state.",
                "- `coordination/reviews/` and `coordination/signals/` for review artifacts and completion markers.",
                "",
                "Ephemeral channel:",
                "- Live follow-up messages may arrive when the harness supports them; they are fast but transient.",
            ]
        )
    return "\n".join(
        [
            "Persistent channels:",
            "- `coordination/tasks/` and `coordination/decisions/` for durable decomposition and coordinator directives.",
            "- `coordination/messages/`, `coordination/reviews/`, and `coordination/state.json` for worker lateral exchange and review artifacts.",
            "- `coordination/signals/` for durable verification and completion markers.",
            "",
            "Ephemeral channel:",
            "- Live follow-up messages may arrive when the harness supports them; they are fast but transient.",
        ]
    )


def _shared_benchmark_rules() -> str:
    return "\n".join(
        [
            "- The target repository is already staged in `workspace/repo`.",
            "- Prefer source-code fixes over benchmark-owned test edits unless a test change is clearly necessary.",
            "- Verify with both targeted reproduction coverage and a broader regression check for the touched area.",
            "- Write durable verification artifacts before any global completion signal.",
            "- Surface blockers and uncertainty clearly instead of narrating success too early.",
        ]
    )


def build_tool_instructions(family: str, role: RoleSpec) -> str:
    """Build prompt section explaining which tools are disabled and how to coordinate."""
    runtime_role = role.runtime_role or "solver"
    disallowed = get_disallowed_tools(family, runtime_role)

    if not disallowed:
        return ""

    lines = [
        "## Topology Enforcement",
        "",
        "The following tools are **mechanically disabled** in this experiment:",
    ]
    for tool in disallowed:
        lines.append(f"- {tool}")
    lines.append("")
    lines.append("Attempts to use these tools will fail. This is not a suggestion — the tools are blocked at the CLI level.")
    lines.append("")

    if family == "single":
        lines.append("You are a single agent. Solve the task on your own using Read, Write, Edit, Bash, Grep, and Glob.")
    elif family in ("centralized", "decentralized", "hybrid"):
        lines.extend([
            "To coordinate with other agents, use the filesystem protocol:",
            "  - Send messages: `python -m helm.agent_cli send --from {your_id} --to {recipient} --msg \"message\"`",
            "  - Check inbox: `python -m helm.agent_cli inbox --agent {your_id}`",
            "  - Check status: `python -m helm.agent_cli status --agent {agent_id}`",
            "",
            "All coordination goes through `coordination/` directories. Do not attempt to use Agent, TeamCreate, or SendMessage.",
        ])
    elif family == "delegating":
        if "Agent" not in disallowed:
            # This is the hub in delegating — can spawn
            lines.extend([
                "You may delegate subtasks to subagents:",
                "  - Spawn: `python -m helm.agent_cli spawn --parent {your_id} --task \"subtask description\" --role worker`",
                "  - Send messages: `python -m helm.agent_cli send --from {your_id} --to {recipient} --msg \"message\"`",
                "  - Check inbox: `python -m helm.agent_cli inbox --agent {your_id}`",
                "",
                "Spawned subagents run independently and write results to `coordination/results/`.",
                "You decide how to decompose the work — the system does not prescribe a decomposition strategy.",
            ])
        else:
            lines.extend([
                "You are a spawned subagent. Complete your assigned task and write results to the specified output file.",
                "You cannot spawn further subagents.",
            ])

    return "\n".join(lines)


def build_prompt(family: str, layout: list[RoleSpec], role: RoleSpec) -> str:
    team_listing = _team_listing(layout)
    common_rules = _shared_benchmark_rules()
    coordination_overview = _coordination_overview(family, role)
    tool_instructions = build_tool_instructions(family, role)

    if role.prompt_kind == "single_solver":
        return f"""You are the sole solver in a Helm matrix experiment on a SWE-bench task.

## Coordination Affordances

{coordination_overview}

## Instructions

1. Read the problem statement carefully.
2. Explore the repository to understand the relevant code.
3. Write a minimal, targeted fix.
4. Verify the fix thoroughly.
5. Write `coordination/signals/verification-summary.md` with exact commands, outcomes, touched files, and remaining uncertainty.
6. Only after the verification summary exists should you write `coordination/signals/done`.

## Important

{common_rules}

{tool_instructions}
"""

    if role.prompt_kind == "independent_selector":
        return f"""You are the selector/finalizer in an independent ensemble solving a SWE-bench task.

## Team

{team_listing}

## Coordination Affordances

{coordination_overview}

## Instructions

1. Give each candidate a durable initial brief in `coordination/tasks/{{agent}}/pending/`.
2. Candidates work independently and do not coordinate laterally.
3. Read candidate submissions from `coordination/tasks/{{agent}}/completed/` and any status files.
4. Choose or merge the best candidate solution.
5. Run the final verification pass yourself.
6. Write `coordination/signals/verification-summary.md`.
7. Only then write `coordination/signals/done`.

## Important

{common_rules}

{tool_instructions}
- Do not force candidates into a shared plan; the experiment condition is late aggregation.
"""

    if role.prompt_kind == "independent_candidate":
        return f"""You are `{role.agent_id}`, a candidate solver in an independent ensemble.

## Coordination Affordances

{coordination_overview}

## Instructions

1. Read any durable brief in `coordination/tasks/{role.agent_id}/pending/`.
2. Solve the task independently; do not wait for or coordinate with other candidates.
3. Publish your findings and suggested final state to `coordination/tasks/{role.agent_id}/completed/`.
4. Record blockers or uncertainty in `coordination/status/{role.agent_id}.json` or `coordination/blocked/{role.agent_id}.md`.

## Important

{common_rules}

{tool_instructions}
- Do not write the global done signal.
"""

    if role.prompt_kind == "centralized_coordinator":
        return f"""You are the central coordinator in a centralized swarm solving a SWE-bench task.

## Team

{team_listing}

## Coordination Affordances

{coordination_overview}

## Instructions

1. Decompose the task into durable assignments.
2. Route work through `coordination/tasks/` and keep your decisions auditable in `coordination/decisions/`.
3. Keep workers unblocked and request clarification when the task or verification path is ambiguous.
4. Require both targeted reproduction coverage and broader regression coverage before accepting the fix.
5. Write `coordination/signals/verification-summary.md`.
6. Only then write `coordination/signals/done`.

## Important

{common_rules}

{tool_instructions}
- Workers should not coordinate laterally in this condition unless the harness itself injects a transient message.
"""

    if role.prompt_kind == "centralized_researcher":
        return f"""You are `{role.agent_id}`, a researcher reporting to a central coordinator.

## Coordination Affordances

{coordination_overview}

## Instructions

1. Work only on assigned investigation tasks.
2. Publish durable findings and root-cause notes through your task completion files.
3. Escalate blockers via `coordination/blocked/` or `coordination/questions/`.

## Important

{common_rules}

{tool_instructions}
- Do not coordinate laterally with other workers in this condition.
- Do not write the global done signal.
"""

    if role.prompt_kind == "centralized_implementer":
        return f"""You are `{role.agent_id}`, an implementer reporting to a central coordinator.

## Coordination Affordances

{coordination_overview}

## Instructions

1. Work only on assigned implementation tasks.
2. Make minimal, targeted changes in `workspace/repo`.
3. Publish durable status and handoff notes through `coordination/tasks/` and `coordination/status/`.

## Important

{common_rules}

{tool_instructions}
- Do not coordinate laterally with other workers in this condition.
- Do not write the global done signal.
"""

    if role.prompt_kind == "centralized_worker":
        return f"""You are `{role.agent_id}`, a worker reporting to a central coordinator.

## Coordination Affordances

{coordination_overview}

## Instructions

1. Work only on assigned tasks.
2. Keep durable handoffs, status, and blockers up to date.
3. Stay within assigned scope unless the coordinator explicitly expands it.

## Important

{common_rules}

{tool_instructions}
- Do not coordinate laterally with other workers in this condition.
- Do not write the global done signal.
"""

    if role.prompt_kind == "centralized_reviewer":
        return f"""You are `{role.agent_id}`, a reviewer reporting to a central coordinator.

## Coordination Affordances

{coordination_overview}

## Instructions

1. Review assigned changes against the problem statement and the coordinator's spec.
2. Run both targeted and broader regression checks on assigned scope.
3. Record findings durably so the coordinator can close the run cleanly.

## Important

{common_rules}

{tool_instructions}
- Do not coordinate laterally with other workers in this condition.
- Do not write the global done signal.
"""

    if role.prompt_kind == "peer_researcher":
        return f"""You are `{role.agent_id}`, a research peer in a decentralized swarm.

## Coordination Affordances

{coordination_overview}

## Instructions

1. Investigate root cause and share durable findings early.
2. Use `coordination/messages/` and `coordination/state.json` so peers can reuse your work.
3. Mark your local readiness with `coordination/signals/{role.agent_id}.done` when finished.

## Important

{common_rules}

{tool_instructions}
- Coordinate as a peer, not a manager.
- Do not write the global done signal unless you are the designated closer.
"""

    if role.prompt_kind == "peer_implementer":
        return f"""You are `{role.agent_id}`, an implementation peer in a decentralized swarm.

## Coordination Affordances

{coordination_overview}

## Instructions

1. Use shared state and peer messages to understand the current plan.
2. Write minimal source-code fixes and keep handoffs durable.
3. Mark your local readiness with `coordination/signals/{role.agent_id}.done` when finished.

## Important

{common_rules}

{tool_instructions}
- Coordinate as a peer, not a manager.
- Do not write the global done signal unless you are the designated closer.
"""

    if role.prompt_kind == "peer_reviewer":
        closer_clause = (
            "You are the designated closer: after the swarm converges, write "
            "`coordination/reviews/final-verification.md` and then `coordination/signals/done`."
            if role.closer
            else "Write durable review artifacts and mark your local readiness with your `.done` file."
        )
        return f"""You are `{role.agent_id}`, a review peer in a decentralized swarm.

## Coordination Affordances

{coordination_overview}

## Instructions

1. Review changes against the problem statement and peer findings.
2. Run both targeted and broader regression coverage.
3. Persist feedback in `coordination/reviews/`.
4. {closer_clause}

## Important

{common_rules}

{tool_instructions}
- Coordinate as a peer, not a manager.
"""

    if role.prompt_kind == "peer_solver":
        closer_clause = (
            "You are the designated closer: after shared verification, write "
            "`coordination/reviews/final-verification.md` and then `coordination/signals/done`."
            if role.closer
            else "When finished, write your local readiness marker and keep peers informed."
        )
        return f"""You are `{role.agent_id}`, a solver peer in a two-agent decentralized swarm.

## Coordination Affordances

{coordination_overview}

## Instructions

1. Coordinate through durable peer messages and shared state.
2. Divide work organically, but keep the current plan inspectable in shared artifacts.
3. {closer_clause}

## Important

{common_rules}

{tool_instructions}
- Coordinate as a peer, not a manager.
"""

    if role.prompt_kind == "hybrid_coordinator":
        return f"""You are the coordinator in a hybrid swarm solving a SWE-bench task.

## Team

{team_listing}

## Coordination Affordances

{coordination_overview}

## Instructions

1. Decompose the task and assign durable work items.
2. Let workers use lateral review and shared state when it helps, but keep the high-level plan legible.
3. Require review artifacts before closing the run.
4. Write `coordination/signals/verification-summary.md`.
5. Only then write `coordination/signals/done`.

## Important

{common_rules}

{tool_instructions}
- Do not micromanage every handoff if workers can resolve it through the allowed lateral channels.
"""

    if role.prompt_kind == "hybrid_researcher":
        return f"""You are `{role.agent_id}`, a researcher in a hybrid swarm.

## Coordination Affordances

{coordination_overview}

## Instructions

1. Take durable assignments from the coordinator.
2. Share reusable findings with peers when it improves review or implementation quality.
3. Keep blockers and uncertainty inspectable.

## Important

{common_rules}

{tool_instructions}
- Respect the coordinator's overall plan, but use the lateral channels when local peer exchange is beneficial.
- Do not write the global done signal.
"""

    if role.prompt_kind == "hybrid_implementer":
        return f"""You are `{role.agent_id}`, an implementer in a hybrid swarm.

## Coordination Affordances

{coordination_overview}

## Instructions

1. Take durable assignments from the coordinator.
2. Make minimal source-code changes.
3. Use peer review channels when feedback can improve the fix before final closure.

## Important

{common_rules}

{tool_instructions}
- Respect the coordinator's overall plan, but use the lateral channels when local peer exchange is beneficial.
- Do not write the global done signal.
"""

    if role.prompt_kind == "hybrid_reviewer":
        return f"""You are `{role.agent_id}`, a reviewer in a hybrid swarm.

## Coordination Affordances

{coordination_overview}

## Instructions

1. Review candidate changes against the task and any peer research.
2. Run targeted and broader regression checks.
3. Publish durable review artifacts so the coordinator can close cleanly.

## Important

{common_rules}

{tool_instructions}
- Respect the coordinator's overall plan, but use the lateral channels when local peer exchange is beneficial.
- Do not write the global done signal.
"""

    if role.prompt_kind == "delegating_solo":
        return f"""You are a single agent that may delegate subtasks to subagents.

## Coordination Affordances

{coordination_overview}

## Instructions

1. Read the problem statement carefully.
2. Decide whether to solve directly or decompose into subtasks.
3. You may delegate subtasks using: `python -m helm.agent_cli spawn --parent {role.agent_id} --task "subtask" --role worker`
4. Spawned subagents write results to `coordination/results/`. Read their output to integrate.
5. Write the final fix yourself or integrate subagent contributions.
6. Verify the fix thoroughly.
7. Write `coordination/signals/verification-summary.md`.
8. Only then write `coordination/signals/done`.

## Important

{common_rules}

{tool_instructions}
- You decide the decomposition strategy — the system does not prescribe one.
- Spawned subagents cannot spawn further subagents.
"""

    if role.prompt_kind == "delegating_coordinator":
        return f"""You are the delegating coordinator. You may spawn subagents to parallelize work.

## Team

{team_listing}

## Coordination Affordances

{coordination_overview}

## Instructions

1. Decompose the task into subtasks as you see fit.
2. You may spawn additional subagents: `python -m helm.agent_cli spawn --parent {role.agent_id} --task "subtask" --role worker`
3. Use `coordination/tasks/` for durable assignments to pre-assigned workers.
4. Spawned subagents write results to `coordination/results/`.
5. Integrate results and verify the fix.
6. Write `coordination/signals/verification-summary.md`.
7. Only then write `coordination/signals/done`.

## Important

{common_rules}

{tool_instructions}
- Pre-assigned workers communicate via filesystem only.
- You decide when to use pre-assigned workers vs spawning new subagents.
"""

    if role.prompt_kind == "delegating_worker":
        return f"""You are `{role.agent_id}`, a worker assigned by the delegating coordinator.

## Coordination Affordances

{coordination_overview}

## Instructions

1. Work on tasks assigned in `coordination/tasks/{role.agent_id}/`.
2. Publish findings and status through coordination filesystem.
3. You cannot spawn subagents or use native messaging tools.

## Important

{common_rules}

{tool_instructions}
- Do not write the global done signal.
"""

    raise ValueError(f"Unsupported prompt kind `{role.prompt_kind}`")


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
