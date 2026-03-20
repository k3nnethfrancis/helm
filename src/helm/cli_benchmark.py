"""Benchmark-specific CLI helpers."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from helm.cli_shared import ACTIVE_BEHAVIORAL_DIMENSIONS, DIMENSION_SHORT_LABELS
from helm.config import ExperimentConfig
from helm.run_data import save_run_data

MATRIX_FIELD_NAMES = [
    "matrix_id",
    "condition_id",
    "architecture_family",
    "swarm_size",
    "task_pack",
    "task_structure",
    "prompt_family",
    "coordination_family",
]


def merge_dimensions(
    configured: list[str] | None,
    baseline: list[str],
) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()

    for dim in baseline:
        clean = dim.strip()
        if not clean or clean in seen:
            continue
        ordered.append(clean)
        seen.add(clean)

    for dim in configured or []:
        clean = str(dim).strip()
        if not clean or clean in seen:
            continue
        ordered.append(clean)
        seen.add(clean)

    return ordered


def effective_benchmark_dimensions(config: ExperimentConfig) -> list[str]:
    return merge_dimensions(config.evaluation.dimensions, ACTIVE_BEHAVIORAL_DIMENSIONS)


def build_judge_backend_from_config(judge_config) -> tuple[object, str, str | None]:
    from helm.judge import OpenRouterJudge, SDKJudge

    backend_name = (
        judge_config.backend.value
        if hasattr(judge_config.backend, "value")
        else str(judge_config.backend)
    )
    if backend_name == "openrouter":
        judge_model = judge_config.model or "google/gemini-2.0-flash-001"
        return OpenRouterJudge(model=judge_model), backend_name, judge_model
    return SDKJudge(), "sdk", None


def judge_benchmark_experiment(
    experiment_dir: Path,
    config: ExperimentConfig,
    dimensions: list[str],
) -> tuple[Path, dict[str, dict[str, str]]]:
    from helm.judge import judge_experiment

    helm_dir = Path(__file__).parent.parent.parent
    judges_dir = helm_dir / "judges"
    if not judges_dir.exists():
        judges_dir = Path.cwd() / "judges"
    if not judges_dir.exists():
        raise FileNotFoundError("judges/ directory not found")

    judge_backend, backend_name, model_name = build_judge_backend_from_config(
        config.evaluation.judge
    )
    scores = asyncio.run(
        judge_experiment(
            experiment_dir=experiment_dir,
            dimensions=dimensions,
            judges_dir=judges_dir,
            backend=judge_backend,
            backend_name=backend_name,
            model_name=model_name,
            strategy="hierarchical",
        )
    )

    scores_path = experiment_dir / "scores.json"
    scores.save(scores_path)
    save_run_data(experiment_dir)

    score_summary = {
        score.dimension: {
            "category": score.category,
            "severity": score.severity,
        }
        for score in scores.scores
    }
    return scores_path, score_summary


def load_dimension_categories(
    run_data: dict[str, Any],
    fallback_scores: dict[str, Any] | None = None,
) -> dict[str, str]:
    judge = run_data.get("evals", {}).get("judge", {})
    scores = judge.get("scores", {}) if isinstance(judge, dict) else {}
    categories: dict[str, str] = {}

    if isinstance(scores, dict):
        for dim, payload in scores.items():
            if not isinstance(payload, dict):
                continue
            category = payload.get("category")
            if isinstance(category, str) and category.strip():
                categories[dim] = category.strip()

    if categories or not isinstance(fallback_scores, dict):
        return categories

    for dim, payload in fallback_scores.items():
        if not isinstance(payload, dict):
            continue
        category = payload.get("category")
        if isinstance(category, str) and category.strip():
            categories[dim] = category.strip()
    return categories


def compact_behavior_profile(
    categories: dict[str, str],
    dimensions: list[str],
) -> str:
    parts: list[str] = []
    for dim in dimensions:
        category = categories.get(dim)
        if not category:
            continue
        label = DIMENSION_SHORT_LABELS.get(dim, dim)
        parts.append(f"{label}={category}")
    return ", ".join(parts) if parts else "n/a"


def matrix_payload(config: ExperimentConfig) -> dict[str, Any] | None:
    return config.matrix_metadata()


def flatten_matrix_fields(matrix: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(matrix, dict):
        return {field: None for field in MATRIX_FIELD_NAMES}
    return {field: matrix.get(field) for field in MATRIX_FIELD_NAMES}
