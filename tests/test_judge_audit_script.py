from __future__ import annotations

import json
import subprocess
from pathlib import Path


def test_audit_judge_reproducibility_reports_complete_metadata(tmp_path: Path) -> None:
    experiment_dir = tmp_path / "exp-audit"
    judge_artifacts = experiment_dir / "judge_artifacts"
    judge_artifacts.mkdir(parents=True)

    (judge_artifacts / "single_input.md").write_text("# Prepared input")
    scores = {
        "schema_version": "v2",
        "experiment_id": "exp-audit",
        "judge_backend": "openrouter",
        "judge_model": "fake-model",
        "strategy": "single",
        "created_at": "2026-03-20T12:00:00+00:00",
        "input_view_type": "merged-transcript",
        "input_preparation": {"used_digest": False, "used_truncation": False},
        "artifacts": {"single_input": "judge_artifacts/single_input.md"},
        "audit": {
            "deterministic_preprocessing": True,
            "nondeterministic_backend": True,
            "rubrics": {
                "goal-drift": {
                    "path": "/tmp/judges/goal-drift.md",
                    "sha256": "abc123",
                }
            },
        },
        "scores": [
            {
                "dimension": "goal-drift",
                "category": "aligned",
                "severity": "none",
                "justification": "ok",
                "evidence": [],
            }
        ],
    }
    (experiment_dir / "scores.json").write_text(json.dumps(scores))

    output_dir = tmp_path / "audit-output"
    script_path = (
        Path(__file__).resolve().parents[1] / "scripts" / "audit_judge_reproducibility.py"
    )
    result = subprocess.run(
        [
            "python",
            str(script_path),
            str(experiment_dir),
            "--output-dir",
            str(output_dir),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr

    summary = json.loads((output_dir / "summary.json").read_text())
    [experiment] = summary["experiments"]
    assert experiment["metadata_complete"] is True
    assert experiment["rubric_hashes_present"] is True
    assert experiment["artifact_references_resolve"] is True
    assert experiment["exact_judge_inputs_present"] is True
