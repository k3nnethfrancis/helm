"""tau-bench adapter scaffolding."""

from __future__ import annotations

import random
from pathlib import Path
from typing import Any

from helm.benchmarks.base import BenchmarkExample, read_jsonl
from helm.config import BenchmarkConfig


def _first_str(row: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None


class TauBenchAdapter:
    """Loads tau-bench-style JSONL rows into normalized examples."""

    name = "tau-bench"

    def load_examples(
        self,
        config: BenchmarkConfig,
        limit: int | None = None,
    ) -> list[BenchmarkExample]:
        dataset_path = Path(config.dataset_path).expanduser()
        rows = read_jsonl(dataset_path)

        if config.seed is not None:
            rng = random.Random(config.seed)
            rng.shuffle(rows)

        selected_ids = set(config.selected_example_ids())
        normalized: list[BenchmarkExample] = []

        for row in rows:
            split = _first_str(row, ("split",))
            if config.split and split and split != config.split:
                continue

            example_id = _first_str(
                row,
                ("task_id", "example_id", "id"),
            )
            if not example_id:
                continue
            if selected_ids and example_id not in selected_ids:
                continue

            prompt = _first_str(
                row,
                ("prompt", "task", "instruction"),
            )
            if not prompt:
                continue

            normalized.append(
                BenchmarkExample(
                    benchmark=self.name,
                    example_id=example_id,
                    prompt=prompt,
                    metadata=row,
                )
            )

            if limit is not None and len(normalized) >= limit:
                break
            if config.max_examples is not None and len(normalized) >= config.max_examples:
                break

        return normalized

