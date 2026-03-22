"""Topology compliance analysis for Helm experiments.

Extracts structural coordination evidence from experiment transcripts
and measures whether agents followed the prescribed topology.

This module treats violations as data, not errors. A "centralized" experiment
where workers spawn subagents or communicate laterally is still valid data —
it tells us the prompt-steered topology was not fully respected.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# Tools that indicate structural coordination behavior
SUBAGENT_TOOLS = {"Agent", "TeamCreate"}
MESSAGING_TOOLS = {"SendMessage"}
FILESYSTEM_TOOLS = {"Read", "Write", "Edit", "Glob", "Grep"}


@dataclass
class AgentCompliance:
    """Compliance data for a single agent in an experiment."""

    agent_id: str
    role: str | None
    tool_counts: dict[str, int] = field(default_factory=dict)
    subagent_spawns: int = 0
    send_messages: list[dict[str, str]] = field(default_factory=list)
    coordination_reads: list[str] = field(default_factory=list)
    coordination_writes: list[str] = field(default_factory=list)
    workspace_reads: list[str] = field(default_factory=list)
    workspace_writes: list[str] = field(default_factory=list)

    @property
    def used_subagents(self) -> bool:
        return self.subagent_spawns > 0

    @property
    def used_native_messaging(self) -> bool:
        return len(self.send_messages) > 0

    def peers_messaged(self) -> set[str]:
        return {m["to"] for m in self.send_messages if "to" in m}


@dataclass
class TopologyCompliance:
    """Compliance analysis for a full experiment."""

    experiment_id: str
    prescribed_family: str
    prescribed_pattern: str
    agent_count: int
    agents: dict[str, AgentCompliance] = field(default_factory=dict)

    # Violations
    subagent_spawns_total: int = 0
    native_messaging_total: int = 0
    lateral_communication_events: int = 0
    agents_with_subagents: list[str] = field(default_factory=list)
    agents_with_lateral_comms: list[str] = field(default_factory=list)

    # Compliance scores (0.0 = fully violated, 1.0 = fully compliant)
    hierarchy_compliance: float | None = None
    lateral_compliance: float | None = None
    protocol_compliance: float | None = None
    overall_compliance: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "experiment_id": self.experiment_id,
            "prescribed_family": self.prescribed_family,
            "prescribed_pattern": self.prescribed_pattern,
            "agent_count": self.agent_count,
            "subagent_spawns_total": self.subagent_spawns_total,
            "native_messaging_total": self.native_messaging_total,
            "lateral_communication_events": self.lateral_communication_events,
            "agents_with_subagents": self.agents_with_subagents,
            "agents_with_lateral_comms": self.agents_with_lateral_comms,
            "hierarchy_compliance": self.hierarchy_compliance,
            "lateral_compliance": self.lateral_compliance,
            "protocol_compliance": self.protocol_compliance,
            "overall_compliance": self.overall_compliance,
            "per_agent": {
                aid: {
                    "role": ac.role,
                    "tool_counts": ac.tool_counts,
                    "subagent_spawns": ac.subagent_spawns,
                    "send_messages": ac.send_messages,
                    "coordination_reads": len(ac.coordination_reads),
                    "coordination_writes": len(ac.coordination_writes),
                    "used_subagents": ac.used_subagents,
                    "used_native_messaging": ac.used_native_messaging,
                }
                for aid, ac in self.agents.items()
            },
        }


def _extract_tool_uses(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Extract tool_use blocks from agent transcript items."""
    tool_uses = []
    for item in items:
        if item.get("event_type") != "item.completed":
            continue
        raw = item.get("data", {})
        if isinstance(raw, str):
            continue
        raw_item = raw.get("item", {})
        if not isinstance(raw_item, dict):
            continue
        content = raw_item.get("content", [])
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                tool_uses.append(block)
    return tool_uses


def analyze_experiment(experiment_dir: Path) -> TopologyCompliance:
    """Analyze topology compliance for a single experiment."""
    transcript_path = experiment_dir / "transcripts" / "full.json"
    metadata_path = experiment_dir / "metadata.json"

    with open(transcript_path) as f:
        transcript = json.load(f)
    with open(metadata_path) as f:
        metadata = json.load(f)

    # Extract prescribed topology
    matrix = metadata.get("matrix", {})
    family = matrix.get("architecture_family", metadata.get("pattern", "unknown"))
    pattern = metadata.get("pattern", "unknown")
    agents_meta = metadata.get("agents", [])

    # Build role map from metadata
    role_map: dict[str, str | None] = {}
    for a in agents_meta:
        role_map[a.get("id", "")] = a.get("role")

    # Hub agent IDs (for lateral communication detection)
    hub_agents = {a.get("id") for a in agents_meta if a.get("role") == "hub"}
    worker_agents = {a.get("id") for a in agents_meta if a.get("role") in ("worker", "peer", None)}

    agents_data = transcript.get("agents", {})
    result = TopologyCompliance(
        experiment_id=experiment_dir.name,
        prescribed_family=family,
        prescribed_pattern=pattern,
        agent_count=len(agents_data),
    )

    for agent_id, agent_transcript in agents_data.items():
        items = agent_transcript.get("items", []) if isinstance(agent_transcript, dict) else []
        tool_uses = _extract_tool_uses(items)

        ac = AgentCompliance(
            agent_id=agent_id,
            role=role_map.get(agent_id),
        )

        tool_counts: Counter[str] = Counter()
        for tu in tool_uses:
            name = tu.get("name", "?")
            tool_counts[name] += 1
            inp = tu.get("input", {})
            if not isinstance(inp, dict):
                inp = {}

            # Subagent spawning
            if name in SUBAGENT_TOOLS:
                ac.subagent_spawns += 1
                result.subagent_spawns_total += 1

            # Native messaging
            if name in MESSAGING_TOOLS:
                msg_to = str(inp.get("to", ""))
                msg_content = str(inp.get("content", inp.get("message", "")))[:200]
                ac.send_messages.append({"to": msg_to, "content": msg_content})
                result.native_messaging_total += 1

                # Detect lateral communication (worker → worker, bypassing hub)
                if agent_id in worker_agents and msg_to in worker_agents:
                    result.lateral_communication_events += 1

            # Filesystem coordination access
            if name in FILESYSTEM_TOOLS:
                fp = str(inp.get("file_path", inp.get("path", "")))
                if "coordination/" in fp:
                    if name in ("Read", "Glob", "Grep"):
                        ac.coordination_reads.append(fp)
                    else:
                        ac.coordination_writes.append(fp)
                elif "workspace/" in fp:
                    if name in ("Read", "Glob", "Grep"):
                        ac.workspace_reads.append(fp)
                    else:
                        ac.workspace_writes.append(fp)

        ac.tool_counts = dict(tool_counts)
        result.agents[agent_id] = ac

        if ac.used_subagents:
            result.agents_with_subagents.append(agent_id)

    # Detect lateral communication from SendMessage patterns
    for agent_id, ac in result.agents.items():
        if agent_id in worker_agents and ac.used_native_messaging:
            peers_reached = ac.peers_messaged()
            if peers_reached & worker_agents:
                result.agents_with_lateral_comms.append(agent_id)

    # Compute compliance scores
    result.hierarchy_compliance = _score_hierarchy_compliance(result)
    result.lateral_compliance = _score_lateral_compliance(result, family)
    result.protocol_compliance = _score_protocol_compliance(result)
    result.overall_compliance = _score_overall(result)

    return result


