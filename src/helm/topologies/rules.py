"""Topology enforcement rules — which tools are blocked per family/role."""

from __future__ import annotations

TOPOLOGY_RULES: dict[tuple[str, str], list[str]] = {
    # Single: true single agent, no delegation or messaging
    ("single", "solver"): ["Agent", "TeamCreate", "SendMessage"],
    # Independent: isolated candidates, no cross-communication
    # RoleSpec uses runtime_role "worker" and "hub" for independent family
    ("independent", "worker"): ["Agent", "TeamCreate", "SendMessage"],
    ("independent", "hub"): ["Agent", "TeamCreate", "SendMessage"],
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

