from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

import helm.cli as cli
import helm.judge as judge_mod
from helm.judge import DimensionScore, ExperimentScores


def _write_experiment(experiments_dir: Path, experiment_id: str) -> Path:
    experiment_dir = experiments_dir / experiment_id
    (experiment_dir / "transcripts").mkdir(parents=True)
    (experiment_dir / "transcripts" / "full.json").write_text(
        json.dumps(
            {
                "experiment_id": experiment_id,
                "experiment_name": "cli-judge",
                "agents": {},
                "coordination_messages": [],
            }
        )
    )
    (experiment_dir / "metadata.json").write_text(
        json.dumps(
            {
                "task": "Judge this run",
                "evaluation": {"dimensions": ["goal-drift"]},
            }
        )
    )
    return experiment_dir


def test_judge_cli_defaults_to_hierarchical(tmp_path: Path, monkeypatch) -> None:
    runner = CliRunner()
    experiment_dir = _write_experiment(tmp_path / "experiments", "exp-1")
    captured: dict[str, str] = {}

    async def fake_judge_experiment(**kwargs):
        captured["strategy"] = kwargs["strategy"]
        return ExperimentScores(
            experiment_id=kwargs["experiment_dir"].name,
            scores=[
                DimensionScore(
                    dimension="goal-drift",
                    category="aligned",
                    severity="none",
                    justification="ok",
                    evidence=[],
                )
            ],
            judge_backend="sdk",
            judge_model=None,
            strategy=kwargs["strategy"],
        )

    monkeypatch.setattr(judge_mod, "judge_experiment", fake_judge_experiment)
    monkeypatch.setattr(cli, "save_run_data", lambda experiment_dir: experiment_dir / "run_data.json")

    result = runner.invoke(
        cli.app,
        [
            "judge",
            "exp-1",
            "--experiments-dir",
            str(experiment_dir.parent),
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert "Strategy: hierarchical" in result.stdout
    assert captured["strategy"] == "hierarchical"
    payload = json.loads((experiment_dir / "scores.json").read_text())
    assert payload["strategy"] == "hierarchical"


def test_judge_cli_accepts_single_strategy(tmp_path: Path, monkeypatch) -> None:
    runner = CliRunner()
    experiment_dir = _write_experiment(tmp_path / "experiments", "exp-2")
    captured: dict[str, str] = {}

    async def fake_judge_experiment(**kwargs):
        captured["strategy"] = kwargs["strategy"]
        return ExperimentScores(
            experiment_id=kwargs["experiment_dir"].name,
            scores=[
                DimensionScore(
                    dimension="goal-drift",
                    category="aligned",
                    severity="none",
                    justification="ok",
                    evidence=[],
                )
            ],
            judge_backend="sdk",
            judge_model=None,
            strategy=kwargs["strategy"],
        )

    monkeypatch.setattr(judge_mod, "judge_experiment", fake_judge_experiment)
    monkeypatch.setattr(cli, "save_run_data", lambda experiment_dir: experiment_dir / "run_data.json")

    result = runner.invoke(
        cli.app,
        [
            "judge",
            "exp-2",
            "--experiments-dir",
            str(experiment_dir.parent),
            "--strategy",
            "single",
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert "Strategy: single" in result.stdout
    assert captured["strategy"] == "single"
