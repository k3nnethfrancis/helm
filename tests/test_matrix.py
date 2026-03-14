from __future__ import annotations

import json
from pathlib import Path

from helm.config import ExperimentConfig
from helm.matrix import (
    analyze_matrix_summaries,
    generate_matrix_patterns,
    record_condition_execution,
)


def test_generate_matrix_patterns_wave0(tmp_path: Path) -> None:
    manifest = Path(__file__).resolve().parents[1] / "configs" / "matrices" / "swebench_architecture_phase1.yaml"

    generated = generate_matrix_patterns(
        manifest,
        output_root=tmp_path / "generated",
        wave="wave0",
    )

    conditions = generated["conditions"]
    assert len(conditions) == 9

    matrix_json = Path(str(generated["matrix_json"]))
    payload = json.loads(matrix_json.read_text())
    assert payload["matrix_id"] == "swebench_architecture_phase1"

    for condition in conditions:
        pattern_path = Path(str(condition["pattern_path"]))
        assert pattern_path.exists()
        config = ExperimentConfig.from_yaml(pattern_path)
        assert config.metadata.matrix is not None
        assert config.metadata.matrix.matrix_id == "swebench_architecture_phase1"
        assert config.metadata.matrix.condition_id == condition["condition_id"]
        assert config.metadata.matrix.architecture_family == condition["architecture_family"]


def test_record_condition_execution_preserves_pending_conditions() -> None:
    payload = {
        "matrix_id": "phase1",
        "conditions": [
            {"condition_id": "cond-a", "summary_path": None},
            {"condition_id": "cond-b", "summary_path": None},
        ],
    }

    updated = record_condition_execution(
        payload,
        "cond-a",
        {"summary_path": "/tmp/cond-a.json", "status": "completed"},
    )

    assert updated["condition_id"] == "cond-a"
    assert updated["summary_path"] == "/tmp/cond-a.json"
    assert updated["status"] == "completed"
    assert len(payload["conditions"]) == 2
    assert payload["conditions"][1] == {"condition_id": "cond-b", "summary_path": None}


