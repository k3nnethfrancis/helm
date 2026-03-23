"""Tests for helm.agent_cli — topology-controlled agent coordination CLI."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import pytest

from helm import agent_cli


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_CONFIG = {
    "family": "centralized",
    "experiment_id": "test-exp",
    "harness": "claude-code",
    "agents": {
        "coordinator": {
            "role": "hub",
            "can_spawn": False,
            "can_message": ["worker_a", "worker_b"],
        },
        "worker_a": {
            "role": "worker",
            "can_spawn": False,
            "can_message": ["coordinator"],
        },
        "worker_b": {
            "role": "worker",
            "can_spawn": False,
            "can_message": ["coordinator"],
        },
    },
    "disallowed_tools_base": ["Agent", "TeamCreate", "SendMessage"],
    "max_spawn_depth": 1,
}


@pytest.fixture()
def coord_dir(tmp_path: Path) -> Path:
    """Create a coordination directory with .helm-config.json."""
    coordination = tmp_path / "coordination"
    coordination.mkdir()
    config_path = coordination / ".helm-config.json"
    config_path.write_text(json.dumps(SAMPLE_CONFIG))
    return coordination


@pytest.fixture()
def _chdir_to_tmp(coord_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Change cwd so _find_config() discovers the config by walking up."""
    monkeypatch.chdir(coord_dir.parent)


