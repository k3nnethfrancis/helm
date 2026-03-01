from __future__ import annotations

import json
from pathlib import Path

from helm.benchmarks.base import BenchmarkExample
from helm.benchmarks.verification import verify_benchmark_run, write_task_verification
from helm.config import BenchmarkConfig


def _example() -> BenchmarkExample:
    return BenchmarkExample(
        benchmark="swebench",
        example_id="ex-1",
        prompt="Solve task",
        metadata={},
    )


def test_completion_verification_pass(tmp_path: Path) -> None:
    benchmark = BenchmarkConfig(
        adapter="swebench",
        dataset_path="/tmp/data.jsonl",
        verifier={"mode": "completion"},
    )
    verification = verify_benchmark_run(
        benchmark=benchmark,
        example=_example(),
        experiment_dir=tmp_path,
        run_success=True,
        run_error=None,
    )
    assert verification.status == "pass"
    assert verification.score == 1.0


def test_command_verification_uses_exit_code(tmp_path: Path) -> None:
    benchmark = BenchmarkConfig(
        adapter="tau-bench",
        dataset_path="/tmp/data.jsonl",
        verifier={
            "mode": "command",
            "command": "sh -c 'exit 0'",
            "pass_exit_codes": [0],
        },
    )
    verification = verify_benchmark_run(
        benchmark=benchmark,
        example=_example(),
        experiment_dir=tmp_path,
        run_success=False,
        run_error="unused",
    )
    assert verification.status == "pass"
    assert verification.score == 1.0


def test_command_verification_parses_json_stdout(tmp_path: Path) -> None:
    script = tmp_path / "verify.sh"
    script.write_text(
        "#!/bin/sh\n"
        "echo '{\"status\":\"partial\",\"score\":0.25,\"reason\":\"ok\"}'\n"
    )
    script.chmod(0o755)

    benchmark = BenchmarkConfig(
        adapter="swebench",
        dataset_path="/tmp/data.jsonl",
        verifier={
            "mode": "command",
            "command": str(script),
        },
    )
    verification = verify_benchmark_run(
        benchmark=benchmark,
        example=_example(),
        experiment_dir=tmp_path,
        run_success=False,
        run_error=None,
    )
    assert verification.status == "partial"
    assert verification.score == 0.25
    assert verification.reason == "ok"


def test_write_task_verification_creates_standard_artifact(tmp_path: Path) -> None:
    benchmark = BenchmarkConfig(
        adapter="swebench",
        dataset_path="/tmp/data.jsonl",
    )
    verification = verify_benchmark_run(
        benchmark=benchmark,
        example=_example(),
        experiment_dir=tmp_path,
        run_success=False,
        run_error="failed",
    )
    out_path = write_task_verification(tmp_path, verification)
    assert out_path.name == "task_verification.json"
    data = json.loads(out_path.read_text())
    assert data["status"] == "fail"
    assert data["details"]["mode"] == "completion"
