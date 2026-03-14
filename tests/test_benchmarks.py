from __future__ import annotations

import json

from helm.benchmarks import available_adapters, get_adapter
from helm.benchmarks.runner import build_benchmark_run_plan
from helm.benchmarks.base import BenchmarkExample
from helm.config import BenchmarkConfig


def _write_jsonl(path, rows: list[dict]) -> None:
    with open(path, "w") as f:
        for row in rows:
            f.write(json.dumps(row))
            f.write("\n")


def test_swebench_adapter_loads_and_filters_examples(tmp_path) -> None:
    dataset_path = tmp_path / "swebench-mini.jsonl"
    _write_jsonl(
        dataset_path,
        [
            {
                "instance_id": "swe-1",
                "split": "verified",
                "problem_statement": "Fix parser bug in tokenizer.",
            },
            {
                "instance_id": "swe-2",
                "split": "test",
                "problem_statement": "Fix race condition in scheduler.",
            },
        ],
    )

    config = BenchmarkConfig(
        adapter="swebench",
        dataset_path=str(dataset_path),
        split="verified",
    )
    adapter = get_adapter(config.adapter)
    examples = adapter.load_examples(config)

    assert len(examples) == 1
    assert examples[0].example_id == "swe-1"
    assert "tokenizer" in examples[0].prompt


def test_tau_bench_adapter_filters_by_example_id(tmp_path) -> None:
    dataset_path = tmp_path / "tau-bench-mini.jsonl"
    _write_jsonl(
        dataset_path,
        [
            {"task_id": "tau-1", "prompt": "Book a hotel in NYC", "split": "dev"},
            {"task_id": "tau-2", "prompt": "Rebook canceled flight", "split": "dev"},
        ],
    )

    config = BenchmarkConfig(
        adapter="tau-bench",
        dataset_path=str(dataset_path),
        split="dev",
        example_ids=["tau-2"],
    )
    adapter = get_adapter(config.adapter)
    examples = adapter.load_examples(config)

    assert len(examples) == 1
    assert examples[0].example_id == "tau-2"
    assert "flight" in examples[0].prompt


def test_available_adapters_lists_expected_names() -> None:
    adapters = available_adapters()
    assert "swebench" in adapters
    assert "tau-bench" in adapters


def test_benchmark_config_alias_and_example_id_dedup() -> None:
    config = BenchmarkConfig.model_validate(
        {
            "adapter": "swebench",
            "dataset_path": "/tmp/data.jsonl",
            "id": "princeton-nlp/SWE-bench_Verified",
            "example_id": "swe-1",
            "example_ids": ["swe-1", "swe-2"],
        }
    )

    assert config.benchmark_id == "princeton-nlp/SWE-bench_Verified"
    assert config.selected_example_ids() == ["swe-1", "swe-2"]


def test_benchmark_config_verifier_helpers() -> None:
    config = BenchmarkConfig(
        adapter="tau-bench",
        dataset_path="/tmp/tau.jsonl",
        verifier={
            "mode": "command",
            "command": "python verify.py",
            "pass_exit_codes": [0, 2],
        },
    )

    assert config.verifier_mode() == "command"
    assert config.verifier_command() == "python verify.py"
    assert config.verifier_pass_exit_codes() == [0, 2]


def test_build_benchmark_run_plan_copies_example_metadata() -> None:
    base_config = {
        "name": "benchmark-test",
        "agents": [{"id": "solver"}],
        "benchmark": {
            "adapter": "swebench",
            "dataset_path": "/tmp/data.jsonl",
        },
    }

    from helm.config import ExperimentConfig

    config = ExperimentConfig.model_validate(base_config)
    examples = [
        BenchmarkExample(
            benchmark="swebench",
            example_id="django__django-1",
            prompt="Solve bug",
            metadata={"repo": "django/django", "base_commit": "abc123"},
        )
    ]

    plan = build_benchmark_run_plan(config, examples)

    assert plan[0].config.benchmark is not None
    assert plan[0].config.benchmark.example_metadata == {
        "repo": "django/django",
        "base_commit": "abc123",
    }
