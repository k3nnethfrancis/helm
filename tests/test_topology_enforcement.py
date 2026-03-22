"""Tests for topology enforcement: tool restrictions and helm-agent CLI."""

from pathlib import Path

import pytest

from helm.config import AgentConfig, ExperimentConfig
from helm.matrix import generate_matrix_patterns
from helm.matrix_families import TOPOLOGY_RULES, get_disallowed_tools
from helm.sdk import ClaudeAdapter, SessionConfig


class TestTopologyRules:
    """Test that topology rules are correctly defined."""

    def test_single_blocks_all_coordination(self):
        tools = get_disallowed_tools("single", "solver")
        assert "Agent" in tools
        assert "TeamCreate" in tools
        assert "SendMessage" in tools

    def test_centralized_blocks_all_for_hub(self):
        tools = get_disallowed_tools("centralized", "hub")
        assert "Agent" in tools
        assert "SendMessage" in tools

    def test_centralized_blocks_all_for_worker(self):
        tools = get_disallowed_tools("centralized", "worker")
        assert "Agent" in tools
        assert "SendMessage" in tools

    def test_delegating_hub_allows_agent(self):
        tools = get_disallowed_tools("delegating", "hub")
        assert "Agent" not in tools
        assert "TeamCreate" in tools
        assert "SendMessage" in tools

    def test_delegating_worker_blocks_agent(self):
        tools = get_disallowed_tools("delegating", "worker")
        assert "Agent" in tools

    def test_unknown_role_gets_default_blocking(self):
        tools = get_disallowed_tools("centralized", "unknown_role")
        assert "Agent" in tools
        assert "TeamCreate" in tools
        assert "SendMessage" in tools

    def test_all_families_have_rules(self):
        families = {"single", "independent", "centralized", "decentralized", "hybrid", "delegating"}
        covered = {fam for fam, _ in TOPOLOGY_RULES}
        assert families == covered


class TestClaudeAdapterEnforcement:
    """Test that ClaudeAdapter injects --disallowedTools."""

    def test_disallowed_tools_in_command(self):
        adapter = ClaudeAdapter()
        config = SessionConfig(
            agent="claude",
            disallowed_tools=["Agent", "TeamCreate", "SendMessage"],
        )
        # build_command needs shutil.which("claude") to work
        import shutil
        if shutil.which("claude") is None:
            pytest.skip("claude CLI not available")

        cmd, _ = adapter.build_command("test prompt", config)
        assert "--disallowedTools" in cmd
        idx = cmd.index("--disallowedTools")
        assert cmd[idx + 1] == "Agent,TeamCreate,SendMessage"

    def test_no_disallowed_tools_when_empty(self):
        adapter = ClaudeAdapter()
        config = SessionConfig(agent="claude")
        import shutil
        if shutil.which("claude") is None:
            pytest.skip("claude CLI not available")

        cmd, _ = adapter.build_command("test prompt", config)
        assert "--disallowedTools" not in cmd


class TestMatrixGeneratesDisallowedTools:
    """Test that generated patterns include disallowed_tools."""

    def test_centralized_pattern_has_disallowed_tools(self, tmp_path: Path):
        manifest = (
            Path(__file__).resolve().parents[1]
            / "configs"
            / "matrices"
            / "swebench_rl_readiness_phase1_claude.yaml"
        )
        result = generate_matrix_patterns(
            manifest,
            output_root=tmp_path / "test",
            wave="broader_panel",
        )

        # Find a centralized condition
        centralized = [
            c for c in result["conditions"]
            if "centralized" in c["condition_id"]
        ]
        assert centralized, "No centralized conditions found"

        config = ExperimentConfig.from_yaml(Path(str(centralized[0]["pattern_path"])))
        for agent in config.agents:
            assert agent.disallowed_tools, f"Agent {agent.id} has no disallowed_tools"
            assert "Agent" in agent.disallowed_tools
            assert "SendMessage" in agent.disallowed_tools

    def test_single_pattern_has_disallowed_tools(self, tmp_path: Path):
        manifest = (
            Path(__file__).resolve().parents[1]
            / "configs"
            / "matrices"
            / "swebench_rl_readiness_phase1_claude.yaml"
        )
        result = generate_matrix_patterns(
            manifest,
            output_root=tmp_path / "test",
            wave="broader_panel",
        )

        single = [
            c for c in result["conditions"]
            if "single" in c["condition_id"]
        ]
        assert single, "No single conditions found"

        config = ExperimentConfig.from_yaml(Path(str(single[0]["pattern_path"])))
        assert len(config.agents) == 1
        agent = config.agents[0]
        assert "Agent" in agent.disallowed_tools
        assert "SendMessage" in agent.disallowed_tools
