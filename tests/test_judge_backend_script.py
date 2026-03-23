from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path


def test_backend_comparison_script_help() -> None:
    script_path = (
        Path(__file__).resolve().parents[1] / "scripts" / "run_judge_backend_comparison.py"
    )
    result = subprocess.run(
        ["python", str(script_path), "--help"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "Compare multiple judge backends" in result.stdout
    assert "--primary-backend" in result.stdout


def test_backend_comparison_flush_outputs_writes_partial_artifacts(tmp_path: Path) -> None:
    script_path = (
        Path(__file__).resolve().parents[1] / "scripts" / "run_judge_backend_comparison.py"
    )
    spec = importlib.util.spec_from_file_location("judge_backend_script", script_path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)

    summary = {
        "dimensions": ["goal-drift"],
        "backends": [{"role": "primary", "backend": "codex-headless"}],
        "experiments": {
            "exp-1": {
                "context": {"pattern": "p", "outcome": "incomplete", "termination_reason": "turn_limit"},
                "outcomes": {
                    "primary:codex-headless": {
                        "categories": {"goal-drift": "aligned"},
                        "severities": {"goal-drift": "none"},
                    }
                },
            }
        },
    }

    module._flush_outputs(
        output_dir=tmp_path,
        summary=summary,
        dimensions=["goal-drift"],
        specs=[("primary", "codex-headless")],
    )

    summary_path = tmp_path / "summary.json"
    report_path = tmp_path / "report.md"
    assert summary_path.exists()
    assert report_path.exists()
    assert json.loads(summary_path.read_text())["experiments"]["exp-1"]["outcomes"][
        "primary:codex-headless"
    ]["categories"]["goal-drift"] == "aligned"
    assert "exp-1" in report_path.read_text()


def test_backend_comparison_load_existing_backend_outcome(tmp_path: Path) -> None:
    script_path = (
        Path(__file__).resolve().parents[1] / "scripts" / "run_judge_backend_comparison.py"
    )
    spec = importlib.util.spec_from_file_location("judge_backend_script_load", script_path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)

    score_path = tmp_path / "primary-codex-headless.json"
    score_path.write_text(
        json.dumps(
            {
                "judge_model": "gpt-5",
                "input_view_type": "hierarchical-synthesis",
                "preparation_path": "hierarchical-synthesis",
                "input_preparation": {"used_digest": False},
                "artifacts": {"foo": "bar"},
                "scores": [
                    {
                        "dimension": "goal-drift",
                        "category": "aligned",
                        "severity": "none",
                    }
                ],
            }
        )
    )

    outcome = module._load_existing_backend_outcome(
        score_path,
        backend="codex-headless",
        role="primary",
    )

    assert outcome.backend == "codex-headless"
    assert outcome.model == "gpt-5"
    assert outcome.categories["goal-drift"] == "aligned"
    assert outcome.severities["goal-drift"] == "none"
