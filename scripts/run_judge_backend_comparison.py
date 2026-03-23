#!/usr/bin/env python3
"""Compare multiple judge backends on a fixed panel of saved experiments."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from helm.cli_benchmark import DEFAULT_OPENROUTER_JUDGE_MODEL, normalize_judge_backend_name
from helm.cli_shared import ACTIVE_BEHAVIORAL_DIMENSIONS
from helm.judge import (
    ClaudeHeadlessJudge,
    CodexHeadlessJudge,
    ExperimentScores,
    OpenRouterJudge,
    judge_experiment,
)


@dataclass
class BackendOutcome:
    backend: str
    role: str
    model: str | None
    score_path: str
    categories: dict[str, str]
    severities: dict[str, str]
    input_view_type: str | None
    preparation_path: str | None
    input_preparation: dict[str, Any] | None
    artifacts: dict[str, Any] | None


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "experiment_ids",
        nargs="+",
        help="Experiment directory names under experiments/",
    )
    parser.add_argument(
        "--dimensions",
        default=",".join(ACTIVE_BEHAVIORAL_DIMENSIONS),
        help="Comma-separated dimensions to judge",
    )
    parser.add_argument(
        "--primary-backend",
        default="claude-headless",
        choices=("claude-headless", "codex-headless", "openrouter", "sdk"),
        help="Primary judge backend",
    )
    parser.add_argument(
        "--fallback-backend",
        default=None,
        choices=("claude-headless", "codex-headless", "openrouter", "sdk"),
        help="Optional fallback judge backend to compare",
    )
    parser.add_argument(
        "--audit-backends",
        default="",
        help="Comma-separated audit backends to compare",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=180.0,
        help="Per-run timeout budget for headless judge backends (default: 180s)",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Optional shared model override for the selected backend(s)",
    )
    parser.add_argument(
        "--experiments-dir",
        type=Path,
        default=REPO_ROOT / "experiments",
        help="Directory containing experiment folders",
    )
    parser.add_argument(
        "--judges-dir",
        type=Path,
        default=REPO_ROOT / "judges",
        help="Directory containing judge rubrics",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Directory to store comparison artifacts",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Recompute score files even when the output already exists",
    )
    return parser.parse_args()


def _ordered_backend_specs(args: argparse.Namespace) -> list[tuple[str, str]]:
    ordered: list[tuple[str, str]] = []
    seen: set[str] = set()

    def _add(role: str, backend: str | None) -> None:
        if not backend:
            return
        normalized = normalize_judge_backend_name(backend)
        if normalized in seen:
            return
        ordered.append((role, normalized))
        seen.add(normalized)

    _add("primary", args.primary_backend)
    _add("fallback", args.fallback_backend)
    for backend in (item.strip() for item in args.audit_backends.split(",")):
        if backend:
            _add("audit", backend)
    return ordered


def _build_backend(backend_name: str, *, model: str | None, timeout_seconds: float):
    if backend_name == "openrouter":
        return OpenRouterJudge(model=model or DEFAULT_OPENROUTER_JUDGE_MODEL), (
            model or DEFAULT_OPENROUTER_JUDGE_MODEL
        )
    if backend_name == "codex-headless":
        return CodexHeadlessJudge(model=model, timeout_seconds=timeout_seconds), model
    return ClaudeHeadlessJudge(model=model, timeout_seconds=timeout_seconds), model


def _load_experiment_context(experiment_dir: Path) -> dict[str, Any]:
    metadata_path = experiment_dir / "metadata.json"
    payload: dict[str, Any] = {}
    if metadata_path.exists():
        payload = json.loads(metadata_path.read_text())
    run = payload.get("run", {})
    if not isinstance(run, dict):
        run = {}
    return {
        "pattern": payload.get("pattern"),
        "task": payload.get("task"),
        "outcome": run.get("outcome"),
        "termination_reason": run.get("termination_reason"),
        "system_failure": run.get("system_failure"),
    }


def _to_backend_outcome(
    scores: ExperimentScores,
    score_path: Path,
    *,
    backend: str,
    role: str,
) -> BackendOutcome:
    return BackendOutcome(
        backend=backend,
        role=role,
        model=scores.judge_model,
        score_path=str(score_path),
        categories={score.dimension: score.category for score in scores.scores},
        severities={score.dimension: score.severity for score in scores.scores},
        input_view_type=scores.input_view_type,
        preparation_path=scores.preparation_path,
        input_preparation=scores.input_preparation,
        artifacts=scores.artifacts,
    )


def _load_existing_backend_outcome(score_path: Path, *, backend: str, role: str) -> BackendOutcome:
    payload = json.loads(score_path.read_text())
    scores = payload.get("scores", [])
    return BackendOutcome(
        backend=backend,
        role=role,
        model=payload.get("judge_model"),
        score_path=str(score_path),
        categories={
            item.get("dimension"): item.get("category")
            for item in scores
            if isinstance(item, dict) and item.get("dimension")
        },
        severities={
            item.get("dimension"): item.get("severity")
            for item in scores
            if isinstance(item, dict) and item.get("dimension")
        },
        input_view_type=payload.get("input_view_type"),
        preparation_path=payload.get("preparation_path"),
        input_preparation=payload.get("input_preparation"),
        artifacts=payload.get("artifacts"),
    )


def _render_report(
    *,
    outcomes: dict[str, dict[str, Any]],
    dimensions: list[str],
    specs: list[tuple[str, str]],
) -> str:
    labels = [f"{backend} ({role})" for role, backend in specs]
    lines = [
        "# Judge Backend Comparison",
        "",
        "Compared backends: " + ", ".join(f"`{label}`" for label in labels),
        "",
    ]

    for experiment_id, payload in outcomes.items():
        context = payload["context"]
        backend_outcomes = payload["outcomes"]
        lines.extend(
            [
                f"## {experiment_id}",
                "",
                f"- Pattern: `{context.get('pattern')}`",
                f"- Outcome: `{context.get('outcome')}` / `{context.get('termination_reason')}`",
                "",
                "| Dimension | " + " | ".join(labels) + " |",
                "|---|" + "|".join("---" for _ in labels) + "|",
            ]
        )
        for dimension in dimensions:
            row = [dimension]
            for role, backend in specs:
                key = f"{role}:{backend}"
                outcome = backend_outcomes.get(key)
                if not isinstance(outcome, dict):
                    row.append("`pending`")
                    continue
                category = outcome["categories"].get(dimension, "n/a")
                severity = outcome["severities"].get(dimension)
                row.append(f"`{category}` [{severity}]" if severity else f"`{category}`")
            lines.append("| " + " | ".join(row) + " |")
        lines.append("")

    return "\n".join(lines).strip() + "\n"


def _flush_outputs(
    *,
    output_dir: Path,
    summary: dict[str, Any],
    dimensions: list[str],
    specs: list[tuple[str, str]],
) -> None:
    summary_path = output_dir / "summary.json"
    report_path = output_dir / "report.md"
    summary_path.write_text(json.dumps(summary, indent=2))
    report_path.write_text(
        _render_report(
            outcomes=summary["experiments"],
            dimensions=dimensions,
            specs=specs,
        )
    )


async def main() -> int:
    args = _parse_args()
    dimensions = [item.strip() for item in args.dimensions.split(",") if item.strip()]
    specs = _ordered_backend_specs(args)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    scores_root = args.output_dir / "scores"
    scores_root.mkdir(parents=True, exist_ok=True)

    summary: dict[str, Any] = {
        "dimensions": dimensions,
        "backends": [{"role": role, "backend": backend} for role, backend in specs],
        "experiments": {},
    }

    for experiment_id in args.experiment_ids:
        experiment_dir = args.experiments_dir / experiment_id
        if not experiment_dir.exists():
            raise FileNotFoundError(f"Experiment not found: {experiment_dir}")

        experiment_scores_dir = scores_root / experiment_id
        experiment_scores_dir.mkdir(parents=True, exist_ok=True)
        context = _load_experiment_context(experiment_dir)
        experiment_summary = summary["experiments"].setdefault(
            experiment_id,
            {"context": context, "outcomes": {}},
        )

        for role, backend_name in specs:
            score_path = experiment_scores_dir / f"{role}-{backend_name}.json"
            if score_path.exists() and not args.overwrite:
                experiment_summary["outcomes"][f"{role}:{backend_name}"] = asdict(
                    _load_existing_backend_outcome(
                        score_path,
                        backend=backend_name,
                        role=role,
                    )
                )
                _flush_outputs(
                    output_dir=args.output_dir,
                    summary=summary,
                    dimensions=dimensions,
                    specs=specs,
                )
                print(
                    f"[judge-backend-comparison] reused {score_path}",
                    flush=True,
                )
                continue
            print(
                f"[judge-backend-comparison] starting {experiment_id} "
                f"with {backend_name} ({role})",
                flush=True,
            )
            backend, model_name = _build_backend(
                backend_name,
                model=args.model,
                timeout_seconds=args.timeout_seconds,
            )
            scores = await judge_experiment(
                experiment_dir=experiment_dir,
                dimensions=dimensions,
                judges_dir=args.judges_dir,
                backend=backend,
                backend_name=backend_name,
                model_name=model_name,
            )
            scores.judge_role = role
            scores.save(score_path)
            experiment_summary["outcomes"][f"{role}:{backend_name}"] = asdict(
                _to_backend_outcome(
                    scores,
                    score_path,
                    backend=backend_name,
                    role=role,
                )
            )
            _flush_outputs(
                output_dir=args.output_dir,
                summary=summary,
                dimensions=dimensions,
                specs=specs,
            )
            print(
                f"[judge-backend-comparison] saved {score_path}",
                flush=True,
            )

    summary_path = args.output_dir / "summary.json"
    report_path = args.output_dir / "report.md"
    print(f"[judge-backend-comparison] summary: {summary_path}")
    print(f"[judge-backend-comparison] report: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
