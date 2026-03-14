from __future__ import annotations

from helm.benchmarks.exporter import (
    build_per_agent_training_records,
    build_training_record,
    compute_composite_reward,
    extract_last_assistant_text,
)
from helm.collector import extract_agent_transcript


def _transcript() -> dict:
    return {
        "agents": {
            "a": {
                "items": [
                    {
                        "timestamp": "2026-02-21T10:00:00",
                        "event_type": "item.completed",
                        "data": {
                            "item": {
                                "role": "assistant",
                                "content": [{"type": "text", "text": "first"}],
                            }
                        },
                    },
                    {
                        "timestamp": "2026-02-21T10:00:02",
                        "event_type": "item.completed",
                        "data": {
                            "item": {
                                "role": "assistant",
                                "content": [{"type": "text", "text": "latest output"}],
                            }
                        },
                    },
                ]
            }
        }
    }


def _run_data() -> dict:
    return {
        "experiment": {
            "id": "exp-1",
            "task": "Solve task",
            "matrix": {
                "matrix_id": "phase1",
                "condition_id": "wave0-single-1",
                "architecture_family": "single",
                "swarm_size": 1,
                "task_pack": "decomposable_cross_module",
                "task_structure": "decomposable_cross_module",
                "prompt_family": "swebench_claude_matrix_v1",
                "coordination_family": "single_solver_persistent_v1",
            },
        },
        "run": {
            "success": True,
            "task_verification": {"status": "pass", "score": 1.0},
            "orchestration_policy_trace": {
                "summary": {"total_events": 1},
                "events": [{"action": "escalate"}],
            },
        },
        "provenance": {"benchmark": {"benchmark_id": "smoke/bench", "example_id": "x1"}},
        "evals": {
            "orchestration": {
                "parallelism_efficiency": {"value": 0.5},
                "coordination_overhead": {"coordination_to_output_ratio": 0.25},
            }
        },
    }


def test_extract_last_assistant_text_picks_latest() -> None:
    assert extract_last_assistant_text(_transcript()) == "latest output"


def test_extract_last_assistant_text_falls_back_to_tool_calls() -> None:
    transcript = {
        "agents": {
            "a": {
                "items": [
                    {
                        "timestamp": "2026-02-21T10:00:03",
                        "event_type": "item.completed",
                        "data": {
                            "item": {
                                "role": "assistant",
                                "content": [{"type": "tool_call", "name": "Write"}],
                            }
                        },
                    }
                ]
            }
        }
    }
    assert extract_last_assistant_text(transcript) == "tool_call:Write"


def test_compute_composite_reward_uses_components() -> None:
    reward, components = compute_composite_reward(_run_data())
    assert 0.0 <= reward <= 1.0
    assert components["task_score"] == 1.0
    assert components["parallelism_score"] == 0.5


def test_build_training_record_contains_expected_fields() -> None:
    record = build_training_record(_run_data(), _transcript())
    assert record["id"] == "exp-1"
    assert isinstance(record["messages"], list)
    assert record["messages"][0]["role"] == "user"
    assert record["messages"][1]["content"] == "latest output"
    assert "reward" in record
    assert "benchmark" in record
    assert record["matrix"]["architecture_family"] == "single"
    assert record["orchestration_policy_trace"]["summary"]["total_events"] == 1


def test_build_training_record_defaults_empty_policy_trace() -> None:
    run_data = _run_data()
    run_data["run"].pop("orchestration_policy_trace")

    record = build_training_record(run_data, _transcript())
    assert record["orchestration_policy_trace"]["summary"]["total_events"] == 0


# ---------------------------------------------------------------------------
# Multi-agent transcript fixture
# ---------------------------------------------------------------------------

