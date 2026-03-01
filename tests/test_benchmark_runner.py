from __future__ import annotations

from helm.benchmarks.base import BenchmarkExample
from helm.benchmarks.runner import build_benchmark_run_plan
from helm.config import AgentConfig, BenchmarkConfig, ExperimentConfig


def _base_config() -> ExperimentConfig:
    return ExperimentConfig(
        name="bench-run",
        agents=[AgentConfig(id="orchestrator")],
        benchmark=BenchmarkConfig(
            adapter="swebench",
            dataset_path="/tmp/swebench.jsonl",
            benchmark_id="princeton-nlp/SWE-bench_Verified",
            split="verified",
            seed=42,
        ),
    )


def test_build_benchmark_run_plan_creates_per_example_configs() -> None:
    config = _base_config()
    examples = [
        BenchmarkExample(
            benchmark="swebench",
            example_id="django__1234",
            prompt="Fix bug in parser.",
            metadata={},
        ),
        BenchmarkExample(
            benchmark="swebench",
            example_id="numpy-5678",
            prompt="Fix dtype coercion issue.",
            metadata={},
        ),
    ]

    plan = build_benchmark_run_plan(config, examples)

    assert len(plan) == 2
    assert plan[0].task == "Fix bug in parser."
    assert plan[0].config.benchmark is not None
    assert plan[0].config.benchmark.example_id == "django__1234"
    assert plan[0].config.benchmark.example_ids == ["django__1234"]
    assert plan[0].config.benchmark.max_examples == 1
    assert plan[0].config.name.startswith("bench-run-")

    # Ensure base config remains unchanged
    assert config.benchmark is not None
    assert config.benchmark.example_id is None
    assert config.benchmark.example_ids == []

