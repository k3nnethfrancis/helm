"""Helpers for generating, running, and analyzing factorized experiment matrices."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from statistics import mean
from typing import Any

import yaml
from pydantic import BaseModel, Field, model_validator

from helm.config import ExperimentConfig

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_GENERATED_ROOT = REPO_ROOT / "patterns" / "generated"
DEFAULT_EXPERIMENTS_DIR = REPO_ROOT / "experiments"
ACTIVE_DIMENSIONS = [
    "escalation-calibration",
    "goal-drift",
    "failure-suppression",
    "context-degradation",
    "resource-waste",
]
MATRIX_METADATA_FIELDS = [
    "matrix_id",
    "condition_id",
    "architecture_family",
    "swarm_size",
    "task_pack",
    "task_structure",
    "prompt_family",
    "coordination_family",
]

SUPPORTED_FAMILY_SIZES: dict[str, set[int]] = {
    "single": {1},
    "independent": {2, 3, 5, 8},
    "centralized": {2, 3, 5, 8},
    "decentralized": {2, 3, 5, 8},
    "hybrid": {2, 3, 5, 8},
}

COORDINATION_FAMILY_LABELS = {
    "single": "single_solver_persistent_v1",
    "independent": "independent_selector_v1",
    "centralized": "centralized_hub_v1",
    "decentralized": "peer_network_v1",
    "hybrid": "hybrid_hub_lateral_review_v1",
}


class MatrixExampleSpec(BaseModel):
    example_id: str
    rationale: str


class MatrixTaskPack(BaseModel):
    task_structure: str
    rationale: str
    primary_examples: list[MatrixExampleSpec] = Field(default_factory=list)
    backup_examples: list[MatrixExampleSpec] = Field(default_factory=list)


class MatrixDefaults(BaseModel):
    harness: str = "claude-code"
    model: str | None = None
    prompt_family: str
    dimensions: list[str] = Field(default_factory=lambda: ACTIVE_DIMENSIONS.copy())
    judge_backend: str = "sdk"
    judge_model: str | None = None
    benchmark: dict[str, Any]
    single_limits: dict[str, Any] = Field(default_factory=dict)
    multi_agent_limits: dict[str, Any] = Field(default_factory=dict)
    direct_cli: bool = True
    on_turn_limit: str = "end"


class MatrixWave(BaseModel):
    families: list[str]
    sizes: list[int]
    anchor_pack: str | None = None
    anchor_example_id: str | None = None
    pack_examples: dict[str, int | str] = Field(default_factory=dict)
    notes: str | None = None


class MatrixManifest(BaseModel):
    matrix_id: str
    description: str = ""
    output_root: str | None = None
    defaults: MatrixDefaults
    task_packs: dict[str, MatrixTaskPack]
    waves: dict[str, MatrixWave]

    @model_validator(mode="after")
    def validate_manifest(self) -> "MatrixManifest":
        for wave_name, wave in self.waves.items():
            for family in wave.families:
                if family not in SUPPORTED_FAMILY_SIZES:
                    raise ValueError(f"Unknown architecture family `{family}` in {wave_name}")
            if wave.anchor_example_id and not wave.anchor_pack:
                raise ValueError(f"{wave_name} defines anchor_example_id without anchor_pack")
            if wave.anchor_pack and wave.anchor_pack not in self.task_packs:
                raise ValueError(f"{wave_name} references unknown anchor_pack `{wave.anchor_pack}`")
            for pack_name in wave.pack_examples:
                if pack_name not in self.task_packs:
                    raise ValueError(f"{wave_name} references unknown task pack `{pack_name}`")
        return self


@dataclass(frozen=True)
class RoleSpec:
    agent_id: str
    runtime_role: str | None
    prompt_kind: str
    closer: bool = False


@dataclass(frozen=True)
class GeneratedCondition:
    wave: str
    condition_id: str
    architecture_family: str
    swarm_size: int
    task_pack: str
    task_structure: str
    example_ids: list[str]
    prompt_family: str
    coordination_family: str
    runtime_pattern: str
    name: str
    description: str
    pattern_path: Path

    def matrix_metadata(self, matrix_id: str) -> dict[str, Any]:
        return {
            "matrix_id": matrix_id,
            "condition_id": self.condition_id,
            "architecture_family": self.architecture_family,
            "swarm_size": self.swarm_size,
            "task_pack": self.task_pack,
            "task_structure": self.task_structure,
            "prompt_family": self.prompt_family,
            "coordination_family": self.coordination_family,
        }


class _LiteralDumper(yaml.SafeDumper):
    pass


def _repr_multiline_str(dumper: yaml.SafeDumper, value: str) -> yaml.nodes.ScalarNode:
    style = "|" if "\n" in value else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", value, style=style)


_LiteralDumper.add_representer(str, _repr_multiline_str)


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
}


def load_matrix_manifest(path: Path) -> MatrixManifest:
    with open(path) as f:
        raw = yaml.safe_load(f)
    if not isinstance(raw, dict):
        raise ValueError(f"Matrix manifest must decode to a mapping: {path}")
    return MatrixManifest.model_validate(raw)


def _normalize_output_root(manifest: MatrixManifest, output_root: Path | None = None) -> Path:
    if output_root is not None:
        return output_root
    configured = manifest.output_root or f"patterns/generated/{manifest.matrix_id}"
    root = Path(configured)
    if root.is_absolute():
        return root
    return REPO_ROOT / root


def _pattern_runtime_label(family: str) -> str:
    if family == "single":
        return "single-agent"
    if family == "decentralized":
        return "peer-network"
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


def _build_prompt(family: str, layout: list[RoleSpec], role: RoleSpec) -> str:
    team_listing = _team_listing(layout)
    common_rules = _shared_benchmark_rules()
    coordination_overview = _coordination_overview(family, role)

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
- Respect the coordinator's overall plan, but use the lateral channels when local peer exchange is beneficial.
- Do not write the global done signal.
"""

    raise ValueError(f"Unsupported prompt kind `{role.prompt_kind}`")


