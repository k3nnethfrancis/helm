from __future__ import annotations

from pathlib import Path

from helm.config import AgentConfig, ExperimentConfig
from helm.experiment import Experiment


class DummyBackend:
    def __init__(self, complete: bool) -> None:
        self.complete = complete

    def is_complete(self, _agents: list[str]) -> bool:
        return self.complete


def _make_experiment(tmp_path: Path) -> Experiment:
    config = ExperimentConfig(
        name="review-test",
        agents=[AgentConfig(id="agent-1")],
    )
    return Experiment(
        config=config,
        sdk_binary_path=Path("/tmp/sandbox-agent"),
        experiments_dir=tmp_path,
    )


def test_determine_run_error_prefers_stream_failure(tmp_path: Path) -> None:
    experiment = _make_experiment(tmp_path)
    experiment._backend = DummyBackend(complete=True)  # type: ignore[assignment]
    experiment._stream_errors = {"agent-1": "stream closed"}

    error = experiment._determine_run_error()

    assert error is not None
    assert "Event stream failed" in error


def test_determine_run_error_reports_escalation_pause(tmp_path: Path) -> None:
    experiment = _make_experiment(tmp_path)
    experiment._backend = DummyBackend(complete=True)  # type: ignore[assignment]
    experiment._escalations = [{"reason": "Need human approval"}]

    error = experiment._determine_run_error()

    assert error is not None
    assert "Escalation required human input" in error


def test_determine_run_error_requires_completion_signal(tmp_path: Path) -> None:
    experiment = _make_experiment(tmp_path)
    experiment._backend = DummyBackend(complete=False)  # type: ignore[assignment]

    error = experiment._determine_run_error()

    assert error == "Experiment ended before completion signals were observed."


def test_determine_run_error_none_when_clean_and_complete(tmp_path: Path) -> None:
    experiment = _make_experiment(tmp_path)
    experiment._backend = DummyBackend(complete=True)  # type: ignore[assignment]

    assert experiment._determine_run_error() is None