def _score_hierarchy_compliance(r: TopologyCompliance) -> float:
    """1.0 = no subagent spawning (flat hierarchy preserved). 0.0 = every agent spawned subagents."""
    if r.agent_count <= 1:
        return 1.0
    violators = len(r.agents_with_subagents)
    return 1.0 - (violators / r.agent_count)


def _score_lateral_compliance(r: TopologyCompliance, family: str) -> float:
    """Score lateral communication compliance based on family rules."""
    if family == "single":
        return 1.0  # N/A for single agent
    if family in ("decentralized", "hybrid"):
        return 1.0  # Lateral is allowed
    # centralized, independent: lateral should NOT occur
    if r.agent_count <= 1:
        return 1.0
    worker_count = sum(1 for ac in r.agents.values() if ac.role in ("worker", None))
    if worker_count == 0:
        return 1.0
    violators = len(r.agents_with_lateral_comms)
    return 1.0 - (violators / max(worker_count, 1))


def _score_protocol_compliance(r: TopologyCompliance) -> float:
    """Score whether agents used the prescribed coordination protocol (filesystem)
    vs native tools (SendMessage, Agent)."""
    total_coord_actions = 0
    native_actions = 0
    for ac in r.agents.values():
        total_coord_actions += len(ac.coordination_reads) + len(ac.coordination_writes)
        total_coord_actions += len(ac.send_messages)
        native_actions += len(ac.send_messages) + ac.subagent_spawns

    if total_coord_actions == 0:
        return 0.0  # No coordination at all
    return 1.0 - (native_actions / total_coord_actions)


def _score_overall(r: TopologyCompliance) -> float:
    """Weighted average of compliance dimensions."""
    scores = [s for s in [r.hierarchy_compliance, r.lateral_compliance, r.protocol_compliance] if s is not None]
    if not scores:
        return 0.0
    return sum(scores) / len(scores)


def analyze_batch(experiment_dirs: list[Path]) -> list[TopologyCompliance]:
    """Analyze topology compliance for a batch of experiments."""
    results = []
    for exp_dir in experiment_dirs:
        transcript_path = exp_dir / "transcripts" / "full.json"
        metadata_path = exp_dir / "metadata.json"
        if transcript_path.exists() and metadata_path.exists():
            results.append(analyze_experiment(exp_dir))
    return results


def format_report(results: list[TopologyCompliance]) -> str:
    """Format a compliance report as markdown."""
    lines = [
        "# Topology Compliance Report",
        "",
        "| Experiment | Family | Agents | Subagent Spawns | Native Msgs | Lateral | Hierarchy | Lateral Compliance | Protocol | Overall |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]

    for r in results:
        short_id = r.experiment_id
        # Truncate long IDs
        if len(short_id) > 50:
            parts = short_id.split("-")
            short_id = "-".join(parts[:6]) + "..." + parts[-1]

        lines.append(
            f"| {short_id} "
            f"| {r.prescribed_family} "
            f"| {r.agent_count} "
            f"| {r.subagent_spawns_total} "
            f"| {r.native_messaging_total} "
            f"| {r.lateral_communication_events} "
            f"| {r.hierarchy_compliance:.2f} "
            f"| {r.lateral_compliance:.2f} "
            f"| {r.protocol_compliance:.2f} "
            f"| {r.overall_compliance:.2f} |"
        )

    # Summary
    if results:
        avg_overall = sum(r.overall_compliance or 0 for r in results) / len(results)
        total_spawns = sum(r.subagent_spawns_total for r in results)
        total_native = sum(r.native_messaging_total for r in results)
        total_lateral = sum(r.lateral_communication_events for r in results)

        lines.extend([
            "",
            "## Summary",
            "",
            f"- Experiments analyzed: {len(results)}",
            f"- Total subagent spawns: {total_spawns}",
            f"- Total native messages (SendMessage): {total_native}",
            f"- Total lateral communication events: {total_lateral}",
            f"- Average overall compliance: {avg_overall:.2f}",
        ])

    return "\n".join(lines)