def _build_agents(defaults: MatrixDefaults, family: str, size: int) -> list[dict[str, Any]]:
    layout = FAMILY_LAYOUTS[family][size]
    agents: list[dict[str, Any]] = []
    for role in layout:
        payload: dict[str, Any] = {
            "id": role.agent_id,
            "harness": defaults.harness,
            "system_prompt": _build_prompt(family, layout, role),
        }
        if defaults.model:
            payload["model"] = defaults.model
        if role.runtime_role:
            payload["role"] = role.runtime_role
        agents.append(payload)
    return agents


def _build_orchestrator(family: str) -> dict[str, Any]:
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


def _build_coordination(family: str) -> dict[str, Any]:
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


def _build_limits(defaults: MatrixDefaults, swarm_size: int) -> dict[str, Any]:
    base = defaults.single_limits if swarm_size == 1 else defaults.multi_agent_limits
    return dict(base)


def _build_evaluation(defaults: MatrixDefaults) -> dict[str, Any]:
    judge: dict[str, Any] = {"backend": defaults.judge_backend}
    if defaults.judge_model:
        judge["model"] = defaults.judge_model
    return {
        "dimensions": defaults.dimensions,
        "judge": judge,
    }


def _build_benchmark(defaults: MatrixDefaults, example_ids: list[str]) -> dict[str, Any]:
    benchmark = dict(defaults.benchmark)
    benchmark["example_ids"] = example_ids
    benchmark["max_examples"] = len(example_ids)
    return benchmark


def _condition_name(matrix_id: str, wave: str, family: str, size: int, task_pack: str) -> str:
    return f"{matrix_id}-{wave}-{family}-{size}-{task_pack}".replace("_", "-")


def _condition_description(
    family: str,
    size: int,
    task_pack: str,
    task_structure: str,
    example_ids: list[str],
) -> str:
    return (
        f"{family} architecture, swarm size {size}, task pack {task_pack} "
        f"({task_structure}), examples: {', '.join(example_ids)}"
    )


