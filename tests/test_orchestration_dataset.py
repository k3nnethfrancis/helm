from __future__ import annotations

from helm.benchmarks.orchestration_dataset import (
    build_orchestration_training_row,
    derive_policy_target,
    normalize_orchestration_record,
)


def _export_record() -> dict:
    return {
        "id": "exp-42",
        "messages": [
            {"role": "user", "content": "Fix a flaky parser and report status."},
            {"role": "assistant", "content": "done"},
        ],
        "reward": 0.81,
        "task_verification": {"status": "pass", "score": 1.0},
        "benchmark": {"benchmark_id": "local/swe-smoke"},
        "orchestration": {
            "parallelism_efficiency": {"value": 0.67},
            "coordination_overhead": {"coordination_to_output_ratio": 0.18},
        },
        "orchestration_policy_trace": {
            "summary": {
                "total_events": 3,
                "by_source": {"orchestrator": 2, "human": 1},
                "by_action": {"escalate": 2, "log": 1},
            }
        },
    }


def test_derive_policy_target_from_trace_and_metrics() -> None:
    target = derive_policy_target(_export_record())
    assert target["escalation_route"] == "orchestrator_then_human"
    assert target["dominant_intervention"] == "escalate"
    assert target["intervention_intensity"] == "medium"
    assert target["parallelism_target"] == "high"
    assert target["coordination_style"] == "lean"
    assert target["verification_gate"] == "pass"
    assert target["human_gate_required"] == "yes"


def test_build_orchestration_training_row_shapes_output() -> None:
    row = build_orchestration_training_row(_export_record())
    assert row["task"] == "helm-orchestration-policy"
    assert isinstance(row["question"], str)
    assert "<escalation_route>" in row["question"]
    assert isinstance(row["answer"], dict)
    assert row["answer"]["verification_gate"] == "pass"


def test_normalize_orchestration_record_accepts_prebuilt_rows() -> None:
    row = normalize_orchestration_record(
        {
            "question": "Return XML policy.",
            "answer": {
                "escalation_route": "none",
                "dominant_intervention": "log",
                "intervention_intensity": "none",
                "parallelism_target": "low",
                "coordination_style": "balanced",
                "verification_gate": "unknown",
                "human_gate_required": "no",
            },
            "info": {"source": "unit-test"},
        }
    )
    assert row["task"] == "helm-orchestration-policy"
    assert row["answer"]["dominant_intervention"] == "log"
