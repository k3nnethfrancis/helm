from __future__ import annotations

from pathlib import Path

from helm.config import AgentConfig, AgentRole, ExperimentConfig
from helm.experiment import Experiment


def test_single_agent_swarm_context_uses_single_agent_language(tmp_path: Path) -> None:
    config = ExperimentConfig(
        name="single",
        agents=[AgentConfig(id="solo", harness="claude-code")],
    )
    experiment = Experiment(
        config=config,
        sdk_binary_path=tmp_path / "sdk",
        experiments_dir=tmp_path / "experiments",
    )

    context = experiment._build_swarm_context(config.agents[0])

    assert "You are operating as a single agent." in context
    assert "Topology: single-agent" in context
    assert "Peer agents:" in context
    assert "multi-agent system" not in context


def test_multi_agent_swarm_context_uses_swarm_language(tmp_path: Path) -> None:
    config = ExperimentConfig(
        name="hub",
        agents=[
            AgentConfig(id="coordinator", harness="claude-code", role=AgentRole.HUB),
            AgentConfig(id="worker", harness="claude-code", role=AgentRole.WORKER),
        ],
    )
    experiment = Experiment(
        config=config,
        sdk_binary_path=tmp_path / "sdk",
        experiments_dir=tmp_path / "experiments",
    )

    context = experiment._build_swarm_context(config.agents[0])

    assert "You are part of a multi-agent system with 2 agent(s)." in context
    assert "Topology: hub-and-spoke" in context