def _select_examples_for_wave(
    manifest: MatrixManifest,
    wave_name: str,
    wave: MatrixWave,
) -> list[tuple[str, str, list[str], str]]:
    if wave.anchor_example_id and wave.anchor_pack:
        pack = manifest.task_packs[wave.anchor_pack]
        return [
            (
                wave.anchor_pack,
                pack.task_structure,
                [wave.anchor_example_id],
                "anchor",
            )
        ]

    selected: list[tuple[str, str, list[str], str]] = []
    for pack_name, requested in wave.pack_examples.items():
        pack = manifest.task_packs[pack_name]
        example_ids = [example.example_id for example in pack.primary_examples]
        if requested == "all":
            chosen = example_ids
            label = "all"
        else:
            count = int(requested)
            chosen = example_ids[:count]
            label = str(count)
        if not chosen:
            continue
        selected.append((pack_name, pack.task_structure, chosen, label))
    return selected


def _build_condition(
    manifest: MatrixManifest,
    wave_name: str,
    family: str,
    size: int,
    task_pack: str,
    task_structure: str,
    example_ids: list[str],
    selection_label: str,
    output_root: Path,
) -> GeneratedCondition:
    condition_id = f"{wave_name}-{family}-{size}-{task_pack}-{selection_label}"
    name = _condition_name(manifest.matrix_id, wave_name, family, size, task_pack)
    description = _condition_description(
        family=family,
        size=size,
        task_pack=task_pack,
        task_structure=task_structure,
        example_ids=example_ids,
    )
    pattern_path = output_root / f"{name}.yaml"
    return GeneratedCondition(
        wave=wave_name,
        condition_id=condition_id,
        architecture_family=family,
        swarm_size=size,
        task_pack=task_pack,
        task_structure=task_structure,
        example_ids=example_ids,
        prompt_family=manifest.defaults.prompt_family,
        coordination_family=COORDINATION_FAMILY_LABELS[family],
        runtime_pattern=_pattern_runtime_label(family),
        name=name,
        description=description,
        pattern_path=pattern_path,
    )