@pytest.fixture()
def _env_coord_dir(coord_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Point HELM_COORDINATION_DIR to the coordination directory."""
    monkeypatch.setenv("HELM_COORDINATION_DIR", str(coord_dir))


def _ns(**kwargs) -> argparse.Namespace:
    """Build an argparse.Namespace from keyword arguments."""
    return argparse.Namespace(**kwargs)


# ---------------------------------------------------------------------------
# _find_config
# ---------------------------------------------------------------------------


class TestFindConfig:
    """Tests for _find_config()."""

    @pytest.mark.usefixtures("_chdir_to_tmp")
    def test_finds_config_via_cwd(self, coord_dir: Path) -> None:
        config = agent_cli._find_config()
        assert config["experiment_id"] == "test-exp"
        assert "coordinator" in config["agents"]

    def test_finds_config_via_env_var(
        self, coord_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Point env var at the coordination dir; cwd is unrelated
        monkeypatch.chdir("/")
        monkeypatch.setenv("HELM_COORDINATION_DIR", str(coord_dir))
        config = agent_cli._find_config()
        assert config["experiment_id"] == "test-exp"

    def test_exits_when_no_config(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("HELM_COORDINATION_DIR", raising=False)
        with pytest.raises(SystemExit) as exc_info:
            agent_cli._find_config()
        assert exc_info.value.code == 1


# ---------------------------------------------------------------------------
# cmd_send
# ---------------------------------------------------------------------------


class TestCmdSend:
    """Tests for the send command."""

    @pytest.mark.usefixtures("_chdir_to_tmp")
    def test_successful_send(self, coord_dir: Path, capsys) -> None:
        agent_cli.cmd_send(_ns(sender="coordinator", to="worker_a", msg="Do the thing"))

        stdout = capsys.readouterr().out
        assert "Message sent from coordinator to worker_a" in stdout

        # Verify message file was created
        messages = list((coord_dir / "messages").glob("*-coordinator-to-worker_a.md"))
        assert len(messages) == 1
        content = messages[0].read_text()
        assert "From: coordinator" in content
        assert "To: worker_a" in content
        assert "Do the thing" in content

    @pytest.mark.usefixtures("_chdir_to_tmp")
    def test_send_reverse_direction(self, coord_dir: Path, capsys) -> None:
        """Worker can send to coordinator (allowed by topology)."""
        agent_cli.cmd_send(_ns(sender="worker_a", to="coordinator", msg="Done"))

        stdout = capsys.readouterr().out
        assert "Message sent from worker_a to coordinator" in stdout

    @pytest.mark.usefixtures("_chdir_to_tmp")
    def test_send_unknown_sender(self) -> None:
        with pytest.raises(SystemExit) as exc_info:
            agent_cli.cmd_send(_ns(sender="ghost", to="coordinator", msg="hello"))
        assert exc_info.value.code == 1

    @pytest.mark.usefixtures("_chdir_to_tmp")
    def test_send_unknown_recipient(self) -> None:
        with pytest.raises(SystemExit) as exc_info:
            agent_cli.cmd_send(_ns(sender="coordinator", to="ghost", msg="hello"))
        assert exc_info.value.code == 1

    @pytest.mark.usefixtures("_chdir_to_tmp")
    def test_topology_violation_worker_to_worker(self, capsys) -> None:
        """Workers can only message the coordinator in centralized topology."""
        with pytest.raises(SystemExit) as exc_info:
            agent_cli.cmd_send(_ns(sender="worker_a", to="worker_b", msg="hey"))
        assert exc_info.value.code == 1

        stderr = capsys.readouterr().err
        assert "Topology violation" in stderr
        assert "worker_a" in stderr

    @pytest.mark.usefixtures("_chdir_to_tmp")
    def test_send_creates_messages_dir(self, coord_dir: Path) -> None:
        """Messages directory is created if it doesn't exist."""
        assert not (coord_dir / "messages").exists()
        agent_cli.cmd_send(_ns(sender="coordinator", to="worker_a", msg="init"))
        assert (coord_dir / "messages").is_dir()


# ---------------------------------------------------------------------------
# cmd_inbox
# ---------------------------------------------------------------------------


class TestCmdInbox:
    """Tests for the inbox command."""

    @pytest.mark.usefixtures("_chdir_to_tmp")
    def test_inbox_returns_messages(self, coord_dir: Path, capsys) -> None:
        # Pre-create a message file
        messages_dir = coord_dir / "messages"
        messages_dir.mkdir()
        msg = messages_dir / "20260322-120000-worker_a-to-coordinator.md"
        msg.write_text("From: worker_a\nTo: coordinator\n\nI'm done.")

        agent_cli.cmd_inbox(_ns(agent="coordinator"))

        stdout = capsys.readouterr().out
        assert "I'm done." in stdout
        assert "worker_a-to-coordinator" in stdout

    @pytest.mark.usefixtures("_chdir_to_tmp")
    def test_inbox_no_messages(self, coord_dir: Path, capsys) -> None:
        messages_dir = coord_dir / "messages"
        messages_dir.mkdir()

        agent_cli.cmd_inbox(_ns(agent="coordinator"))

        stdout = capsys.readouterr().out
        assert "No messages for coordinator" in stdout

    @pytest.mark.usefixtures("_chdir_to_tmp")
    def test_inbox_no_messages_dir(self, coord_dir: Path, capsys) -> None:
        """If messages/ doesn't exist at all, still reports no messages."""
        agent_cli.cmd_inbox(_ns(agent="coordinator"))

        stdout = capsys.readouterr().out
        assert "No messages." in stdout

    @pytest.mark.usefixtures("_chdir_to_tmp")
    def test_inbox_only_own_messages(self, coord_dir: Path, capsys) -> None:
        """Agent only sees messages addressed to them."""
        messages_dir = coord_dir / "messages"
        messages_dir.mkdir()
        (messages_dir / "20260322-120000-coordinator-to-worker_a.md").write_text("task A")
        (messages_dir / "20260322-120001-coordinator-to-worker_b.md").write_text("task B")

        agent_cli.cmd_inbox(_ns(agent="worker_a"))

        stdout = capsys.readouterr().out
        assert "task A" in stdout
        assert "task B" not in stdout


# ---------------------------------------------------------------------------
# cmd_status
# ---------------------------------------------------------------------------


class TestCmdStatus:
    """Tests for the status command."""

    @pytest.mark.usefixtures("_chdir_to_tmp")
    def test_status_known_agent(self, capsys) -> None:
        agent_cli.cmd_status(_ns(agent="coordinator"))

        stdout = capsys.readouterr().out
        assert "Agent: coordinator" in stdout
        assert "Role: hub" in stdout
        assert "Can spawn: False" in stdout

    @pytest.mark.usefixtures("_chdir_to_tmp")
    def test_status_worker(self, capsys) -> None:
        agent_cli.cmd_status(_ns(agent="worker_a"))

        stdout = capsys.readouterr().out
        assert "Agent: worker_a" in stdout
        assert "Role: worker" in stdout

    @pytest.mark.usefixtures("_chdir_to_tmp")
    def test_status_unknown_agent(self) -> None:
        with pytest.raises(SystemExit) as exc_info:
            agent_cli.cmd_status(_ns(agent="ghost"))
        assert exc_info.value.code == 1

    @pytest.mark.usefixtures("_chdir_to_tmp")
    def test_status_shows_tasks(self, coord_dir: Path, capsys) -> None:
        """Status reports task assignment files if present."""
        tasks_dir = coord_dir / "tasks"
        tasks_dir.mkdir()
        (tasks_dir / "task-worker_a-001.md").write_text("fix the bug")

        agent_cli.cmd_status(_ns(agent="worker_a"))

        stdout = capsys.readouterr().out
        assert "Task assignments: 1" in stdout
        assert "task-worker_a-001.md" in stdout

    @pytest.mark.usefixtures("_chdir_to_tmp")
    def test_status_shows_signals(self, coord_dir: Path, capsys) -> None:
        signals_dir = coord_dir / "signals"
        signals_dir.mkdir()
        (signals_dir / "done-worker_a.md").write_text("done")

        agent_cli.cmd_status(_ns(agent="worker_a"))

        stdout = capsys.readouterr().out
        assert "Signals:" in stdout
        assert "done-worker_a.md" in stdout


# ---------------------------------------------------------------------------
# cmd_spawn — validation logic only (no subprocess)
# ---------------------------------------------------------------------------


class TestCmdSpawn:
    """Tests for spawn command validation (not subprocess execution)."""

    @pytest.mark.usefixtures("_chdir_to_tmp")
    def test_spawn_rejected_cant_spawn(self, capsys) -> None:
        """Coordinator has can_spawn=False, so spawn is rejected."""
        with pytest.raises(SystemExit) as exc_info:
            agent_cli.cmd_spawn(_ns(parent="coordinator", task="do stuff", role="worker"))
        assert exc_info.value.code == 1

        stderr = capsys.readouterr().err
        assert "Topology violation" in stderr
        assert "cannot spawn" in stderr

    @pytest.mark.usefixtures("_chdir_to_tmp")
    def test_spawn_rejected_unknown_parent(self) -> None:
        with pytest.raises(SystemExit) as exc_info:
            agent_cli.cmd_spawn(_ns(parent="ghost", task="do stuff", role="worker"))
        assert exc_info.value.code == 1

    def test_spawn_rejected_max_depth(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Spawn depth check prevents exceeding max_spawn_depth."""
        # Create a config where coordinator CAN spawn
        config = {
            **SAMPLE_CONFIG,
            "agents": {
                **SAMPLE_CONFIG["agents"],
                "coordinator": {
                    "role": "hub",
                    "can_spawn": True,
                    "can_message": ["worker_a", "worker_b"],
                },
            },
            "max_spawn_depth": 1,
        }
        coordination = tmp_path / "coordination"
        coordination.mkdir()
        (coordination / ".helm-config.json").write_text(json.dumps(config))
        monkeypatch.chdir(tmp_path)

        # Set HELM_SPAWN_DEPTH to already be at max
        monkeypatch.setenv("HELM_SPAWN_DEPTH", "1")

        with pytest.raises(SystemExit) as exc_info:
            agent_cli.cmd_spawn(_ns(parent="coordinator", task="sub-task", role="worker"))
        assert exc_info.value.code == 1

    def test_spawn_rejected_worker_cant_spawn(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Workers with can_spawn=False are rejected."""
        coordination = tmp_path / "coordination"
        coordination.mkdir()
        (coordination / ".helm-config.json").write_text(json.dumps(SAMPLE_CONFIG))
        monkeypatch.chdir(tmp_path)

        with pytest.raises(SystemExit) as exc_info:
            agent_cli.cmd_spawn(_ns(parent="worker_a", task="sub-task", role="worker"))
        assert exc_info.value.code == 1


# ---------------------------------------------------------------------------
# _coordination_dir
# ---------------------------------------------------------------------------


class TestCoordinationDir:
    """Tests for _coordination_dir()."""

    @pytest.mark.usefixtures("_chdir_to_tmp")
    def test_finds_via_cwd(self, coord_dir: Path) -> None:
        result = agent_cli._coordination_dir(SAMPLE_CONFIG)
        assert result == coord_dir

    def test_finds_via_env_var(
        self, coord_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HELM_COORDINATION_DIR", str(coord_dir))
        result = agent_cli._coordination_dir(SAMPLE_CONFIG)
        assert result == coord_dir
