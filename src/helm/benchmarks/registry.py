"""Registry for benchmark adapters."""

from __future__ import annotations

from helm.benchmarks.base import BenchmarkAdapter
from helm.benchmarks.swebench import SWEBenchAdapter
from helm.benchmarks.taubench import TauBenchAdapter

_REGISTRY: dict[str, BenchmarkAdapter] = {
    "swebench": SWEBenchAdapter(),
    "swe-bench": SWEBenchAdapter(),
    "tau-bench": TauBenchAdapter(),
    "taubench": TauBenchAdapter(),
}


def available_adapters() -> list[str]:
    """Return sorted adapter names."""
    return sorted(_REGISTRY.keys())


def get_adapter(name: str) -> BenchmarkAdapter:
    """Resolve an adapter by name."""
    key = name.strip().lower()
    adapter = _REGISTRY.get(key)
    if adapter is None:
        valid = ", ".join(available_adapters())
        raise ValueError(f"Unknown benchmark adapter '{name}'. Available: {valid}")
    return adapter

