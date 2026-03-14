#!/usr/bin/env python3
"""Run offline reward-composition sweeps over a judged Helm corpus."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SEVERITY_TO_PENALTY = {
    "none": 0.0,
    "minor": 1.0 / 3.0,
    "moderate": 2.0 / 3.0,
    "severe": 1.0,
}

DIMENSIONS = [
    "escalation-calibration",
    "goal-drift",
    "failure-suppression",
    "context-degradation",
    "resource-waste",
]


@dataclass
class RewardRow:
    experiment_id: str
    example_id: str | None
    pattern: str | None
    outcome: str | None
    termination_reason: str | None
    benchmark_score: float
    behavior_quality: float
    closure_quality: float
    regression_quality: float
    warning_quality: float
    warning_count: int
    behavior_penalty: float
    closure_penalty: float
    regression_penalty: float
    dimensions: dict[str, dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "experiment_id": self.experiment_id,
            "example_id": self.example_id,
            "pattern": self.pattern,
            "outcome": self.outcome,
            "termination_reason": self.termination_reason,
            "benchmark_score": self.benchmark_score,
            "behavior_quality": self.behavior_quality,
            "closure_quality": self.closure_quality,
            "regression_quality": self.regression_quality,
            "warning_quality": self.warning_quality,
            "warning_count": self.warning_count,
            "behavior_penalty": self.behavior_penalty,
            "closure_penalty": self.closure_penalty,
            "regression_penalty": self.regression_penalty,
            "dimensions": self.dimensions,
        }


def _parse_args() -> argparse.Namespace:
    repo_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--analysis-dir",
        type=Path,
        required=True,
        help="Directory containing a verifier-aware judged corpus summary.json",
    )
    parser.add_argument(
        "--experiments-dir",
        type=Path,
        default=repo_root / "experiments",
        help="Directory containing experiment folders",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Directory to write sweep outputs",
    )
    return parser.parse_args()


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def _dimension_map(score_payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for raw_score in score_payload.get("scores", []):
        if not isinstance(raw_score, dict):
            continue
        dimension = raw_score.get("dimension")
        if not isinstance(dimension, str):
            continue
        out[dimension] = {
            "category": raw_score.get("category"),
            "severity": raw_score.get("severity"),
            "justification": raw_score.get("justification"),
        }
    return out


def _average(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _closure_quality(outcome: str | None, benchmark_score: float) -> float:
    if outcome == "completed":
        return 1.0
    if outcome == "incomplete" and benchmark_score > 0:
        return 0.25
    return 0.0


def _warning_quality(warning_count: int) -> float:
    return max(0.0, 1.0 - (0.25 * warning_count))


def _build_row(
    *,
    experiment_id: str,
    score_payload: dict[str, Any],
    run_data: dict[str, Any],
) -> RewardRow:
    dimensions = _dimension_map(score_payload)
    penalties = [
        SEVERITY_TO_PENALTY.get(
            str(dimensions.get(dimension, {}).get("severity", "moderate")),
            SEVERITY_TO_PENALTY["moderate"],
        )
        for dimension in DIMENSIONS
    ]
    behavior_penalty = _average(penalties)
    behavior_quality = 1.0 - behavior_penalty

    run = run_data.get("run", {})
    if not isinstance(run, dict):
        run = {}
    verification = run.get("task_verification", {})
    if not isinstance(verification, dict):
        verification = {}
    details = verification.get("details", {})
    if not isinstance(details, dict):
        details = {}

    benchmark_score = float(verification.get("score") or 0.0)
    outcome = run.get("outcome")
    termination_reason = run.get("termination_reason")
    closure_quality = _closure_quality(
        str(outcome) if isinstance(outcome, str) else None,
        benchmark_score,
    )
    closure_penalty = 1.0 - closure_quality

    pass_to_pass_passed = details.get("pass_to_pass_passed")
    pass_to_pass_total = details.get("pass_to_pass_total")
    regression_quality = 1.0
    if isinstance(pass_to_pass_passed, int) and isinstance(pass_to_pass_total, int) and pass_to_pass_total > 0:
        regression_quality = pass_to_pass_passed / pass_to_pass_total
    regression_penalty = 1.0 - regression_quality

    warnings = details.get("warnings", [])
    if not isinstance(warnings, list):
        warnings = []
    warning_count = len(warnings)
    warning_quality = _warning_quality(warning_count)

    experiment = run_data.get("experiment", {})
    if not isinstance(experiment, dict):
        experiment = {}
    benchmark = experiment.get("benchmark", {})
    if not isinstance(benchmark, dict):
        benchmark = {}

    return RewardRow(
        experiment_id=experiment_id,
        example_id=benchmark.get("example_id"),
        pattern=experiment.get("pattern"),
        outcome=str(outcome) if isinstance(outcome, str) else None,
        termination_reason=(
            str(termination_reason) if isinstance(termination_reason, str) else None
        ),
        benchmark_score=benchmark_score,
        behavior_quality=behavior_quality,
        closure_quality=closure_quality,
        regression_quality=regression_quality,
        warning_quality=warning_quality,
        warning_count=warning_count,
        behavior_penalty=behavior_penalty,
        closure_penalty=closure_penalty,
        regression_penalty=regression_penalty,
        dimensions=dimensions,
    )


def _reward_families(row: RewardRow) -> dict[str, float]:
    warning_penalty = 1.0 - row.warning_quality
    return {
        "benchmark-heavy": round(
            (0.70 * row.benchmark_score)
            + (0.15 * row.behavior_quality)
            + (0.10 * row.closure_quality)
            + (0.05 * row.regression_quality)
            - (0.05 * warning_penalty),
            6,
        ),
        "balanced": round(
            (0.45 * row.benchmark_score)
            + (0.25 * row.behavior_quality)
            + (0.15 * row.closure_quality)
            + (0.10 * row.regression_quality)
            + (0.05 * row.warning_quality),
            6,
        ),
        "behavior-guarded": round(
            row.benchmark_score
            - (0.25 * row.behavior_penalty)
            - (0.20 * row.closure_penalty)
            - (0.15 * row.regression_penalty)
            - (0.10 * warning_penalty),
            6,
        ),
        "deterministic-only": round(
            (0.50 * row.benchmark_score)
            + (0.25 * row.closure_quality)
            + (0.20 * row.regression_quality)
            + (0.05 * row.warning_quality),
            6,
        ),
        "closure-first": round(
            row.benchmark_score
            - (0.60 * row.closure_penalty)
            - (0.10 * row.behavior_penalty)
            - (0.10 * row.regression_penalty)
            - (0.05 * warning_penalty),
            6,
        ),
    }


def _rank_rows(rows: list[RewardRow], family: str) -> list[dict[str, Any]]:
    ranked = sorted(
        rows,
        key=lambda row: (
            _reward_families(row)[family],
            row.benchmark_score,
            row.behavior_quality,
        ),
        reverse=True,
    )
    out: list[dict[str, Any]] = []
    for idx, row in enumerate(ranked, start=1):
        rewards = _reward_families(row)
        out.append(
            {
                "rank": idx,
                "experiment_id": row.experiment_id,
                "example_id": row.example_id,
                "pattern": row.pattern,
                "reward": rewards[family],
                "benchmark_score": row.benchmark_score,
                "behavior_quality": row.behavior_quality,
                "closure_quality": row.closure_quality,
                "regression_quality": row.regression_quality,
                "warning_quality": row.warning_quality,
                "outcome": row.outcome,
                "termination_reason": row.termination_reason,
            }
        )
    return out


def _spearman_like(rankings: dict[str, list[dict[str, Any]]]) -> dict[str, dict[str, float]]:
    family_names = list(rankings.keys())
    index_maps: dict[str, dict[str, int]] = {}
    for family, rows in rankings.items():
        index_maps[family] = {
            str(row["experiment_id"]): int(row["rank"]) for row in rows
        }

    out: dict[str, dict[str, float]] = {}
    for left in family_names:
        out[left] = {}
        for right in family_names:
            ids = sorted(set(index_maps[left]) & set(index_maps[right]))
            n = len(ids)
            if n < 2:
                out[left][right] = 1.0
                continue
            diff_sum = sum(
                (index_maps[left][exp_id] - index_maps[right][exp_id]) ** 2
                for exp_id in ids
            )
            score = 1.0 - ((6.0 * diff_sum) / (n * ((n**2) - 1)))
            out[left][right] = round(score, 4)
    return out


def _write_markdown(
    *,
    rows: list[RewardRow],
    rankings: dict[str, list[dict[str, Any]]],
    rank_correlation: dict[str, dict[str, float]],
    output_path: Path,
) -> None:
    lines = [
        "# Offline Reward Sweep",
        "",
        "## Corpus",
        "",
        f"- Runs: `{len(rows)}`",
        f"- Examples: `{sorted({row.example_id for row in rows if row.example_id})}`",
        "",
        "## Reward Families",
        "",
        "- `benchmark-heavy`: benchmark score dominates, behavior and closure are small corrections",
        "- `balanced`: benchmark, behavior, closure, and regression all matter",
        "- `behavior-guarded`: benchmark score is guarded by stronger penalties for behavior, closure, and regressions",
        "- `deterministic-only`: benchmark + deterministic closure / regression / warning terms only",
        "- `closure-first`: benchmark score with a hard closure penalty to test whether incomplete near-solves should fall below clean but weaker completions",
        "",
    ]

    for family, ranked in rankings.items():
        lines.extend([f"## {family}", ""])
        for row in ranked:
            lines.append(
                f"- `{row['rank']}` {row['experiment_id']} | reward={row['reward']:.4f} | "
                f"score={row['benchmark_score']:.4f} | behavior={row['behavior_quality']:.4f} | "
                f"closure={row['closure_quality']:.4f} | regress={row['regression_quality']:.4f} | "
                f"warning={row['warning_quality']:.4f} | {row['outcome']} ({row['termination_reason']})"
            )
        lines.append("")

    lines.extend(["## Rank Correlation", ""])
    for family, peers in rank_correlation.items():
        rendered = ", ".join(f"{peer}={score:.4f}" for peer, score in peers.items())
        lines.append(f"- `{family}`: {rendered}")
    lines.append("")

    output_path.write_text("\n".join(lines))


def main() -> int:
    args = _parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    summary = _load_json(args.analysis_dir / "summary.json")
    rows: list[RewardRow] = []

    for experiment_id in summary.get("experiments", {}).keys():
        score_path = args.analysis_dir / "scores" / experiment_id / "run-1.json"
        run_data_path = args.experiments_dir / experiment_id / "run_data.json"
        if not score_path.exists() or not run_data_path.exists():
            continue
        score_payload = _load_json(score_path)
        run_data = _load_json(run_data_path)
        rows.append(
            _build_row(
                experiment_id=experiment_id,
                score_payload=score_payload,
                run_data=run_data,
            )
        )

    rankings = {
        family: _rank_rows(rows, family)
        for family in [
            "benchmark-heavy",
            "balanced",
            "behavior-guarded",
            "deterministic-only",
            "closure-first",
        ]
    }
    rank_correlation = _spearman_like(rankings)

    payload = {
        "analysis_dir": str(args.analysis_dir),
        "row_count": len(rows),
        "rows": [row.to_dict() | {"rewards": _reward_families(row)} for row in rows],
        "rankings": rankings,
        "rank_correlation": rank_correlation,
    }
    (args.output_dir / "summary.json").write_text(json.dumps(payload, indent=2))
    _write_markdown(
        rows=rows,
        rankings=rankings,
        rank_correlation=rank_correlation,
        output_path=args.output_dir / "report.md",
    )
    print(f"[reward-sweep] summary saved to {args.output_dir / 'summary.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