def _multi_agent_transcript() -> dict:
    """Transcript with 3 agents: coordinator, researcher, implementer."""
    return {
        "experiment_id": "exp-multi-1",
        "experiment_name": "hub-spoke-test",
        "agents": {
            "coordinator": {
                "start_time": "2026-03-01T10:00:00",
                "end_time": "2026-03-01T10:05:00",
                "item_count": 2,
                "items": [
                    {
                        "timestamp": "2026-03-01T10:00:01",
                        "event_type": "item.completed",
                        "data": {
                            "item": {
                                "role": "assistant",
                                "content": [
                                    {"type": "text", "text": "Delegating tasks to team"},
                                ],
                            }
                        },
                    },
                    {
                        "timestamp": "2026-03-01T10:05:00",
                        "event_type": "item.completed",
                        "data": {
                            "item": {
                                "role": "assistant",
                                "content": [
                                    {"type": "text", "text": "All tasks complete"},
                                ],
                            }
                        },
                    },
                ],
            },
            "researcher": {
                "start_time": "2026-03-01T10:00:30",
                "end_time": "2026-03-01T10:03:00",
                "item_count": 1,
                "items": [
                    {
                        "timestamp": "2026-03-01T10:03:00",
                        "event_type": "item.completed",
                        "data": {
                            "item": {
                                "role": "assistant",
                                "content": [
                                    {"type": "text", "text": "Research findings ready"},
                                ],
                            }
                        },
                    },
                ],
            },
            "implementer": {
                "start_time": "2026-03-01T10:01:00",
                "end_time": "2026-03-01T10:04:00",
                "item_count": 1,
                "items": [
                    {
                        "timestamp": "2026-03-01T10:04:00",
                        "event_type": "item.completed",
                        "data": {
                            "item": {
                                "role": "assistant",
                                "content": [
                                    {"type": "tool_call", "name": "Write"},
                                ],
                            }
                        },
                    },
                ],
            },
        },
        "coordination_messages": [
            {"sender": "coordinator", "recipient": "researcher", "type": "task_assignment"},
            {"sender": "researcher", "recipient": "coordinator", "type": "status_update"},
            {"sender": "coordinator", "recipient": "__all__", "type": "decision"},
            {"sender": None, "recipient": "__all__", "type": "status_update"},
        ],
    }


def _multi_agent_run_data() -> dict:
    return {
        "experiment": {
            "id": "exp-multi-1",
            "task": "Build a fibonacci function with tests",
            "pattern": "hub-and-spoke",
            "matrix": {
                "matrix_id": "phase1",
                "condition_id": "wave0-centralized-3",
                "architecture_family": "centralized",
                "swarm_size": 3,
                "task_pack": "decomposable_cross_module",
                "task_structure": "decomposable_cross_module",
                "prompt_family": "swebench_claude_matrix_v1",
                "coordination_family": "centralized_hub_v1",
            },
            "agents": [
                {"id": "coordinator", "role": "hub", "harness": "claude-code", "model": "claude-opus-4-6"},
                {"id": "researcher", "role": "worker", "harness": "claude-code", "model": "claude-opus-4-6"},
                {"id": "implementer", "role": "worker", "harness": "claude-code", "model": "claude-opus-4-6"},
            ],
        },
        "run": {
            "success": True,
            "task_verification": {"status": "pass", "score": 1.0},
        },
        "provenance": {"benchmark": {"benchmark_id": "swe-bench", "example_id": "ex-1"}},
        "evals": {
            "orchestration": {
                "parallelism_efficiency": {"value": 0.6},
                "coordination_overhead": {"coordination_to_output_ratio": 0.2},
            }
        },
    }


# ---------------------------------------------------------------------------
# extract_agent_transcript tests
# ---------------------------------------------------------------------------

def test_extract_agent_transcript_returns_single_agent() -> None:
    t = _multi_agent_transcript()
    result = extract_agent_transcript(t, "researcher")
    assert result is not None
    assert result["agent_id"] == "researcher"
    assert "researcher" in result["agents"]
    assert len(result["agents"]) == 1
    assert result["total_items"] == 1


def test_extract_agent_transcript_filters_coordination_messages() -> None:
    t = _multi_agent_transcript()
    result = extract_agent_transcript(t, "researcher")
    assert result is not None
    # researcher sees direct messages plus broadcasts
    assert len(result["coordination_messages"]) == 4


