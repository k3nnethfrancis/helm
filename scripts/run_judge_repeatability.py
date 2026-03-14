#!/usr/bin/env python3
"""Run repeated behavioral judging over a fixed experiment sample.

Saves each repeat as its own JSON artifact and writes a compact summary with
per-dimension agreement statistics.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from helm.judge import (
    DIMENSION_CATEGORIES,
    SEVERITY_ORDER,
    ExperimentScores,
    OpenRouterJudge,
    SDKJudge,
    judge_experiment,
)

DEFAULT_DIMENSIONS = [
    "escalation-calibration",
    "goal-drift",
    "failure-suppression",
    "context-degradation",
    "resource-waste",
]


@dataclass
class PairwiseAgreement:
    exact_pairs: int
    within_one_pairs: int
    total_pairs: int

    def to_dict(self) -> dict[str, float | int]:
        exact_rate = self.exact_pairs / self.total_pairs if self.total_pairs else 0.0
        within_one_rate = self.within_one_pairs / self.total_pairs if self.total_pairs else 0.0
        return {
            "exact_pairs": self.exact_pairs,
            "within_one_pairs": self.within_one_pairs,
            "total_pairs": self.total_pairs,
            "exact_rate": round(exact_rate, 4),
            "within_one_rate": round(within_one_rate, 4),
        }


def _parse_args() -> argparse.Namespace:
    repo_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "experiment_ids",
        nargs="+",
        help="Experiment directory names under experiments/",
    )
    parser.add_argument(
        "--repeats",
        type=int,
        default=3,
        help="Number of repeated judge runs per experiment (default: 3)",
    )
    parser.add_argument(
        "--dimensions",
        default=",".join(DEFAULT_DIMENSIONS),
        help="Comma-separated dimensions to judge",
    )
    parser.add_argument(
        "--backend",
        default="sdk",
        choices=("sdk", "openrouter"),
        help="Judge backend to use",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=180.0,
        help="Per-run timeout budget for the SDK judge backend (default: 180s)",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="OpenRouter model name (required only for openrouter backend)",
    )
    parser.add_argument(
        "--experiments-dir",
        type=Path,
        default=repo_root / "experiments",
        help="Directory containing experiment folders",
    )
    parser.add_argument(
        "--judges-dir",
        type=Path,
        default=repo_root / "judges",
        help="Directory containing judge rubrics",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Directory to store repeatability artifacts",
    )
    return parser.parse_args()


def _load_experiment_context(experiment_dir: Path) -> dict[str, object]:
    context: dict[str, object] = {}

    metadata_path = experiment_dir / "metadata.json"
    if metadata_path.exists():
        metadata = json.loads(metadata_path.read_text())
        run = metadata.get("run", {})
        benchmark = metadata.get("benchmark", {})
        context["pattern"] = metadata.get("pattern")
        context["task"] = metadata.get("task")
        if isinstance(run, dict):
            context["run_outcome"] = run.get("outcome")
            context["termination_reason"] = run.get("termination_reason")
            context["system_failure"] = run.get("system_failure")
        if isinstance(benchmark, dict):
            context["example_id"] = benchmark.get("example_id")
            context["adapter"] = benchmark.get("adapter")

    verification_path = experiment_dir / "evaluation" / "task_verification.json"
    if verification_path.exists():
        verification = json.loads(verification_path.read_text())
        context["verification"] = {
            "status": verification.get("status"),
            "score": verification.get("score"),
            "reason": verification.get("reason"),
        }

    return context


def _load_existing_run_payload(run_path: Path) -> dict[str, object] | None:
    try:
        payload = json.loads(run_path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _score_entries_from_payload(
    payload: dict[str, object],
    dimensions: list[str],
) -> dict[str, list[dict[str, str]]]:
    per_dimension: dict[str, list[dict[str, str]]] = {dim: [] for dim in dimensions}
    scores = payload.get("scores", [])
    if not isinstance(scores, list):
        return per_dimension

    for raw_score in scores:
        if not isinstance(raw_score, dict):
            continue
        dimension = raw_score.get("dimension")
        category = raw_score.get("category")
        severity = raw_score.get("severity")
        if not isinstance(dimension, str) or dimension not in per_dimension:
            continue
        if not isinstance(category, str) or not isinstance(severity, str):
            continue
        per_dimension[dimension].append(
            {
                "dimension": dimension,
                "category": category,
                "severity": severity,
            }
        )
    return per_dimension


def _severity_index(dimension: str, category: str, severity: str) -> int:
    severity_name = severity
    if category in DIMENSION_CATEGORIES.get(dimension, {}):
        severity_name = DIMENSION_CATEGORIES[dimension][category]
    try:
        return SEVERITY_ORDER.index(severity_name)
    except ValueError:
        return SEVERITY_ORDER.index("moderate")


def _pairwise_agreement(entries: list[dict[str, str]]) -> PairwiseAgreement:
    exact_pairs = 0
    within_one_pairs = 0
    total_pairs = 0
    for i, left in enumerate(entries):
        for right in entries[i + 1 :]:
            total_pairs += 1
            if left["category"] == right["category"]:
                exact_pairs += 1
            left_idx = _severity_index(left["dimension"], left["category"], left["severity"])
            right_idx = _severity_index(right["dimension"], right["category"], right["severity"])
            if abs(left_idx - right_idx) <= 1:
                within_one_pairs += 1
    return PairwiseAgreement(
        exact_pairs=exact_pairs,
        within_one_pairs=within_one_pairs,
        total_pairs=total_pairs,
    )


async def _build_backend(args: argparse.Namespace):
    if args.backend == "sdk":
        return SDKJudge(timeout_seconds=args.timeout_seconds), "sdk", None
    model = args.model or "google/gemini-2.0-flash-001"
    return OpenRouterJudge(model=model), "openrouter", model


async def _run_once(
    experiment_dir: Path,
    dimensions: list[str],
    judges_dir: Path,
    backend,
    backend_name: str,
    model_name: str | None,
) -> ExperimentScores:
    return await judge_experiment(
        experiment_dir=experiment_dir,
        dimensions=dimensions,
        judges_dir=judges_dir,
        backend=backend,
        backend_name=backend_name,
        model_name=model_name,
    )


async def main() -> int:
    args = _parse_args()
    dimensions = [d.strip() for d in args.dimensions.split(",") if d.strip()]
    backend, backend_name, model_name = await _build_backend(args)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    scores_root = args.output_dir / "scores"
    summary: dict[str, object] = {
        "backend": backend_name,
        "model": model_name,
        "repeats": args.repeats,
        "timeout_seconds": args.timeout_seconds if backend_name == "sdk" else None,
        "dimensions": dimensions,
        "experiments": {},
    }

    all_dimension_entries: dict[str, list[dict[str, str]]] = {dim: [] for dim in dimensions}

    for experiment_id in args.experiment_ids:
        experiment_dir = args.experiments_dir / experiment_id
        if not experiment_dir.exists():
            raise FileNotFoundError(f"Experiment not found: {experiment_dir}")

        print(f"[repeatability] {experiment_id}", flush=True)
        experiment_scores_dir = scores_root / experiment_id
        experiment_scores_dir.mkdir(parents=True, exist_ok=True)
        experiment_context = _load_experiment_context(experiment_dir)

        run_results: list[dict[str, object]] = []
        per_dimension: dict[str, list[dict[str, str]]] = {dim: [] for dim in dimensions}
        run_status_counts: Counter[str] = Counter()
        run_errors: list[dict[str, object]] = []

        for repeat in range(1, args.repeats + 1):
            run_path = experiment_scores_dir / f"run-{repeat}.json"
            existing_payload = _load_existing_run_payload(run_path) if run_path.exists() else None
            if existing_payload is not None:
                print(f"  run {repeat}/{args.repeats} (cached)", flush=True)
                run_status = str(existing_payload.get("status", "ok"))
                run_status_counts[run_status] += 1
                run_results.append(
                    {
                        "repeat": repeat,
                        "path": str(run_path),
                        "status": run_status,
                        "cached": True,
                    }
                )
                cached_entries = _score_entries_from_payload(existing_payload, dimensions)
                for dimension, entries in cached_entries.items():
                    per_dimension[dimension].extend(entries)
                    all_dimension_entries[dimension].extend(entries)
                error_payload = existing_payload.get("error")
                if isinstance(error_payload, dict):
                    run_errors.append({"repeat": repeat, **error_payload})
                continue

            print(f"  run {repeat}/{args.repeats}", flush=True)
            try:
                result = await _run_once(
                    experiment_dir=experiment_dir,
                    dimensions=dimensions,
                    judges_dir=args.judges_dir,
                    backend=backend,
                    backend_name=backend_name,
                    model_name=model_name,
                )
                payload: dict[str, object] = result.to_dict()
                payload["status"] = "ok"
            except Exception as exc:
                payload = {
                    "schema_version": "v2",
                    "experiment_id": experiment_id,
                    "judge_backend": backend_name,
                    "judge_model": model_name,
                    "scores": [],
                    "status": "error",
                    "error": {
                        "type": type(exc).__name__,
                        "message": str(exc),
                    },
                }

            run_path.write_text(json.dumps(payload, indent=2))
            run_status = str(payload.get("status", "ok"))
            run_status_counts[run_status] += 1
            run_results.append(
                {
                    "repeat": repeat,
                    "path": str(run_path),
                    "status": run_status,
                    "cached": False,
                }
            )

            run_entries = _score_entries_from_payload(payload, dimensions)
            for dimension, entries in run_entries.items():
                per_dimension[dimension].extend(entries)
                all_dimension_entries[dimension].extend(entries)
            error_payload = payload.get("error")
            if isinstance(error_payload, dict):
                run_errors.append({"repeat": repeat, **error_payload})

        dimension_summary: dict[str, object] = {}
        for dimension, entries in per_dimension.items():
            counter = Counter(entry["category"] for entry in entries)
            agreement = _pairwise_agreement(entries)
            dimension_summary[dimension] = {
                "runs": entries,
                "completed_runs": len(entries),
                "category_counts": dict(counter),
                "majority_category": counter.most_common(1)[0][0] if counter else None,
                "agreement": agreement.to_dict(),
            }

        summary["experiments"][experiment_id] = {
            "context": experiment_context,
            "runs": run_results,
            "run_status_counts": dict(run_status_counts),
            "errors": run_errors,
            "dimension_summary": dimension_summary,
        }

    overall: dict[str, object] = {}
    for dimension, entries in all_dimension_entries.items():
        counter = Counter(entry["category"] for entry in entries)
        overall[dimension] = {
            "category_counts": dict(counter),
            "agreement": _pairwise_agreement(entries).to_dict(),
        }
    summary["overall"] = overall

    (args.output_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    print(f"[repeatability] summary saved to {args.output_dir / 'summary.json'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