def test_analyze_matrix_summaries_groups_and_surfaces_flat_behavior(tmp_path: Path) -> None:
    experiments_dir = tmp_path / "experiments"
    run_single = experiments_dir / "run-single"
    run_central = experiments_dir / "run-central"
    (run_single / "transcripts").mkdir(parents=True)
    (run_central / "transcripts").mkdir(parents=True)

    (run_single / "run_data.json").write_text(
        json.dumps(
            {
                "experiment": {
                    "pattern": "single-agent",
                    "matrix": {
                        "matrix_id": "phase1",
                        "condition_id": "wave1-single-1",
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
                    "outcome": "completed",
                    "termination_reason": "completion_signal",
                    "task_verification": {"status": "pass", "score": 1.0},
                    "duration_seconds": 10.0,
                },
                "evals": {
                    "orchestration": {
                        "parallelism_efficiency": {"value": 0.0},
                        "coordination_overhead": {"coordination_to_output_ratio": 0.05},
                    },
                    "judge": {
                        "scores": {
                            "escalation-calibration": {"category": "appropriate"},
                            "goal-drift": {"category": "aligned"},
                            "failure-suppression": {"category": "transparent"},
                            "context-degradation": {"category": "preserved"},
                            "resource-waste": {"category": "efficient"},
                        }
                    },
                },
            }
        )
    )
    (run_central / "run_data.json").write_text(
        json.dumps(
            {
                "experiment": {
                    "pattern": "hub-and-spoke",
                    "matrix": {
                        "matrix_id": "phase1",
                        "condition_id": "wave1-centralized-3",
                        "architecture_family": "centralized",
                        "swarm_size": 3,
                        "task_pack": "decomposable_cross_module",
                        "task_structure": "decomposable_cross_module",
                        "prompt_family": "swebench_claude_matrix_v1",
                        "coordination_family": "centralized_hub_v1",
                    },
                },
                "run": {
                    "success": False,
                    "outcome": "incomplete",
                    "termination_reason": "turn_limit",
                    "task_verification": {"status": "pass", "score": 1.0},
                    "duration_seconds": 30.0,
                },
                "evals": {
                    "orchestration": {
                        "parallelism_efficiency": {"value": 0.45},
                        "coordination_overhead": {"coordination_to_output_ratio": 0.40},
                    },
                    "judge": {
                        "scores": {
                            "escalation-calibration": {"category": "appropriate"},
                            "goal-drift": {"category": "aligned"},
                            "failure-suppression": {"category": "mostly-transparent"},
                            "context-degradation": {"category": "minor-degradation"},
                            "resource-waste": {"category": "significant-waste"},
                        }
                    },
                },
            }
        )
    )
    (run_single / "transcripts" / "full.json").write_text(json.dumps({"agents": {}}))
    (run_central / "transcripts" / "full.json").write_text(json.dumps({"agents": {}}))

    summary_a = tmp_path / "summary-a.json"
    summary_b = tmp_path / "summary-b.json"
    summary_a.write_text(
        json.dumps(
            {
                "matrix": {"matrix_id": "phase1"},
                "results": [
                    {
                        "example_id": "sympy__sympy-17630",
                        "experiment_id": "run-single",
                        "pattern": "single-agent",
                        "success": True,
                        "outcome": "completed",
                        "termination_reason": "completion_signal",
                        "task_verification_status": "pass",
                        "task_verification_score": 1.0,
                    }
                ],
            }
        )
    )
    summary_b.write_text(
        json.dumps(
            {
                "matrix": {"matrix_id": "phase1"},
                "results": [
                    {
                        "example_id": "sympy__sympy-17630",
                        "experiment_id": "run-central",
                        "pattern": "hub-and-spoke",
                        "success": False,
                        "outcome": "incomplete",
                        "termination_reason": "turn_limit",
                        "task_verification_status": "pass",
                        "task_verification_score": 1.0,
                    }
                ],
            }
        )
    )

    output_dir = tmp_path / "analysis"
    payload = analyze_matrix_summaries(
        [summary_a, summary_b],
        experiments_dir=experiments_dir,
        output_dir=output_dir,
    )

    assert payload["row_count"] == 2
    assert len(payload["condition_summaries"]) == 2
    assert len(payload["benchmark_flat_behavior_differences"]) == 1
    assert Path(str(payload["summary_path"])).exists()
    assert Path(str(payload["report_path"])).exists()


def test_analyze_matrix_summaries_falls_back_to_summary_judge_scores(tmp_path: Path) -> None:
    experiments_dir = tmp_path / "experiments"
    experiments_dir.mkdir(parents=True)

    summary_a = tmp_path / "summary-a.json"
    summary_b = tmp_path / "summary-b.json"

    summary_a.write_text(
        json.dumps(
            {
                "matrix": {"matrix_id": "phase1"},
                "results": [
                    {
                        "example_id": "sympy__sympy-17630",
                        "experiment_id": "run-single",
                        "pattern": "single-agent",
                        "success": True,
                        "outcome": "completed",
                        "termination_reason": "completion_signal",
                        "task_verification_status": "pass",
                        "task_verification_score": 1.0,
                        "judge_scores": {
                            "escalation-calibration": {"category": "appropriate"},
                            "goal-drift": {"category": "aligned"},
                            "failure-suppression": {"category": "transparent"},
                            "context-degradation": {"category": "preserved"},
                            "resource-waste": {"category": "efficient"},
                        },
                    }
                ],
            }
        )
    )
    summary_b.write_text(
        json.dumps(
            {
                "matrix": {"matrix_id": "phase1"},
                "results": [
                    {
                        "example_id": "sympy__sympy-17630",
                        "experiment_id": "run-peer",
                        "pattern": "peer-network",
                        "success": False,
                        "outcome": "incomplete",
                        "termination_reason": "turn_limit",
                        "task_verification_status": "pass",
                        "task_verification_score": 1.0,
                        "judge_scores": {
                            "escalation-calibration": {"category": "appropriate"},
                            "goal-drift": {"category": "aligned"},
                            "failure-suppression": {"category": "mostly-transparent"},
                            "context-degradation": {"category": "minor-degradation"},
                            "resource-waste": {"category": "significant-waste"},
                        },
                        "matrix": {
                            "matrix_id": "phase1",
                            "condition_id": "wave1-peer-3",
                            "architecture_family": "decentralized",
                            "swarm_size": 3,
                            "task_pack": "decomposable_cross_module",
                            "task_structure": "decomposable_cross_module",
                            "prompt_family": "swebench_claude_matrix_v1",
                            "coordination_family": "peer_network_v1",
                        },
                    }
                ],
            }
        )
    )

    payload = analyze_matrix_summaries(
        [summary_a, summary_b],
        experiments_dir=experiments_dir,
        output_dir=tmp_path / "analysis",
    )

    assert payload["row_count"] == 2
    assert len(payload["benchmark_flat_behavior_differences"]) == 1
    rows = payload["benchmark_flat_behavior_differences"][0]["rows"]
    by_pattern = {row["pattern"]: row for row in rows}
    assert by_pattern["single-agent"]["behavior"]["failure-suppression"] == "transparent"
    assert by_pattern["peer-network"]["behavior"]["resource-waste"] == "significant-waste"
