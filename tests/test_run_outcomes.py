from __future__ import annotations

import json

from helm.run_outcomes import (
    backfill_metadata_file,
    merge_normalized_run_record,
    normalize_run_record,
)


def test_normalize_run_record_turn_limit_is_incomplete() -> None:
    normalized = normalize_run_record(
        {
            "success": False,
            "error": "Turn limit reached; experiment ended before completion.",
        }
    )

    assert normalized["success"] is False
    assert normalized["outcome"] == "incomplete"
    assert normalized["termination_reason"] == "turn_limit"
    assert normalized["system_failure"] is False
    assert "Turn limit reached" in str(normalized["message"])
    assert normalized["error"] is None


def test_merge_normalized_run_record_preserves_existing_fields() -> None:
    merged = merge_normalized_run_record(
        {
            "success": False,
            "duration_seconds": 12.0,
            "agent_stats": {"a": {"turns": 50}},
            "error": "Turn limit reached; experiment ended before completion.",
        }
    )

    assert merged["duration_seconds"] == 12.0
    assert merged["agent_stats"] == {"a": {"turns": 50}}
    assert merged["outcome"] == "incomplete"
    assert merged["termination_reason"] == "turn_limit"
    assert merged["system_failure"] is False
    assert merged["error"] is None


def test_backfill_metadata_file_updates_legacy_run_record(tmp_path) -> None:
    metadata_path = tmp_path / "metadata.json"
    metadata_path.write_text(
        json.dumps(
            {
                "experiment_id": "exp-1",
                "run": {
                    "success": False,
                    "duration_seconds": 12.0,
                    "error": "Turn limit reached; experiment ended before completion.",
                    "agent_stats": {"a": {"turns": 50}},
                },
            }
        )
    )

    changed = backfill_metadata_file(metadata_path)
    updated = json.loads(metadata_path.read_text())

    assert changed is True
    assert updated["run"]["outcome"] == "incomplete"
    assert updated["run"]["termination_reason"] == "turn_limit"
    assert updated["run"]["system_failure"] is False
    assert updated["run"]["duration_seconds"] == 12.0
    assert updated["run"]["agent_stats"] == {"a": {"turns": 50}}
    assert updated["run"]["error"] is None

    assert backfill_metadata_file(metadata_path) is False
