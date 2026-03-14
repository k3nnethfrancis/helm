from __future__ import annotations

import json

from typer.testing import CliRunner

from helm.cli import app


def test_backfill_run_metadata_command_updates_legacy_metadata(tmp_path) -> None:
    runner = CliRunner()
    experiment_dir = tmp_path / "exp-legacy"
    experiment_dir.mkdir(parents=True)
    (experiment_dir / "metadata.json").write_text(
        json.dumps(
            {
                "experiment_id": "exp-legacy",
                "run": {
                    "success": False,
                    "error": "Turn limit reached; experiment ended before completion.",
                },
            }
        )
    )

    result = runner.invoke(
        app,
        [
            "backfill-run-metadata",
            "--experiments-dir",
            str(tmp_path),
            "--no-refresh-run-data",
        ],
    )

    assert result.exit_code == 0
    assert "Metadata updated: 1" in result.stdout
    assert "Metadata unchanged: 0" in result.stdout

    updated = json.loads((experiment_dir / "metadata.json").read_text())
    assert updated["run"]["outcome"] == "incomplete"
    assert updated["run"]["termination_reason"] == "turn_limit"
    assert updated["run"]["system_failure"] is False
    assert updated["run"]["error"] is None


def test_backfill_run_metadata_command_normalizes_single_agent_pattern(tmp_path) -> None:
    runner = CliRunner()
    experiment_dir = tmp_path / "exp-single"
    experiment_dir.mkdir(parents=True)
    (experiment_dir / "metadata.json").write_text(
        json.dumps(
            {
                "experiment_id": "exp-single",
                "pattern": "peer-network",
                "agents": [{"id": "solo", "role": None}],
                "run": {
                    "success": True,
                    "outcome": "completed",
                    "termination_reason": "completion_signal",
                    "system_failure": False,
                },
            }
        )
    )

    result = runner.invoke(
        app,
        [
            "backfill-run-metadata",
            "--experiments-dir",
            str(tmp_path),
            "--no-refresh-run-data",
        ],
    )

    assert result.exit_code == 0
    assert "Metadata updated: 1" in result.stdout

    updated = json.loads((experiment_dir / "metadata.json").read_text())
    assert updated["pattern"] == "single-agent"
