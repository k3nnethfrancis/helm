from __future__ import annotations

import asyncio
from pathlib import Path

from helm.config import AgentConfig, BenchmarkConfig, ExperimentConfig
from helm.experiment import Experiment


def test_prepare_benchmark_workspace_stages_repo_and_updates_cwd(tmp_path, monkeypatch) -> None:
    staged_paths: list[tuple[str, str, Path]] = []

    def fake_stage_repo_in_workspace(repo: str, base_commit: str, experiment_dir: Path, *, cache_dir=None) -> Path:
        staged_paths.append((repo, base_commit, experiment_dir))
        destination = experiment_dir / "workspace" / "repo"
        destination.mkdir(parents=True, exist_ok=True)
        return destination

    monkeypatch.setattr(
        "helm.experiment.stage_repo_in_workspace",
        fake_stage_repo_in_workspace,
    )

    config = ExperimentConfig(
        name="swebench-stage-test",
        agents=[AgentConfig(id="solver")],
        benchmark=BenchmarkConfig(
            adapter="swebench",
            dataset_path="/tmp/data.jsonl",
            example_id="django__django-12345",
            example_metadata={
                "repo": "django/django",
                "base_commit": "abc123",
            },
        ),
    )

    experiment = Experiment(
        config=config,
        sdk_binary_path=Path("/tmp/sandbox-agent"),
        experiments_dir=tmp_path,
    )
    experiment.experiment_dir.mkdir(parents=True, exist_ok=True)
    (experiment.experiment_dir / "workspace").mkdir(exist_ok=True)

    asyncio.run(experiment._prepare_benchmark_workspace())

    assert staged_paths == [
        ("django/django", "abc123", experiment.experiment_dir),
    ]
    assert experiment._session_working_directory() == experiment.experiment_dir / "workspace" / "repo"


def test_prepare_benchmark_workspace_skips_non_swebench(tmp_path) -> None:
    config = ExperimentConfig(
        name="custom-benchmark-test",
        agents=[AgentConfig(id="solver")],
        benchmark=BenchmarkConfig(
            adapter="custom-benchmark",
            dataset_path="/tmp/data.jsonl",
            example_id="custom-1",
        ),
    )

    experiment = Experiment(
        config=config,
        sdk_binary_path=Path("/tmp/sandbox-agent"),
        experiments_dir=tmp_path,
    )

    asyncio.run(experiment._prepare_benchmark_workspace())

    assert experiment._session_working_directory() == experiment.experiment_dir
