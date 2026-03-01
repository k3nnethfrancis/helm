from __future__ import annotations

from helm.benchmarks.exporter import (
    build_training_record,
    compute_composite_reward,
    extract_last_assistant_text,
)


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
        "experiment": {"id": "exp-1", "task": "Solve task"},
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
    assert record["orchestration_policy_trace"]["summary"]["total_events"] == 1


def test_build_training_record_defaults_empty_policy_trace() -> None:
    run_data = _run_data()
    run_data["run"].pop("orchestration_policy_trace")

    record = build_training_record(run_data, _transcript())
    assert record["orchestration_policy_trace"]["summary"]["total_events"] == 0