def test_extract_agent_transcript_includes_broadcast_coordination_messages() -> None:
    t = _multi_agent_transcript()
    result = extract_agent_transcript(t, "implementer")
    assert result is not None
    recipients = {msg["recipient"] for msg in result["coordination_messages"]}
    assert "__all__" in recipients


def test_extract_agent_transcript_returns_none_for_unknown_agent() -> None:
    t = _multi_agent_transcript()
    assert extract_agent_transcript(t, "nonexistent") is None


def test_extract_agent_transcript_preserves_experiment_context() -> None:
    t = _multi_agent_transcript()
    result = extract_agent_transcript(t, "coordinator")
    assert result is not None
    assert result["experiment_id"] == "exp-multi-1"
    assert result["experiment_name"] == "hub-spoke-test"


# ---------------------------------------------------------------------------
# build_per_agent_training_records tests
# ---------------------------------------------------------------------------

def test_per_agent_records_produces_one_per_agent() -> None:
    records = build_per_agent_training_records(
        _multi_agent_run_data(), _multi_agent_transcript()
    )
    assert len(records) == 3
    agent_ids = {r["agent_id"] for r in records}
    assert agent_ids == {"coordinator", "researcher", "implementer"}


def test_per_agent_records_shared_reward() -> None:
    records = build_per_agent_training_records(
        _multi_agent_run_data(), _multi_agent_transcript()
    )
    rewards = {r["reward"] for r in records}
    # All agents should get the same reward (shared attribution)
    assert len(rewards) == 1
    assert all(r["reward_attribution"] == "shared" for r in records)


def test_per_agent_records_contain_agent_metadata() -> None:
    records = build_per_agent_training_records(
        _multi_agent_run_data(), _multi_agent_transcript()
    )
    coord = next(r for r in records if r["agent_id"] == "coordinator")
    assert coord["agent_role"] == "hub"
    assert coord["agent_harness"] == "claude-code"
    assert coord["agent_model"] == "claude-opus-4-6"
    assert coord["topology"] == "hub-and-spoke"
    assert coord["matrix"]["architecture_family"] == "centralized"


def test_per_agent_records_have_correct_messages() -> None:
    records = build_per_agent_training_records(
        _multi_agent_run_data(), _multi_agent_transcript()
    )
    coord = next(r for r in records if r["agent_id"] == "coordinator")
    assert coord["messages"][0]["role"] == "user"
    assert coord["messages"][0]["content"] == "Build a fibonacci function with tests"
    assert coord["messages"][1]["content"] == "All tasks complete"

    impl = next(r for r in records if r["agent_id"] == "implementer")
    # implementer only had tool_call, should fall back
    assert impl["messages"][1]["content"] == "tool_call:Write"


def test_per_agent_records_include_trace() -> None:
    records = build_per_agent_training_records(
        _multi_agent_run_data(), _multi_agent_transcript()
    )
    researcher = next(r for r in records if r["agent_id"] == "researcher")
    assert "trace" in researcher
    assert researcher["trace"]["agent_id"] == "researcher"
    assert len(researcher["trace"]["agents"]) == 1


def test_per_agent_records_id_format() -> None:
    records = build_per_agent_training_records(
        _multi_agent_run_data(), _multi_agent_transcript()
    )
    coord = next(r for r in records if r["agent_id"] == "coordinator")
    assert coord["id"] == "exp-multi-1:coordinator"
    assert coord["experiment_id"] == "exp-multi-1"


def test_per_agent_records_empty_transcript() -> None:
    records = build_per_agent_training_records(
        _multi_agent_run_data(), {"agents": {}}
    )
    assert records == []


def test_per_agent_records_single_agent_fallback() -> None:
    """Single-agent experiment should produce exactly one record."""
    records = build_per_agent_training_records(_run_data(), _transcript())
    assert len(records) == 1
    assert records[0]["agent_id"] == "a"
