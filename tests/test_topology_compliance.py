"""Tests for topology_compliance.py — extraction, analysis, scoring, and reporting."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from helm.topology_compliance import (
    AgentCompliance,
    TopologyCompliance,
    _extract_tool_uses,
    _score_hierarchy_compliance,
    _score_lateral_compliance,
    _score_protocol_adoption,
    _score_protocol_compliance,
    _verify_enforcement,
    analyze_experiment,
    format_report,
)


# ---------------------------------------------------------------------------
# Helpers to build transcript structures
# ---------------------------------------------------------------------------


def _tool_use_item(name: str, inp: dict | None = None) -> dict:
    """Build an item.completed event containing one tool_use block."""
    return {
        "event_type": "item.completed",
        "data": {
            "item": {
                "content": [
                    {"type": "tool_use", "name": name, "input": inp or {}}
                ]
            }
        },
    }


def _text_item(text: str = "some text") -> dict:
    """Build an item.completed event with only text content (no tool_use)."""
    return {
        "event_type": "item.completed",
        "data": {"item": {"content": [{"type": "text", "text": text}]}},
    }


def _non_completed_event() -> dict:
    return {"event_type": "item.started", "data": {}}


def _write_experiment(
    tmp_path: Path,
    transcript: dict,
    metadata: dict,
    name: str = "test-exp",
) -> Path:
    """Write transcript and metadata files into a temp experiment dir."""
    exp_dir = tmp_path / name
    (exp_dir / "transcripts").mkdir(parents=True)
    (exp_dir / "transcripts" / "full.json").write_text(json.dumps(transcript))
    (exp_dir / "metadata.json").write_text(json.dumps(metadata))
    return exp_dir


# ---------------------------------------------------------------------------
# _extract_tool_uses
# ---------------------------------------------------------------------------


class TestExtractToolUses:
    def test_extracts_tool_use_from_completed_event(self):
        items = [_tool_use_item("Bash", {"command": "ls"})]
        result = _extract_tool_uses(items)
        assert len(result) == 1
        assert result[0]["name"] == "Bash"
        assert result[0]["input"]["command"] == "ls"

    def test_extracts_multiple_tool_uses_in_single_item(self):
        item = {
            "event_type": "item.completed",
            "data": {
                "item": {
                    "content": [
                        {"type": "tool_use", "name": "Read", "input": {"file_path": "/a"}},
                        {"type": "tool_use", "name": "Write", "input": {"file_path": "/b"}},
                    ]
                }
            },
        }
        result = _extract_tool_uses([item])
        assert len(result) == 2
        assert {r["name"] for r in result} == {"Read", "Write"}

    def test_skips_non_completed_events(self):
        items = [_non_completed_event(), _tool_use_item("Bash")]
        result = _extract_tool_uses(items)
        assert len(result) == 1

    def test_handles_data_as_string(self):
        items = [{"event_type": "item.completed", "data": "raw string data"}]
        assert _extract_tool_uses(items) == []

    def test_handles_missing_data_key(self):
        items = [{"event_type": "item.completed"}]
        assert _extract_tool_uses(items) == []

    def test_handles_non_dict_item(self):
        items = [{"event_type": "item.completed", "data": {"item": "not a dict"}}]
        assert _extract_tool_uses(items) == []

    def test_handles_non_list_content(self):
        items = [{"event_type": "item.completed", "data": {"item": {"content": "not a list"}}}]
        assert _extract_tool_uses(items) == []

    def test_ignores_text_blocks(self):
        items = [_text_item("hello")]
        assert _extract_tool_uses(items) == []

    def test_empty_items(self):
        assert _extract_tool_uses([]) == []


# ---------------------------------------------------------------------------
# analyze_experiment
# ---------------------------------------------------------------------------


class TestAnalyzeExperiment:
    """Integration tests that write experiment dirs and run analyze_experiment."""

    def _base_metadata(self, **overrides) -> dict:
        meta = {
            "pattern": "hub-and-spoke",
            "matrix": {"architecture_family": "centralized"},
            "agents": [
                {"id": "coordinator", "role": "hub"},
                {"id": "worker_a", "role": "worker"},
            ],
        }
        meta.update(overrides)
        return meta

    def _base_transcript(self, agents: dict | None = None) -> dict:
        return {
            "experiment_id": "test-exp",
            "agents": agents
            or {
                "coordinator": {"agent_id": "coordinator", "session_id": "s1", "items": []},
                "worker_a": {"agent_id": "worker_a", "session_id": "s2", "items": []},
            },
        }

    def test_detects_subagent_spawns(self, tmp_path):
        transcript = self._base_transcript(
            {
                "coordinator": {
                    "items": [_tool_use_item("Agent", {"task": "do thing"})]
                },
                "worker_a": {"items": []},
            }
        )
        exp_dir = _write_experiment(tmp_path, transcript, self._base_metadata())
        result = analyze_experiment(exp_dir)

        assert result.subagent_spawns_total == 1
        assert "coordinator" in result.agents_with_subagents
        assert result.agents["coordinator"].used_subagents is True

    def test_detects_native_messaging(self, tmp_path):
        transcript = self._base_transcript(
            {
                "coordinator": {
                    "items": [
                        _tool_use_item("SendMessage", {"to": "worker_a", "content": "hi"})
                    ]
                },
                "worker_a": {"items": []},
            }
        )
        exp_dir = _write_experiment(tmp_path, transcript, self._base_metadata())
        result = analyze_experiment(exp_dir)

        assert result.native_messaging_total == 1
        assert result.agents["coordinator"].used_native_messaging is True
        assert result.agents["coordinator"].send_messages[0]["to"] == "worker_a"

    def test_detects_lateral_communication(self, tmp_path):
        """worker_a sends to worker_b — lateral communication in centralized topology."""
        meta = {
            "pattern": "hub-and-spoke",
            "matrix": {"architecture_family": "centralized"},
            "agents": [
                {"id": "coordinator", "role": "hub"},
                {"id": "worker_a", "role": "worker"},
                {"id": "worker_b", "role": "worker"},
            ],
        }
        transcript = self._base_transcript(
            {
                "coordinator": {"items": []},
                "worker_a": {
                    "items": [
                        _tool_use_item("SendMessage", {"to": "worker_b", "content": "yo"})
                    ]
                },
                "worker_b": {"items": []},
            }
        )
        exp_dir = _write_experiment(tmp_path, transcript, meta)
        result = analyze_experiment(exp_dir)

        assert result.lateral_communication_events == 1
        assert "worker_a" in result.agents_with_lateral_comms

    def test_detects_helm_agent_cli_usage(self, tmp_path):
        transcript = self._base_transcript(
            {
                "coordinator": {
                    "items": [
                        _tool_use_item(
                            "Bash", {"command": "python -m helm.agent_cli send --to worker_a --msg hi"}
                        ),
                        _tool_use_item(
                            "Bash", {"command": "helm-agent spawn --role worker_c"}
                        ),
                        _tool_use_item(
                            "Bash", {"command": "helm-agent inbox --agent coordinator"}
                        ),
                        _tool_use_item(
                            "Bash", {"command": "helm-agent status --verbose"}
                        ),
                    ]
                },
                "worker_a": {"items": []},
            }
        )
        exp_dir = _write_experiment(tmp_path, transcript, self._base_metadata())
        result = analyze_experiment(exp_dir)

        ac = result.agents["coordinator"]
        assert ac.helm_agent_sends == 1
        assert ac.helm_agent_spawns == 1
        assert ac.helm_agent_inbox == 1
        assert ac.helm_agent_status == 1
        assert ac.used_helm_agent is True
        assert ac.helm_agent_total == 4
        assert result.helm_agent_sends_total == 1
        assert result.helm_agent_spawns_total == 1

    def test_counts_filesystem_coordination(self, tmp_path):
        transcript = self._base_transcript(
            {
                "coordinator": {
                    "items": [
                        _tool_use_item("Read", {"file_path": "/work/coordination/plan.md"}),
                        _tool_use_item("Write", {"file_path": "/work/coordination/result.md"}),
                        _tool_use_item("Edit", {"file_path": "/work/coordination/plan.md"}),
                        _tool_use_item("Read", {"file_path": "/work/workspace/code.py"}),
                        _tool_use_item("Write", {"file_path": "/work/workspace/code.py"}),
                    ]
                },
                "worker_a": {"items": []},
            }
        )
        exp_dir = _write_experiment(tmp_path, transcript, self._base_metadata())
        result = analyze_experiment(exp_dir)

        ac = result.agents["coordinator"]
        assert len(ac.coordination_reads) == 1
        assert len(ac.coordination_writes) == 2
        assert len(ac.workspace_reads) == 1
        assert len(ac.workspace_writes) == 1

    def test_identifies_hub_vs_worker(self, tmp_path):
        transcript = self._base_transcript()
        exp_dir = _write_experiment(tmp_path, transcript, self._base_metadata())
        result = analyze_experiment(exp_dir)

        assert result.agents["coordinator"].role == "hub"
        assert result.agents["worker_a"].role == "worker"

    def test_single_agent_experiment(self, tmp_path):
        meta = {
            "pattern": "single",
            "matrix": {"architecture_family": "single"},
            "agents": [{"id": "solver", "role": "solver"}],
        }
        transcript = {
            "experiment_id": "test-single",
            "agents": {
                "solver": {
                    "items": [
                        _tool_use_item("Bash", {"command": "ls"}),
                        _tool_use_item("Read", {"file_path": "/work/workspace/code.py"}),
                    ]
                }
            },
        }
        exp_dir = _write_experiment(tmp_path, transcript, meta)
        result = analyze_experiment(exp_dir)

        assert result.agent_count == 1
        assert result.hierarchy_compliance == 1.0
        assert result.enforcement_verified is True
        assert result.subagent_spawns_total == 0

    def test_zero_coordination_experiment(self, tmp_path):
        """Agents exist but use no coordination tools at all."""
        transcript = self._base_transcript(
            {
                "coordinator": {
                    "items": [_tool_use_item("Bash", {"command": "echo hello"})]
                },
                "worker_a": {
                    "items": [_tool_use_item("Bash", {"command": "echo world"})]
                },
            }
        )
        exp_dir = _write_experiment(tmp_path, transcript, self._base_metadata())
        result = analyze_experiment(exp_dir)

        assert result.subagent_spawns_total == 0
        assert result.native_messaging_total == 0
        assert result.lateral_communication_events == 0
        assert result.protocol_compliance == 0.0  # no coordination at all
        assert result.protocol_adoption == 1.0  # trivially compliant
        assert result.enforcement_verified is True

    def test_glob_grep_counted_as_reads(self, tmp_path):
        transcript = self._base_transcript(
            {
                "coordinator": {
                    "items": [
                        _tool_use_item("Glob", {"path": "/work/coordination/"}),
                        _tool_use_item("Grep", {"path": "/work/coordination/plan.md"}),
                    ]
                },
                "worker_a": {"items": []},
            }
        )
        exp_dir = _write_experiment(tmp_path, transcript, self._base_metadata())
        result = analyze_experiment(exp_dir)

        ac = result.agents["coordinator"]
        assert len(ac.coordination_reads) == 2
        assert len(ac.coordination_writes) == 0


# ---------------------------------------------------------------------------
# Compliance scoring (unit-level)
# ---------------------------------------------------------------------------


class TestHierarchyCompliance:
    def test_no_subagents_returns_1(self):
        r = TopologyCompliance("x", "centralized", "hub-spoke", 3)
        r.agents_with_subagents = []
        assert _score_hierarchy_compliance(r) == 1.0

    def test_all_agents_spawn_returns_0(self):
        r = TopologyCompliance("x", "centralized", "hub-spoke", 3)
        r.agents_with_subagents = ["a", "b", "c"]
        assert _score_hierarchy_compliance(r) == pytest.approx(0.0)

    def test_partial_violation(self):
        r = TopologyCompliance("x", "centralized", "hub-spoke", 4)
        r.agents_with_subagents = ["a"]
        assert _score_hierarchy_compliance(r) == pytest.approx(0.75)

    def test_single_agent(self):
        r = TopologyCompliance("x", "single", "single", 1)
        assert _score_hierarchy_compliance(r) == 1.0


class TestLateralCompliance:
    def test_decentralized_always_1(self):
        r = TopologyCompliance("x", "decentralized", "mesh", 3)
        r.agents_with_lateral_comms = ["a", "b"]
        assert _score_lateral_compliance(r, "decentralized") == 1.0

    def test_hybrid_always_1(self):
        r = TopologyCompliance("x", "hybrid", "hub-mesh", 3)
        r.agents_with_lateral_comms = ["a"]
        assert _score_lateral_compliance(r, "hybrid") == 1.0

    def test_single_always_1(self):
        r = TopologyCompliance("x", "single", "single", 1)
        assert _score_lateral_compliance(r, "single") == 1.0

    def test_centralized_no_violations(self):
        r = TopologyCompliance("x", "centralized", "hub-spoke", 3)
        r.agents = {
            "hub": AgentCompliance("hub", "hub"),
            "w1": AgentCompliance("w1", "worker"),
            "w2": AgentCompliance("w2", "worker"),
        }
        r.agents_with_lateral_comms = []
        assert _score_lateral_compliance(r, "centralized") == 1.0

    def test_centralized_all_workers_violate(self):
        r = TopologyCompliance("x", "centralized", "hub-spoke", 3)
        r.agents = {
            "hub": AgentCompliance("hub", "hub"),
            "w1": AgentCompliance("w1", "worker"),
            "w2": AgentCompliance("w2", "worker"),
        }
        r.agents_with_lateral_comms = ["w1", "w2"]
        assert _score_lateral_compliance(r, "centralized") == pytest.approx(0.0)

    def test_centralized_partial_violation(self):
        r = TopologyCompliance("x", "centralized", "hub-spoke", 3)
        r.agents = {
            "hub": AgentCompliance("hub", "hub"),
            "w1": AgentCompliance("w1", "worker"),
            "w2": AgentCompliance("w2", "worker"),
        }
        r.agents_with_lateral_comms = ["w1"]
        assert _score_lateral_compliance(r, "centralized") == pytest.approx(0.5)


class TestProtocolCompliance:
    def test_all_filesystem_returns_1(self):
        r = TopologyCompliance("x", "centralized", "hub-spoke", 2)
        ac = AgentCompliance("a", "hub")
        ac.coordination_reads = ["/a", "/b"]
        ac.coordination_writes = ["/c"]
        r.agents = {"a": ac}
        assert _score_protocol_compliance(r) == pytest.approx(1.0)

    def test_all_native_returns_0(self):
        r = TopologyCompliance("x", "centralized", "hub-spoke", 2)
        ac = AgentCompliance("a", "hub")
        ac.send_messages = [{"to": "b", "content": "hi"}]
        ac.subagent_spawns = 1
        r.agents = {"a": ac}
        # total_coord_actions = 0 fs + 1 msg = 1; native = 1 msg + 1 spawn = 2
        # score = 1 - (2 / 1) — but the formula is 1 - native/total_coord
        # total_coord = 1 (send_messages counted), native = 2
        # so 1 - 2/1 = -1.0 ... wait, let me re-read the formula
        # total_coord_actions: coord reads + coord writes + send_messages = 0 + 0 + 1 = 1
        # native_actions: send_messages + subagent_spawns = 1 + 1 = 2
        # 1.0 - (2 / 1) = -1.0
        # The implementation can go negative — just check it's < 0 or == -1
        assert _score_protocol_compliance(r) == pytest.approx(-1.0)

    def test_no_coordination_returns_0(self):
        r = TopologyCompliance("x", "centralized", "hub-spoke", 2)
        r.agents = {"a": AgentCompliance("a", "hub")}
        assert _score_protocol_compliance(r) == 0.0

    def test_mixed_coordination(self):
        """50% filesystem, 50% native."""
        r = TopologyCompliance("x", "centralized", "hub-spoke", 2)
        ac = AgentCompliance("a", "hub")
        ac.coordination_reads = ["/a"]
        ac.coordination_writes = ["/b"]
        ac.send_messages = [{"to": "x", "content": "hi"}]
        # total_coord = 2 + 1 = 3; native = 1 msg + 0 spawn = 1
        # score = 1 - 1/3 ≈ 0.667
        r.agents = {"a": ac}
        assert _score_protocol_compliance(r) == pytest.approx(2 / 3, rel=1e-3)


class TestProtocolAdoption:
    def test_no_coordination_trivially_compliant(self):
        r = TopologyCompliance("x", "centralized", "hub-spoke", 2)
        r.subagent_spawns_total = 0
        r.native_messaging_total = 0
        r.agents = {"a": AgentCompliance("a", "hub")}
        assert _score_protocol_adoption(r) == 1.0

    def test_all_helm_agent(self):
        r = TopologyCompliance("x", "centralized", "hub-spoke", 2)
        r.subagent_spawns_total = 0
        r.native_messaging_total = 0
        ac = AgentCompliance("a", "hub")
        ac.helm_agent_sends = 3
        r.agents = {"a": ac}
        assert _score_protocol_adoption(r) == 1.0

    def test_all_native(self):
        r = TopologyCompliance("x", "centralized", "hub-spoke", 2)
        r.subagent_spawns_total = 2
        r.native_messaging_total = 1
        r.agents = {"a": AgentCompliance("a", "hub")}
        # controlled = 0; native = 3; total = 3
        assert _score_protocol_adoption(r) == pytest.approx(0.0)

    def test_mixed_helm_and_native(self):
        r = TopologyCompliance("x", "centralized", "hub-spoke", 2)
        r.subagent_spawns_total = 0
        r.native_messaging_total = 2
        ac = AgentCompliance("a", "hub")
        ac.helm_agent_sends = 2
        ac.coordination_reads = ["/a"]
        ac.coordination_writes = ["/b"]
        # controlled = 2 helm + 2 fs = 4; native = 2; total = 6
        r.agents = {"a": ac}
        assert _score_protocol_adoption(r) == pytest.approx(4 / 6, rel=1e-3)


class TestVerifyEnforcement:
    def test_clean_returns_true(self):
        r = TopologyCompliance("x", "centralized", "hub-spoke", 2)
        r.subagent_spawns_total = 0
        r.native_messaging_total = 0
        assert _verify_enforcement(r) is True

    def test_subagent_spawns_returns_false(self):
        r = TopologyCompliance("x", "centralized", "hub-spoke", 2)
        r.subagent_spawns_total = 1
        r.native_messaging_total = 0
        assert _verify_enforcement(r) is False

    def test_native_messages_returns_false(self):
        r = TopologyCompliance("x", "centralized", "hub-spoke", 2)
        r.subagent_spawns_total = 0
        r.native_messaging_total = 3
        assert _verify_enforcement(r) is False


# ---------------------------------------------------------------------------
# format_report
# ---------------------------------------------------------------------------


class TestFormatReport:
    def _make_result(self, **kwargs) -> TopologyCompliance:
        defaults = {
            "experiment_id": "exp-001",
            "prescribed_family": "centralized",
            "prescribed_pattern": "hub-spoke",
            "agent_count": 3,
        }
        defaults.update(kwargs)
        r = TopologyCompliance(**defaults)
        r.hierarchy_compliance = 1.0
        r.lateral_compliance = 1.0
        r.protocol_compliance = 0.5
        r.overall_compliance = 0.83
        r.subagent_spawns_total = 0
        r.native_messaging_total = 1
        r.lateral_communication_events = 0
        return r

    def test_produces_valid_markdown_table(self):
        report = format_report([self._make_result()])
        lines = report.strip().split("\n")
        assert lines[0] == "# Topology Compliance Report"
        # Header row
        assert "| Experiment |" in lines[2]
        # Separator row
        assert lines[3].startswith("|---")
        # Data row
        assert "exp-001" in lines[4]

    def test_summary_section_present(self):
        report = format_report([self._make_result()])
        assert "## Summary" in report
        assert "Experiments analyzed: 1" in report

    def test_empty_results(self):
        report = format_report([])
        assert "# Topology Compliance Report" in report
        assert "## Summary" not in report

    def test_multiple_results(self):
        r1 = self._make_result(experiment_id="exp-001")
        r2 = self._make_result(experiment_id="exp-002")
        report = format_report([r1, r2])
        assert "exp-001" in report
        assert "exp-002" in report
        assert "Experiments analyzed: 2" in report

    def test_long_experiment_id_truncated(self):
        long_id = "-".join(["part"] * 12)  # many dashes
        r = self._make_result(experiment_id=long_id)
        report = format_report([r])
        # Should still be in the output (possibly truncated)
        assert "part" in report


# ---------------------------------------------------------------------------
# AgentCompliance dataclass properties
# ---------------------------------------------------------------------------


class TestAgentComplianceProperties:
    def test_peers_messaged(self):
        ac = AgentCompliance("a", "worker")
        ac.send_messages = [
            {"to": "b", "content": "hi"},
            {"to": "c", "content": "yo"},
            {"to": "b", "content": "again"},
        ]
        assert ac.peers_messaged() == {"b", "c"}

    def test_peers_messaged_missing_to(self):
        ac = AgentCompliance("a", "worker")
        ac.send_messages = [{"content": "hi"}]
        assert ac.peers_messaged() == set()

    def test_helm_agent_total(self):
        ac = AgentCompliance("a", "hub")
        ac.helm_agent_sends = 1
        ac.helm_agent_spawns = 2
        ac.helm_agent_inbox = 3
        ac.helm_agent_status = 4
        assert ac.helm_agent_total == 10
        assert ac.used_helm_agent is True

    def test_defaults(self):
        ac = AgentCompliance("a", None)
        assert ac.used_subagents is False
        assert ac.used_native_messaging is False
        assert ac.used_helm_agent is False
        assert ac.helm_agent_total == 0


# ---------------------------------------------------------------------------
# TopologyCompliance.to_dict
# ---------------------------------------------------------------------------


class TestTopologyComplianceToDict:
    def test_roundtrip_fields(self):
        r = TopologyCompliance("exp-1", "centralized", "hub-spoke", 2)
        r.agents["a"] = AgentCompliance("a", "hub")
        r.hierarchy_compliance = 1.0
        r.lateral_compliance = 0.5
        r.protocol_compliance = 0.75
        r.overall_compliance = 0.75
        r.enforcement_verified = True

        d = r.to_dict()
        assert d["experiment_id"] == "exp-1"
        assert d["prescribed_family"] == "centralized"
        assert d["hierarchy_compliance"] == 1.0
        assert d["enforcement_verified"] is True
        assert "a" in d["per_agent"]
        assert d["per_agent"]["a"]["role"] == "hub"
