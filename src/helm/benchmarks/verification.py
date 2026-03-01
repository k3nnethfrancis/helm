"""Benchmark task verification helpers."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from helm.benchmarks.base import BenchmarkExample
from helm.config import BenchmarkConfig


@dataclass(frozen=True)
class TaskVerification:
    """Normalized task verification payload."""

    status: str
    score: float | None
    reason: str | None
    details: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "score": self.score,
            "reason": self.reason,
            "details": self.details,
        }


def _completion_verification(success: bool, error: str | None) -> TaskVerification:
    status = "pass" if success else "fail"
    score = 1.0 if success else 0.0
    reason = (
        "Run reached completion signals."
        if success
        else f"Run failed before completion signals: {error or 'unknown error'}"
    )
    return TaskVerification(
        status=status,
        score=score,
        reason=reason,
        details={
            "mode": "completion",
            "run_success": success,
            "run_error": error,
        },
    )


def _parse_command_output(stdout: str) -> dict[str, Any] | None:
    text = stdout.strip()
    if not text:
        return None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None
    if isinstance(payload, dict):
        return payload
    return None


def _command_verification(
    benchmark: BenchmarkConfig,
    example: BenchmarkExample,
    experiment_dir: Path,
) -> TaskVerification:
    command = benchmark.verifier_command()
    if command is None:
        return TaskVerification(
            status="unknown",
            score=None,
            reason="Verifier mode is command but no command was configured.",
            details={"mode": "command"},
        )

    context = {
        "experiment_dir": str(experiment_dir),
        "dataset_path": benchmark.dataset_path,
        "benchmark_id": benchmark.benchmark_id or "",
        "adapter": benchmark.adapter,
        "example_id": example.example_id,
        "split": benchmark.split or "",
    }

    rendered = command
    for key, value in context.items():
        rendered = rendered.replace(f"{{{key}}}", str(value))

    proc = subprocess.run(
        rendered,
        shell=True,
        cwd=str(experiment_dir),
        capture_output=True,
        text=True,
    )

    parsed = _parse_command_output(proc.stdout)
    pass_exit_codes = benchmark.verifier_pass_exit_codes()
    command_passed = proc.returncode in pass_exit_codes

    if parsed is not None:
        status = str(parsed.get("status", "pass" if command_passed else "fail"))
        score_raw = parsed.get("score")
        score = float(score_raw) if isinstance(score_raw, (int, float)) else None
        reason = parsed.get("reason")
        if reason is not None:
            reason = str(reason)
        details = parsed.get("details")
        if not isinstance(details, dict):
            details = {}
        details.update(
            {
                "mode": "command",
                "command": rendered,
                "returncode": proc.returncode,
                "stdout": proc.stdout.strip(),
                "stderr": proc.stderr.strip(),
            }
        )
        return TaskVerification(
            status=status,
            score=score,
            reason=reason,
            details=details,
        )

    status = "pass" if command_passed else "fail"
    score = 1.0 if command_passed else 0.0
    reason = (
        f"Verifier command exited with {proc.returncode}."
        if command_passed
        else f"Verifier command failed with exit code {proc.returncode}."
    )
    return TaskVerification(
        status=status,
        score=score,
        reason=reason,
        details={
            "mode": "command",
            "command": rendered,
            "returncode": proc.returncode,
            "stdout": proc.stdout.strip(),
            "stderr": proc.stderr.strip(),
            "pass_exit_codes": pass_exit_codes,
        },
    )


def verify_benchmark_run(
    benchmark: BenchmarkConfig,
    example: BenchmarkExample,
    experiment_dir: Path,
    run_success: bool,
    run_error: str | None,
) -> TaskVerification:
    """Verify benchmark run and return normalized task verification payload."""
    mode = benchmark.verifier_mode()
    if mode == "command":
        return _command_verification(benchmark, example, experiment_dir)
    return _completion_verification(run_success, run_error)


def write_task_verification(
    experiment_dir: Path,
    verification: TaskVerification,
) -> Path:
    """Write task verification artifact in the standard location."""
    out_dir = experiment_dir / "evaluation"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "task_verification.json"
    with open(out_path, "w") as f:
        json.dump(verification.to_dict(), f, indent=2)
    return out_path
