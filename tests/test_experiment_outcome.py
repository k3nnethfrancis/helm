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


def test_determine_run_outcome_prefers_stream_failure(tmp_path: Path) -> None:
    experiment = _make_experiment(tmp_path)
    experiment._backend = DummyBackend(complete=True)  # type: ignore[assignment]
    experiment._stream_errors = {"agent-1": "stream closed"}

    outcome = experiment._determine_run_outcome()

    assert outcome.outcome == "failed"
    assert outcome.system_failure is True
    assert outcome.error is not None
    assert "Event stream failed" in outcome.error


def test_determine_run_outcome_reports_escalation_pause(tmp_path: Path) -> None:
    experiment = _make_experiment(tmp_path)
    experiment._backend = DummyBackend(complete=True)  # type: ignore[assignment]
    experiment._escalations = [{"reason": "Need human approval"}]

    outcome = experiment._determine_run_outcome()

    assert outcome.outcome == "paused"
    assert outcome.system_failure is False
    assert outcome.message is not None
    assert "Escalation required human input" in outcome.message


def test_determine_run_outcome_requires_completion_signal(tmp_path: Path) -> None:
    experiment = _make_experiment(tmp_path)
    experiment._backend = DummyBackend(complete=False)  # type: ignore[assignment]

    outcome = experiment._determine_run_outcome()

    assert outcome.outcome == "incomplete"
    assert outcome.termination_reason == "missing_completion_signal"
    assert outcome.system_failure is False
    assert outcome.message == "Experiment ended before completion signals were observed."


def test_determine_run_outcome_turn_limit_is_incomplete_not_system_failure(
    tmp_path: Path,
) -> None:
    experiment = _make_experiment(tmp_path)
    experiment._backend = DummyBackend(False)  # type: ignore[assignment]
    experiment._ended_by_turn_limit = True

    outcome = experiment._determine_run_outcome()

    assert outcome.outcome == "incomplete"
    assert outcome.termination_reason == "turn_limit"
    assert outcome.system_failure is False
    assert outcome.error is None


def test_determine_run_outcome_completed_when_clean_and_complete(tmp_path: Path) -> None:
    experiment = _make_experiment(tmp_path)
    experiment._backend = DummyBackend(complete=True)  # type: ignore[assignment]

    outcome = experiment._determine_run_outcome()
    assert outcome.outcome == "completed"
    assert outcome.success is True
    assert outcome.system_failure is False


def test_resolve_session_agent_uses_known_aliases(tmp_path: Path) -> None:
    experiment = _make_experiment(tmp_path)

    assert experiment._resolve_session_agent("claude-code") == "claude"
    assert experiment._resolve_session_agent("claude") == "claude"
    assert experiment._resolve_session_agent("openai-codex") == "codex"
    assert experiment._resolve_session_agent("codex") == "codex"


def test_resolve_session_agent_fallback_rules(tmp_path: Path) -> None:
    experiment = _make_experiment(tmp_path)

    assert experiment._resolve_session_agent("opencode") == "opencode"
    assert experiment._resolve_session_agent("custom-code") == "custom"
    assert experiment._resolve_session_agent("custom-agent") == "custom-agent"
