"""Topology family layouts and configuration constants."""

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
