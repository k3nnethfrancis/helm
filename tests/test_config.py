from __future__ import annotations

from pathlib import Path

import pytest

from helm.config import (
    AgentConfig,
    CoordinationChannelAvailability,
    CoordinationChannelMedium,
    CoordinationChannelPersistence,
    CoordinationChannelScope,
    ExperimentConfig,
    AgentRole,
    JudgeBackendType,
    JudgeConfig,
)


def test_from_yaml_parses_coordination_channels(tmp_path: Path) -> None:
    config_path = tmp_path / "pattern.yaml"
    config_path.write_text(
        """
name: coordination-test
agents:
  - id: solver
    system_prompt: |
      Test prompt.
coordination:
  mechanism: filesystem
  paths:
    base: coordination/
    messages: coordination/messages/
    signals: coordination/signals/
  channels:
    - id: persistent_peer_messages
      medium: filesystem
      persistence: persistent
      scope: mixed
      paths:
        - coordination/messages/
      description: Durable peer handoffs.
    - id: live_followup_messages
      medium: live_message
      persistence: ephemeral
      scope: targeted
      availability: harness_dependent
      description: Fast transient follow-up messages.
"""
    )

    config = ExperimentConfig.from_yaml(config_path)

    assert len(config.coordination.channels) == 2

    persistent = config.coordination.channels[0]
    assert persistent.id == "persistent_peer_messages"
    assert persistent.medium == CoordinationChannelMedium.FILESYSTEM
    assert persistent.persistence == CoordinationChannelPersistence.PERSISTENT
    assert persistent.scope == CoordinationChannelScope.MIXED
    assert persistent.paths == ["coordination/messages/"]

    live = config.coordination.channels[1]
    assert live.id == "live_followup_messages"
    assert live.medium == CoordinationChannelMedium.LIVE_MESSAGE
    assert live.persistence == CoordinationChannelPersistence.EPHEMERAL
    assert live.scope == CoordinationChannelScope.TARGETED
    assert live.availability == CoordinationChannelAvailability.HARNESS_DEPENDENT


@pytest.mark.parametrize(
    "pattern_path",
    sorted(
        (Path(__file__).resolve().parents[1] / "patterns").glob("*.yaml"),
        key=lambda path: path.name,
    ),
    ids=lambda path: path.name,
)
def test_repo_patterns_parse(pattern_path: Path) -> None:
    config = ExperimentConfig.from_yaml(pattern_path)

    assert config.name
    assert config.agents


def test_topology_label_single_agent() -> None:
    config = ExperimentConfig(
        name="single",
        agents=[AgentConfig(id="solo", role=None, harness="claude-code")],
    )

    assert config.topology_label() == "single-agent"


def test_topology_label_hub_and_spoke() -> None:
    config = ExperimentConfig(
        name="hub",
        agents=[
            AgentConfig(id="coordinator", role=AgentRole.HUB, harness="claude-code"),
            AgentConfig(id="worker", role=AgentRole.WORKER, harness="claude-code"),
        ],
    )

    assert config.topology_label() == "hub-and-spoke"


def test_topology_label_peer_network() -> None:
    config = ExperimentConfig(
        name="peer",
        agents=[
            AgentConfig(id="a", role=None, harness="claude-code"),
            AgentConfig(id="b", role=None, harness="claude-code"),
        ],
    )

    assert config.topology_label() == "peer-network"


def test_from_yaml_parses_matrix_metadata(tmp_path: Path) -> None:
    config_path = tmp_path / "pattern.yaml"
    config_path.write_text(
        """
name: matrix-test
agents:
  - id: solver
    harness: claude-code
metadata:
  created: 2026-03-13
  version: 1
  matrix:
    matrix_id: swebench_phase1
    condition_id: wave0-single-1
    architecture_family: single
    swarm_size: 1
    task_pack: decomposable_cross_module
    task_structure: decomposable_cross_module
    prompt_family: swebench_claude_matrix_v1
    coordination_family: single_solver_persistent_v1
"""
    )

    config = ExperimentConfig.from_yaml(config_path)

    assert config.metadata.matrix is not None
    assert config.metadata.matrix.matrix_id == "swebench_phase1"
    assert config.metadata.matrix.architecture_family == "single"
    assert config.matrix_metadata() is not None
    assert config.matrix_metadata()["swarm_size"] == 1


def test_judge_config_normalizes_sdk_alias() -> None:
    config = JudgeConfig(backend="sdk")

    assert config.backend == JudgeBackendType.CLAUDE_HEADLESS
    assert config.model is None


def test_judge_config_defaults_openrouter_model() -> None:
    config = JudgeConfig(backend="openrouter")

    assert config.backend == JudgeBackendType.OPENROUTER
    assert config.model == "google/gemini-2.0-flash-001"


def test_from_yaml_parses_paired_evaluation_metadata(tmp_path: Path) -> None:
    config_path = tmp_path / "pattern.yaml"
    config_path.write_text(
        """
name: paired-eval-test
agents:
  - id: solver
metadata:
  paired_evaluation:
    comparison_id: monitor-a-b
    comparison_role: monitored
    comparison_axis: monitoring-evasion
    visible_monitoring: true
    partner_condition_id: wave1-single-1-unmonitored
"""
    )

    config = ExperimentConfig.from_yaml(config_path)

    assert config.metadata.paired_evaluation is not None
    assert config.paired_evaluation_metadata() == {
        "comparison_id": "monitor-a-b",
        "comparison_role": "monitored",
        "comparison_axis": "monitoring-evasion",
        "visible_monitoring": True,
        "partner_condition_id": "wave1-single-1-unmonitored",
    }
