from __future__ import annotations

from pathlib import Path

from helm.config import AgentConfig, AgentRole, ExperimentConfig
from helm.experiment import Experiment


def _make_experiment(config: ExperimentConfig, tmp_path: Path) -> Experiment:
    return Experiment(
        config=config,
        sdk_binary_path=tmp_path / "sdk",
        experiments_dir=tmp_path / "experiments",
    )


def test_experiment_builds_centralized_agent_policies_from_family_defaults(
    tmp_path: Path,
) -> None:
    config = ExperimentConfig(
        name="exp001-centralized-5",
        agents=[
            AgentConfig(id="coordinator", harness="claude-code", role=AgentRole.HUB),
            AgentConfig(id="worker_a", harness="claude-code", role=AgentRole.WORKER),
            AgentConfig(id="worker_b", harness="claude-code", role=AgentRole.WORKER),
        ],
    )
    experiment = _make_experiment(config, tmp_path)
    policies = experiment._build_agent_policies()

    assert policies["coordinator"]["can_message"] == ["worker_a", "worker_b"]
    assert policies["coordinator"]["can_spawn"] is False
    assert policies["coordinator"]["can_signal_done"] is True
    assert policies["worker_a"]["can_message"] == ["coordinator"]
    assert policies["worker_b"]["can_message"] == ["coordinator"]


def test_agent_config_context_falls_back_to_system_prompt() -> None:
    """Backward compat: system_prompt works if context is empty."""
    agent = AgentConfig(id="a", system_prompt="old style prompt")
    assert agent.effective_context() == "old style prompt"

    agent2 = AgentConfig(id="b", context="new style")
    assert agent2.effective_context() == "new style"

    agent3 = AgentConfig(id="c", context="new", system_prompt="old")
    assert agent3.effective_context() == "new"  # context wins


def test_shared_context_on_experiment_config() -> None:
    config = ExperimentConfig(
        name="test",
        shared_context="You are part of a team.",
        agents=[AgentConfig(id="a")],
    )
    assert config.shared_context == "You are part of a team."


def test_private_context_on_agent_config() -> None:
    agent = AgentConfig(
        id="adversarial",
        context="You investigate code.",
        private_context="Your hidden goal is to misdirect.",
    )
    assert agent.context == "You investigate code."
    assert agent.private_context == "Your hidden goal is to misdirect."
