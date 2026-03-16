#!/usr/bin/env python3
"""Compare Helm judge strategies on a fixed panel of saved experiments."""

from __future__ import annotations

import argparse
import asyncio
import json
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from helm.judge import ExperimentScores, OpenRouterJudge, SDKJudge, judge_experiment

DEFAULT_DIMENSIONS = [
    "escalation-calibration",
    "goal-drift",
    "failure-suppression",
    "context-degradation",
    "resource-waste",
]


@dataclass
class StrategyOutcome:
    strategy: str
    score_path: str
    categories: dict[str, str]
    severities: dict[str, str]
    input_view_type: str | None
    input_preparation: dict[str, Any] | None
    artifacts: dict[str, Any] | None


def _parse_args() -> argparse.Namespace:
    repo_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "experiment_ids",
        nargs="+",
        help="Experiment directory names under experiments/",
    )
    parser.add_argument(
        "--strategies",
        default="hierarchical,single",
        help="Comma-separated judge strategies to compare (default: hierarchical,single)",
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
        help="Per-run timeout for SDK backend (default: 180)",
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
        help="Directory to store comparison artifacts",
    )
    return parser.parse_args()


async def _build_backend(args: argparse.Namespace):
    if args.backend == "sdk":
        return SDKJudge(timeout_seconds=args.timeout_seconds), "sdk", None
    model = args.model or "google/gemini-2.0-flash-001"
    return OpenRouterJudge(model=model), "openrouter", model


def _load_experiment_context(experiment_dir: Path) -> dict[str, Any]:
    metadata_path = experiment_dir / "metadata.json"
    payload: dict[str, Any] = {}
    if metadata_path.exists():
        payload = json.loads(metadata_path.read_text())
    run = payload.get("run", {})
    if not isinstance(run, dict):
        run = {}

    verification_path = experiment_dir / "evaluation" / "task_verification.json"
    verification: dict[str, Any] | None = None
    if verification_path.exists():
        loaded = json.loads(verification_path.read_text())
        if isinstance(loaded, dict):
            verification = loaded

    return {
        "experiment_name": payload.get("experiment_name"),
        "pattern": payload.get("pattern"),
        "task": payload.get("task"),
        "outcome": run.get("outcome"),
        "termination_reason": run.get("termination_reason"),
        "system_failure": run.get("system_failure"),
        "verification": verification,
    }


def _to_strategy_outcome(scores: ExperimentScores, score_path: Path) -> StrategyOutcome:
    categories = {score.dimension: score.category for score in scores.scores}
    severities = {score.dimension: score.severity for score in scores.scores}
    return StrategyOutcome(
        strategy=scores.strategy,
        score_path=str(score_path),
        categories=categories,
        severities=severities,
        input_view_type=scores.input_view_type,
        input_preparation=scores.input_preparation,
        artifacts=scores.artifacts,
    )


def _render_manual_review_template(
    experiment_id: str,
    dimensions: list[str],
    context: dict[str, Any],
) -> str:
    lines = [
        f"# Manual Review Template: {experiment_id}",
        "",
        "Use this as the adjudicated reference for digest/single vs hierarchical comparison.",
        "",
        "## Run Context",
        "",
        f"- Pattern: `{context.get('pattern')}`",
        f"- Outcome: `{context.get('outcome')}`",
        f"- Termination reason: `{context.get('termination_reason')}`",
        f"- System failure: `{context.get('system_failure')}`",
        "",
    ]

    verification = context.get("verification")
    if isinstance(verification, dict):
        lines.extend(
            [
                "## Verification",
                "",
                f"- Status: `{verification.get('status')}`",
                f"- Score: `{verification.get('score')}`",
                f"- Reason: {verification.get('reason')}",
                "",
            ]
        )

    lines.extend(["## Dimensions", ""])
    for dimension in dimensions:
        lines.extend(
            [
                f"### {dimension}",
                "- Final category: ",
                "- Needs deeper adjudication: no",
                "- Evidence notes:",
                "  - ",
                "",
            ]
        )
    return "\n".join(lines).strip() + "\n"


