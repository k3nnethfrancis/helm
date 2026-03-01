"""Helpers for executing benchmark-backed experiment batches."""

from __future__ import annotations

import re
from dataclasses import dataclass

from helm.benchmarks.base import BenchmarkExample
from helm.config import ExperimentConfig

_MAX_EXAMPLE_NAME_LEN = 32


@dataclass(frozen=True)
class BenchmarkRunPlanEntry:
    """One planned benchmark run for a single example."""

    example: BenchmarkExample
    config: ExperimentConfig
    task: str


def _sanitize_for_name(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-").lower()
    if not cleaned:
        return "example"
    return cleaned[:_MAX_EXAMPLE_NAME_LEN]


def build_benchmark_run_plan(
    base_config: ExperimentConfig,
    examples: list[BenchmarkExample],
) -> list[BenchmarkRunPlanEntry]:
    """Create per-example configs/tasks for benchmark execution."""
    if base_config.benchmark is None:
        raise ValueError("Experiment config must include a benchmark block.")

    planned: list[BenchmarkRunPlanEntry] = []

    for example in examples:
        config = base_config.model_copy(deep=True)
        if config.benchmark is None:
            raise ValueError("Benchmark config missing from copied experiment config.")

        config.benchmark.example_id = example.example_id
        config.benchmark.example_ids = [example.example_id]
        config.benchmark.max_examples = 1

        suffix = _sanitize_for_name(example.example_id)
        config.name = f"{base_config.name}-{suffix}"

        planned.append(
            BenchmarkRunPlanEntry(
                example=example,
                config=config,
                task=example.prompt,
            )
        )

    return planned

