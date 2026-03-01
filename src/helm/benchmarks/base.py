"""Shared benchmark adapter types."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from helm.config import BenchmarkConfig


@dataclass(frozen=True)
class BenchmarkExample:
    """A single benchmark example normalized for Helm usage."""

    benchmark: str
    example_id: str
    prompt: str
    metadata: dict[str, Any]


class BenchmarkAdapter(Protocol):
    """Adapter interface for loading benchmark examples."""

    name: str

    def load_examples(
        self,
        config: BenchmarkConfig,
        limit: int | None = None,
    ) -> list[BenchmarkExample]:
        """Load and normalize examples from a benchmark dataset."""


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    """Read JSONL rows into a list of dictionaries."""
    rows: list[dict[str, Any]] = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            raw = json.loads(line)
            if isinstance(raw, dict):
                rows.append(raw)
    return rows