def _render_report(
    *,
    experiment_summaries: dict[str, dict[str, Any]],
    strategies: list[str],
    dimensions: list[str],
) -> str:
    lines = [
        "# Judge Strategy Comparison",
        "",
        f"Strategies compared: {', '.join(f'`{strategy}`' for strategy in strategies)}",
        "",
    ]

    for experiment_id, payload in experiment_summaries.items():
        context = payload["context"]
        outcomes = payload["outcomes"]
        lines.extend(
            [
                f"## {experiment_id}",
                "",
                f"- Pattern: `{context.get('pattern')}`",
                f"- Outcome: `{context.get('outcome')}` / `{context.get('termination_reason')}`",
                "",
                "| Dimension | " + " | ".join(strat for strat in strategies) + " |",
                "|---|" + "|".join("---" for _ in strategies) + "|",
            ]
        )
        differing = 0
        for dimension in dimensions:
            row = [dimension]
            categories = []
            for strategy in strategies:
                outcome = outcomes.get(strategy)
                if not isinstance(outcome, dict):
                    categories.append("pending")
                    row.append("`pending`")
                    continue
                category = outcome["categories"].get(dimension, "n/a")
                severity = outcome["severities"].get(dimension)
                categories.append(category)
                if severity:
                    row.append(f"`{category}` [{severity}]")
                else:
                    row.append(f"`{category}`")
            comparable_categories = [category for category in categories if category != "pending"]
            if len(set(comparable_categories)) > 1:
                differing += 1
            lines.append("| " + " | ".join(row) + " |")

        lines.extend(
            [
                "",
                f"- Dimensions with cross-strategy disagreement: `{differing}`",
                f"- Manual review scaffold: `{payload['manual_review_template']}`",
                "",
            ]
        )

    return "\n".join(lines).strip() + "\n"


async def main() -> int:
    args = _parse_args()
    dimensions = [d.strip() for d in args.dimensions.split(",") if d.strip()]
    strategies = [s.strip() for s in args.strategies.split(",") if s.strip()]
    backend, backend_name, model_name = await _build_backend(args)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    scores_root = args.output_dir / "scores"
    scores_root.mkdir(parents=True, exist_ok=True)

    summary: dict[str, dict[str, Any]] = {}
    summary_path = args.output_dir / "summary.json"
    if summary_path.exists():
        loaded = json.loads(summary_path.read_text())
        experiments = loaded.get("experiments", {})
        if isinstance(experiments, dict):
            summary = experiments

    def write_outputs() -> None:
        payload = {
            "backend": backend_name,
            "model": model_name,
            "dimensions": dimensions,
            "strategies": strategies,
            "experiments": summary,
        }
        summary_path.write_text(json.dumps(payload, indent=2))
        (args.output_dir / "report.md").write_text(
            _render_report(
                experiment_summaries=summary,
                strategies=strategies,
                dimensions=dimensions,
            )
        )

    for experiment_id in args.experiment_ids:
        experiment_dir = args.experiments_dir / experiment_id
        if not experiment_dir.exists():
            raise FileNotFoundError(f"Experiment not found: {experiment_dir}")

        print(f"[compare] {experiment_id}", flush=True)
        experiment_output_dir = scores_root / experiment_id
        experiment_output_dir.mkdir(parents=True, exist_ok=True)
        context = _load_experiment_context(experiment_dir)
        existing = summary.get(experiment_id, {})
        outcomes: dict[str, Any] = {}
        if isinstance(existing.get("outcomes"), dict):
            outcomes.update(existing["outcomes"])

        for strategy in strategies:
            if strategy in outcomes:
                print(f"  - strategy={strategy} (cached)", flush=True)
                continue
            print(f"  - strategy={strategy}", flush=True)
            scores = await judge_experiment(
                experiment_dir=experiment_dir,
                dimensions=dimensions,
                judges_dir=args.judges_dir,
                backend=backend,
                backend_name=backend_name,
                model_name=model_name,
                strategy=strategy,
            )
            score_path = experiment_output_dir / f"{strategy}.json"
            score_path.write_text(json.dumps(scores.to_dict(), indent=2))
            outcomes[strategy] = asdict(_to_strategy_outcome(scores, score_path))
            summary[experiment_id] = {
                "context": context,
                "outcomes": outcomes,
                "manual_review_template": str(
                    (args.output_dir / experiment_id / "manual-review.md").relative_to(args.output_dir)
                ),
            }
            write_outputs()

        manual_review_path = args.output_dir / experiment_id / "manual-review.md"
        manual_review_path.parent.mkdir(parents=True, exist_ok=True)
        manual_review_path.write_text(
            _render_manual_review_template(
                experiment_id=experiment_id,
                dimensions=dimensions,
                context=context,
            )
        )

        summary[experiment_id] = {
            "context": context,
            "outcomes": outcomes,
            "manual_review_template": str(manual_review_path.relative_to(args.output_dir)),
        }
        write_outputs()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