def _write_pattern(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        yaml.dump(payload, f, Dumper=_LiteralDumper, sort_keys=False, width=100)


def _render_condition_payload(
    manifest: MatrixManifest,
    condition: GeneratedCondition,
) -> dict[str, Any]:
    agents = _build_agents(
        defaults=manifest.defaults,
        family=condition.architecture_family,
        size=condition.swarm_size,
    )
    payload = {
        "name": condition.name,
        "description": condition.description,
        "agents": agents,
        "orchestrator": _build_orchestrator(condition.architecture_family),
        "coordination": _build_coordination(condition.architecture_family),
        "benchmark": _build_benchmark(manifest.defaults, condition.example_ids),
        "evaluation": _build_evaluation(manifest.defaults),
        "limits": _build_limits(manifest.defaults, condition.swarm_size),
        "metadata": {
            "created": date.today().isoformat(),
            "version": 1,
            "matrix": condition.matrix_metadata(manifest.matrix_id),
        },
    }
    config = ExperimentConfig.model_validate(payload)
    return config.model_dump(mode="json", by_alias=True, exclude_none=True)


def generate_matrix_patterns(
    manifest_path: Path,
    *,
    output_root: Path | None = None,
    wave: str | None = None,
) -> dict[str, Any]:
    manifest = load_matrix_manifest(manifest_path)
    resolved_output_root = _normalize_output_root(manifest, output_root)
    resolved_output_root.mkdir(parents=True, exist_ok=True)

    selected_waves = (
        {wave: manifest.waves[wave]}
        if wave is not None
        else manifest.waves
    )

    conditions: list[GeneratedCondition] = []
    for wave_name, wave_config in selected_waves.items():
        if wave_name not in manifest.waves:
            raise ValueError(f"Unknown wave `{wave_name}`")
        pack_entries = _select_examples_for_wave(manifest, wave_name, wave_config)
        for family in wave_config.families:
            for size in wave_config.sizes:
                if size not in SUPPORTED_FAMILY_SIZES[family]:
                    continue
                for task_pack, task_structure, example_ids, selection_label in pack_entries:
                    conditions.append(
                        _build_condition(
                            manifest=manifest,
                            wave_name=wave_name,
                            family=family,
                            size=size,
                            task_pack=task_pack,
                            task_structure=task_structure,
                            example_ids=example_ids,
                            selection_label=selection_label,
                            output_root=resolved_output_root,
                        )
                    )

    written_conditions: list[dict[str, Any]] = []
    for condition in conditions:
        payload = _render_condition_payload(manifest, condition)
        _write_pattern(condition.pattern_path, payload)
        written_conditions.append(
            {
                "wave": condition.wave,
                "condition_id": condition.condition_id,
                "pattern_path": str(condition.pattern_path),
                "name": condition.name,
                "description": condition.description,
                "runtime_pattern": condition.runtime_pattern,
                "example_ids": condition.example_ids,
                **condition.matrix_metadata(manifest.matrix_id),
            }
        )

    matrix_payload = {
        "matrix_id": manifest.matrix_id,
        "description": manifest.description,
        "manifest_path": str(manifest_path),
        "output_root": str(resolved_output_root),
        "generated_at": datetime.now().isoformat(),
        "defaults": {
            "prompt_family": manifest.defaults.prompt_family,
            "direct_cli": manifest.defaults.direct_cli,
            "on_turn_limit": manifest.defaults.on_turn_limit,
            "dimensions": manifest.defaults.dimensions,
        },
        "conditions": written_conditions,
    }
    matrix_json = resolved_output_root / "matrix.json"
    with open(matrix_json, "w") as f:
        json.dump(matrix_payload, f, indent=2)

    return {
        "matrix_id": manifest.matrix_id,
        "manifest_path": str(manifest_path),
        "output_root": str(resolved_output_root),
        "matrix_json": str(matrix_json),
        "conditions": written_conditions,
    }


def load_matrix_json(path: Path) -> dict[str, Any]:
    with open(path) as f:
        payload = json.load(f)
    if not isinstance(payload, dict):
        raise ValueError(f"Matrix JSON must decode to an object: {path}")
    return payload


def record_condition_execution(
    matrix_payload: dict[str, Any],
    condition_id: str,
    execution_fields: dict[str, Any],
) -> dict[str, Any]:
    """Update one condition entry in-place without dropping pending conditions."""
    conditions = matrix_payload.get("conditions", [])
    if not isinstance(conditions, list):
        raise ValueError("matrix payload missing conditions list")

    for condition in conditions:
        if not isinstance(condition, dict):
            continue
        if condition.get("condition_id") != condition_id:
            continue
        condition.update(execution_fields)
        return condition

    raise KeyError(f"Unknown condition_id `{condition_id}`")


def _load_run_data(experiments_dir: Path, experiment_id: str) -> dict[str, Any]:
    run_data_path = experiments_dir / experiment_id / "run_data.json"
    if not run_data_path.exists():
        return {}
    with open(run_data_path) as f:
        payload = json.load(f)
    return payload if isinstance(payload, dict) else {}


def _load_transcript_usage(experiments_dir: Path, experiment_id: str) -> dict[str, int]:
    transcript_path = experiments_dir / experiment_id / "transcripts" / "full.json"
    if not transcript_path.exists():
        return {"input_tokens": 0, "output_tokens": 0}
    with open(transcript_path) as f:
        payload = json.load(f)
    if not isinstance(payload, dict):
        return {"input_tokens": 0, "output_tokens": 0}

    input_tokens = 0
    output_tokens = 0
    agents = payload.get("agents", {})
    if not isinstance(agents, dict):
        return {"input_tokens": 0, "output_tokens": 0}

    for agent_data in agents.values():
        if not isinstance(agent_data, dict):
            continue
        items = agent_data.get("items", [])
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            data = item.get("data", {})
            if not isinstance(data, dict):
                continue
            usage = data.get("usage")
            if not isinstance(usage, dict):
                raw = data.get("raw", {})
                if isinstance(raw, dict):
                    usage = raw.get("usage")
            if not isinstance(usage, dict):
                continue
            input_value = usage.get("input_tokens")
            output_value = usage.get("output_tokens")
            if isinstance(input_value, int):
                input_tokens += input_value
            if isinstance(output_value, int):
                output_tokens += output_value
    return {"input_tokens": input_tokens, "output_tokens": output_tokens}


def _flatten_matrix(matrix: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(matrix, dict):
        return {field: None for field in MATRIX_METADATA_FIELDS}
    return {field: matrix.get(field) for field in MATRIX_METADATA_FIELDS}


def _mode(values: list[str]) -> str | None:
    filtered = [value for value in values if value]
    if not filtered:
        return None
    return Counter(filtered).most_common(1)[0][0]


def analyze_matrix_summaries(
    summary_paths: list[Path],
    *,
    experiments_dir: Path | None = None,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    if not summary_paths:
        raise ValueError("Provide at least one summary path.")

    resolved_experiments_dir = experiments_dir or DEFAULT_EXPERIMENTS_DIR
    rows: list[dict[str, Any]] = []
    matrix_id: str | None = None

    for summary_path in summary_paths:
        with open(summary_path) as f:
            payload = json.load(f)
        if not isinstance(payload, dict):
            continue

        top_matrix = payload.get("matrix")
        if isinstance(top_matrix, dict) and matrix_id is None:
            matrix_id = str(top_matrix.get("matrix_id") or "")

        results = payload.get("results", [])
        if not isinstance(results, list):
            continue

        for result in results:
            if not isinstance(result, dict):
                continue
            experiment_id = result.get("experiment_id")
            if not isinstance(experiment_id, str):
                continue

            run_data = _load_run_data(resolved_experiments_dir, experiment_id)
            experiment = run_data.get("experiment", {})
            if not isinstance(experiment, dict):
                experiment = {}
            run = run_data.get("run", {})
            if not isinstance(run, dict):
                run = {}
            evals = run_data.get("evals", {})
            if not isinstance(evals, dict):
                evals = {}
            orchestration = evals.get("orchestration", {})
            if not isinstance(orchestration, dict):
                orchestration = {}
            judge = evals.get("judge", {})
            if not isinstance(judge, dict):
                judge = {}
            judge_scores = judge.get("scores", {})
            if not isinstance(judge_scores, dict):
                judge_scores = {}
            summary_judge_scores = result.get("judge_scores")
            if not isinstance(summary_judge_scores, dict):
                summary_judge_scores = {}

            matrix = experiment.get("matrix")
            if not isinstance(matrix, dict):
                candidate_matrix = result.get("matrix")
                matrix = candidate_matrix if isinstance(candidate_matrix, dict) else None
            if matrix_id is None and isinstance(matrix, dict):
                matrix_id = str(matrix.get("matrix_id") or "")

            task_verification = run.get("task_verification", {})
            if not isinstance(task_verification, dict):
                task_verification = {}
            usage = _load_transcript_usage(resolved_experiments_dir, experiment_id)
            flattened_matrix = _flatten_matrix(matrix)

            row: dict[str, Any] = {
                "summary_path": str(summary_path),
                "experiment_id": experiment_id,
                "example_id": result.get("example_id"),
                "pattern": experiment.get("pattern") or result.get("pattern"),
                "run_success": run.get("success", result.get("success")),
                "run_outcome": run.get("outcome", result.get("outcome")),
                "termination_reason": run.get(
                    "termination_reason",
                    result.get("termination_reason"),
                ),
                "system_failure": run.get("system_failure", result.get("system_failure")),
                "task_verification_status": task_verification.get(
                    "status",
                    result.get("task_verification_status"),
                ),
                "task_verification_score": task_verification.get(
                    "score",
                    result.get("task_verification_score"),
                ),
                "duration_seconds": run.get("duration_seconds", result.get("duration_seconds")),
                "parallelism_efficiency": orchestration.get("parallelism_efficiency", {}).get("value"),
                "coordination_to_output_ratio": orchestration.get("coordination_overhead", {}).get(
                    "coordination_to_output_ratio"
                ),
                "input_tokens": usage["input_tokens"],
                "output_tokens": usage["output_tokens"],
                "matrix": matrix,
                **flattened_matrix,
            }
            for dim in ACTIVE_DIMENSIONS:
                payload = judge_scores.get(dim, {})
                if (
                    not isinstance(payload, dict)
                    or not isinstance(payload.get("category"), str)
                    or not payload.get("category")
                ):
                    payload = summary_judge_scores.get(dim, {})
                if isinstance(payload, dict):
                    row[dim] = payload.get("category")
                else:
                    row[dim] = None
            rows.append(row)

    def _avg(field: str, group_rows: list[dict[str, Any]]) -> float | None:
        values = [float(row[field]) for row in group_rows if isinstance(row.get(field), (int, float))]
        if not values:
            return None
        return mean(values)

    grouped: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        key = (
            row.get("architecture_family"),
            row.get("swarm_size"),
            row.get("task_pack"),
            row.get("task_structure"),
        )
        grouped[key].append(row)

    condition_summaries: list[dict[str, Any]] = []
    for key, group_rows in sorted(grouped.items(), key=lambda item: tuple(str(v) for v in item[0])):
        family, size, task_pack, task_structure = key
        run_count = len(group_rows)
        completed = sum(1 for row in group_rows if row.get("run_outcome") == "completed")
        turn_limit = sum(1 for row in group_rows if row.get("termination_reason") == "turn_limit")
        modal_dimensions = {
            dim: _mode([str(row.get(dim) or "") for row in group_rows])
            for dim in ACTIVE_DIMENSIONS
        }
        failure_modes = Counter(
            str(row.get("termination_reason") or "unknown")
            for row in group_rows
            if row.get("run_outcome") != "completed"
        )
        condition_summaries.append(
            {
                "architecture_family": family,
                "swarm_size": size,
                "task_pack": task_pack,
                "task_structure": task_structure,
                "runs": run_count,
                "clean_completion_rate": completed / run_count if run_count else None,
                "turn_limit_incomplete_rate": turn_limit / run_count if run_count else None,
                "avg_task_score": _avg("task_verification_score", group_rows),
                "avg_duration_seconds": _avg("duration_seconds", group_rows),
                "avg_parallelism_efficiency": _avg("parallelism_efficiency", group_rows),
                "avg_coordination_to_output_ratio": _avg("coordination_to_output_ratio", group_rows),
                "avg_input_tokens": _avg("input_tokens", group_rows),
                "avg_output_tokens": _avg("output_tokens", group_rows),
                "modal_dimensions": modal_dimensions,
                "top_failure_modes": dict(failure_modes.most_common(3)),
            }
        )

    benchmark_flat_differences: list[dict[str, Any]] = []
    per_example: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        example_id = row.get("example_id")
        score = row.get("task_verification_score")
        if not isinstance(example_id, str) or not isinstance(score, (int, float)):
            continue
        per_example[(example_id, f"{float(score):.3f}")].append(row)

    for (example_id, score), group_rows in sorted(per_example.items()):
        if len(group_rows) < 2:
            continue
        signatures = {
            (
                row.get("run_outcome"),
                row.get("termination_reason"),
                tuple(row.get(dim) for dim in ACTIVE_DIMENSIONS),
            )
            for row in group_rows
        }
        if len(signatures) <= 1:
            continue
        benchmark_flat_differences.append(
            {
                "example_id": example_id,
                "task_verification_score": float(score),
                "rows": [
                    {
                        "experiment_id": row.get("experiment_id"),
                        "pattern": row.get("pattern"),
                        "architecture_family": row.get("architecture_family"),
                        "swarm_size": row.get("swarm_size"),
                        "run_outcome": row.get("run_outcome"),
                        "termination_reason": row.get("termination_reason"),
                        "behavior": {
                            dim: row.get(dim)
                            for dim in ACTIVE_DIMENSIONS
                        },
                    }
                    for row in group_rows
                ],
            }
        )

    failure_mode_rows: list[dict[str, Any]] = []
    by_family_size: dict[tuple[Any, Any], Counter[str]] = defaultdict(Counter)
    for row in rows:
        if row.get("run_outcome") == "completed":
            continue
        key = (row.get("architecture_family"), row.get("swarm_size"))
        by_family_size[key][str(row.get("termination_reason") or "unknown")] += 1
    for (family, size), counter in sorted(by_family_size.items(), key=lambda item: tuple(str(v) for v in item[0])):
        for label, count in counter.most_common():
            failure_mode_rows.append(
                {
                    "architecture_family": family,
                    "swarm_size": size,
                    "failure_mode": label,
                    "count": count,
                }
            )

    summary: dict[str, Any] = {
        "matrix_id": matrix_id,
        "generated_at": datetime.now().isoformat(),
        "summary_paths": [str(path) for path in summary_paths],
        "experiments_dir": str(resolved_experiments_dir),
        "row_count": len(rows),
        "condition_summaries": condition_summaries,
        "benchmark_flat_behavior_differences": benchmark_flat_differences,
        "failure_modes": failure_mode_rows,
        "rows": rows,
    }

    report_lines = [
        "# Matrix Report",
        "",
        f"- Matrix ID: `{matrix_id or 'unknown'}`",
        f"- Summary files: {len(summary_paths)}",
        f"- Rows analyzed: {len(rows)}",
        "",
        "## Condition Summaries",
        "",
        "| family | size | task_pack | task_structure | runs | avg_score | clean_completion | turn_limit_rate | avg_parallel | avg_coord_ratio | avg_duration_s | EC | GD | FS | CD | RW |",
        "|---|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---|---|---|---|---|",
    ]

    for item in condition_summaries:
        report_lines.append(
            "| "
            + f"{item.get('architecture_family') or 'n/a'} | "
            + f"{item.get('swarm_size') or 'n/a'} | "
            + f"{item.get('task_pack') or 'n/a'} | "
            + f"{item.get('task_structure') or 'n/a'} | "
            + f"{item.get('runs') or 0} | "
            + (
                f"{item['avg_task_score']:.3f}"
                if isinstance(item.get("avg_task_score"), (int, float))
                else "n/a"
            )
            + " | "
            + (
                f"{item['clean_completion_rate']:.3f}"
                if isinstance(item.get("clean_completion_rate"), (int, float))
                else "n/a"
            )
            + " | "
            + (
                f"{item['turn_limit_incomplete_rate']:.3f}"
                if isinstance(item.get("turn_limit_incomplete_rate"), (int, float))
                else "n/a"
            )
            + " | "
            + (
                f"{item['avg_parallelism_efficiency']:.3f}"
                if isinstance(item.get("avg_parallelism_efficiency"), (int, float))
                else "n/a"
            )
            + " | "
            + (
                f"{item['avg_coordination_to_output_ratio']:.3f}"
                if isinstance(item.get("avg_coordination_to_output_ratio"), (int, float))
                else "n/a"
            )
            + " | "
            + (
                f"{item['avg_duration_seconds']:.1f}"
                if isinstance(item.get("avg_duration_seconds"), (int, float))
                else "n/a"
            )
            + " | "
            + " | ".join(
                item.get("modal_dimensions", {}).get(dim) or "n/a"
                for dim in ACTIVE_DIMENSIONS
            )
            + " |"
        )

    if benchmark_flat_differences:
        report_lines.extend(["", "## Benchmark-Flat Behavioral Differences", ""])
        for item in benchmark_flat_differences:
            report_lines.append(
                f"- `{item['example_id']}` at score `{item['task_verification_score']:.3f}`:"
            )
            for row in item["rows"]:
                profile = ", ".join(
                    f"{dim}={row['behavior'].get(dim) or 'n/a'}"
                    for dim in ACTIVE_DIMENSIONS
                )
                report_lines.append(
                    "  - "
                    + f"`{row.get('architecture_family')}` size `{row.get('swarm_size')}` "
                    + f"({row.get('pattern')}) -> `{row.get('run_outcome')}` "
                    + f"/ `{row.get('termination_reason')}`; {profile}"
                )

    if failure_mode_rows:
        report_lines.extend(
            [
                "",
                "## Top Failure Modes By Family/Size",
                "",
                "| family | size | failure_mode | count |",
                "|---|---:|---|---:|",
            ]
        )
        for row in failure_mode_rows:
            report_lines.append(
                "| "
                + f"{row['architecture_family']} | {row['swarm_size']} | "
                + f"{row['failure_mode']} | {row['count']} |"
            )

    report_text = "\n".join(report_lines)
    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)
        summary_path = output_dir / "matrix-summary.json"
        report_path = output_dir / "matrix-report.md"
        with open(summary_path, "w") as f:
            json.dump(summary, f, indent=2)
        with open(report_path, "w") as f:
            f.write(report_text)
        summary["summary_path"] = str(summary_path)
        summary["report_path"] = str(report_path)

    return summary
