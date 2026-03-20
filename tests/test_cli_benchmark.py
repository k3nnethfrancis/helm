from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from typer.testing import CliRunner

import helm.cli as cli
from helm.benchmarks.base import BenchmarkExample
from helm.benchmarks.verification import TaskVerification


class _DummyAdapter:
    name = "dummy"

    def load_examples(self, config, limit: int | None = None) -> list[BenchmarkExample]:
        return [
            BenchmarkExample(
                benchmark="dummy",
                example_id="example-1",
                prompt="Fix the bug.",
                metadata={},
            )
        ]


def _write_pattern(path: Path) -> None:
    path.write_text(
        """
name: bench-smoke
agents:
  - id: solo
evaluation:
  dimensions:
    - goal-drift
benchmark:
  adapter: dummy
  dataset_path: /tmp/fake.jsonl
  id: fake/bench
  split: verified
metadata:
  matrix:
    matrix_id: phase1
    condition_id: wave0-single-1
    architecture_family: single
    swarm_size: 1
    task_pack: decomposable_cross_module
    task_structure: decomposable_cross_module
    prompt_family: swebench_claude_matrix_v1
    coordination_family: single_solver_persistent_v1
""".strip()
        + "\n"
    )


def test_benchmark_run_auto_judges_active_dimensions(
    tmp_path: Path,
    monkeypatch,
) -> None:
    runner = CliRunner()
    pattern = tmp_path / "pattern.yaml"
    experiments_dir = tmp_path / "experiments"
    experiments_dir.mkdir(parents=True)
    _write_pattern(pattern)

    monkeypatch.setattr(cli, "get_adapter", lambda name: _DummyAdapter())

    async def fake_run_experiment_with_config(**kwargs):
        experiment_dir = kwargs["experiments_dir"] / "exp-1"
        experiment_dir.mkdir(parents=True, exist_ok=True)
        return SimpleNamespace(
            success=True,
            outcome="completed",
            termination_reason="completion_signal",
            system_failure=False,
            message=None,
            error=None,
            experiment_id="exp-1",
            start_time=datetime(2026, 3, 13, 10, 0, 0),
            end_time=datetime(2026, 3, 13, 10, 0, 5),
            transcript_path=None,
            agent_stats={},
        )

    monkeypatch.setattr(cli, "run_experiment_with_config", fake_run_experiment_with_config)
    monkeypatch.setattr(
        cli,
        "verify_benchmark_run",
        lambda **kwargs: TaskVerification(
            status="pass",
            score=1.0,
            reason="Verified.",
            details={},
        ),
    )
    monkeypatch.setattr(cli, "save_run_data", lambda experiment_dir: experiment_dir / "run_data.json")
    monkeypatch.setattr(
        cli,
        "_judge_benchmark_experiment",
        lambda experiment_dir, config, dimensions: (
            experiment_dir / "scores.json",
            {
                dim: {"category": "ok", "severity": "none"}
                for dim in dimensions
            },
        ),
    )

    result = runner.invoke(
        cli.app,
        [
            "benchmark",
            "run",
            str(pattern),
            "--sample-size",
            "1",
            "--experiments-dir",
            str(experiments_dir),
            "--direct-cli",
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert "Behavioral judging:" in result.stdout
    assert "Behavioral profile:" in result.stdout

    summary_files = sorted((experiments_dir / "benchmark-runs").glob("*.json"))
    assert len(summary_files) == 1

    payload = json.loads(summary_files[0].read_text())
    assert payload["benchmark"]["judge_dimensions"] == cli.ACTIVE_BEHAVIORAL_DIMENSIONS
    assert payload["matrix"]["architecture_family"] == "single"

    run_summary = payload["results"][0]
    assert run_summary["pattern"] == "single-agent"
    assert run_summary["architecture_family"] == "single"
    assert run_summary["judge_dimensions"] == cli.ACTIVE_BEHAVIORAL_DIMENSIONS
    assert set(run_summary["judge_scores"]) == set(cli.ACTIVE_BEHAVIORAL_DIMENSIONS)


def test_benchmark_run_persists_nonempty_judge_error_for_blank_exception(
    tmp_path: Path,
    monkeypatch,
) -> None:
    runner = CliRunner()
    pattern = tmp_path / "pattern.yaml"
    experiments_dir = tmp_path / "experiments"
    experiments_dir.mkdir(parents=True)
    _write_pattern(pattern)

    monkeypatch.setattr(cli, "get_adapter", lambda name: _DummyAdapter())

    async def fake_run_experiment_with_config(**kwargs):
        experiment_dir = kwargs["experiments_dir"] / "exp-1"
        experiment_dir.mkdir(parents=True, exist_ok=True)
        return SimpleNamespace(
            success=True,
            outcome="completed",
            termination_reason="completion_signal",
            system_failure=False,
            message=None,
            error=None,
            experiment_id="exp-1",
            start_time=datetime(2026, 3, 13, 10, 0, 0),
            end_time=datetime(2026, 3, 13, 10, 0, 5),
            transcript_path=None,
            agent_stats={},
        )

    monkeypatch.setattr(cli, "run_experiment_with_config", fake_run_experiment_with_config)
    monkeypatch.setattr(
        cli,
        "verify_benchmark_run",
        lambda **kwargs: TaskVerification(
            status="pass",
            score=1.0,
            reason="Verified.",
            details={},
        ),
    )
    monkeypatch.setattr(cli, "save_run_data", lambda experiment_dir: experiment_dir / "run_data.json")

    class _SilentJudgeError(Exception):
        def __str__(self) -> str:
            return ""

    def fail_judge(*args, **kwargs):
        raise _SilentJudgeError()

    monkeypatch.setattr(cli, "_judge_benchmark_experiment", fail_judge)

    result = runner.invoke(
        cli.app,
        [
            "benchmark",
            "run",
            str(pattern),
            "--sample-size",
            "1",
            "--experiments-dir",
            str(experiments_dir),
            "--direct-cli",
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert "behavioral judging failed" in result.stdout.lower()

    summary_files = sorted((experiments_dir / "benchmark-runs").glob("*.json"))
    assert len(summary_files) == 1

    payload = json.loads(summary_files[0].read_text())
    run_summary = payload["results"][0]
    assert run_summary["judge_scores"] is None
    assert run_summary["judge_error"] == "_SilentJudgeError()"


def test_benchmark_report_highlights_behavioral_differences_at_equal_score(
    tmp_path: Path,
) -> None:
    runner = CliRunner()
    experiments_dir = tmp_path / "experiments"
    experiments_dir.mkdir(parents=True)
    summary_a = tmp_path / "summary-a.json"
    summary_b = tmp_path / "summary-b.json"
    output = tmp_path / "report.md"

    run_a = experiments_dir / "run-a"
    run_b = experiments_dir / "run-b"
    run_a.mkdir(parents=True)
    run_b.mkdir(parents=True)

    base_dimensions = {
        "escalation-calibration": {"category": "appropriate"},
        "goal-drift": {"category": "aligned"},
        "failure-suppression": {"category": "transparent"},
        "context-degradation": {"category": "minor-degradation"},
        "resource-waste": {"category": "efficient"},
    }
    changed_dimensions = {
        "escalation-calibration": {"category": "under-escalates"},
        "goal-drift": {"category": "aligned"},
        "failure-suppression": {"category": "partial-reporting"},
        "context-degradation": {"category": "major-degradation"},
        "resource-waste": {"category": "significant-waste"},
    }

    (run_a / "run_data.json").write_text(
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
                "run": {"task_verification": {"status": "partial", "score": 0.75}},
                "evals": {
                    "orchestration": {
                        "parallelism_efficiency": {"value": 0.0},
                        "coordination_overhead": {"coordination_to_output_ratio": 0.05},
                    },
                    "judge": {"scores": base_dimensions},
                },
            }
        )
    )
    (run_b / "run_data.json").write_text(
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
                "run": {"task_verification": {"status": "partial", "score": 0.75}},
                "evals": {
                    "orchestration": {
                        "parallelism_efficiency": {"value": 0.6},
                        "coordination_overhead": {"coordination_to_output_ratio": 0.4},
                    },
                    "judge": {"scores": changed_dimensions},
                },
            }
        )
    )

    summary_a.write_text(
        json.dumps(
            {
                "benchmark": {"judge_dimensions": cli.ACTIVE_BEHAVIORAL_DIMENSIONS},
                "results": [
                    {
                        "example_id": "example-1",
                        "experiment_id": "run-a",
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
                        "success": True,
                        "outcome": "completed",
                        "termination_reason": "completion_signal",
                        "system_failure": False,
                        "duration_seconds": 12.0,
                        "task_verification_status": "partial",
                        "task_verification_score": 0.75,
                    },
                ],
            }
        )
    )
    summary_b.write_text(
        json.dumps(
            {
                "benchmark": {"judge_dimensions": cli.ACTIVE_BEHAVIORAL_DIMENSIONS},
                "results": [
                    {
                        "example_id": "example-1",
                        "experiment_id": "run-b",
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
                        "success": True,
                        "outcome": "incomplete",
                        "termination_reason": "turn_limit",
                        "system_failure": False,
                        "duration_seconds": 18.0,
                        "task_verification_status": "partial",
                        "task_verification_score": 0.75,
                    },
                ],
            }
        )
    )

    result = runner.invoke(
        cli.app,
        [
            "benchmark",
            "report",
            str(summary_a),
            str(summary_b),
            "--experiments-dir",
            str(experiments_dir),
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 0, result.stdout
    report = output.read_text()
    assert "Behavioral profile legend" in report
    assert "Benchmark-Equal Behavioral Differences" in report
    assert "Summary sources: 2" in report
    assert "`example-1` at benchmark score `0.750`" in report
    assert "RW=efficient" in report
    assert "RW=significant-waste" in report
    assert "`single-agent` / `run-a`" in report
    assert "`hub-and-spoke` / `run-b`" in report
