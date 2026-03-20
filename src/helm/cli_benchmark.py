"""Benchmark-specific CLI helpers."""

from __future__ import annotations

import asyncio
import csv
import json
from pathlib import Path
from typing import Any

import typer

from helm.benchmarks import (
    build_orchestration_training_row,
    build_per_agent_training_records,
    build_training_record,
    normalize_orchestration_record,
)
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


def benchmark_report_impl(
    summaries: list[Path],
    output: Path | None = None,
    format: str = "markdown",
    experiments_dir: Path | None = None,
) -> None:
    if not summaries:
        typer.echo("Error: provide at least one summary.", err=True)
        raise typer.Exit(1)

    configured_judge_dimensions: list[str] = []
    rows: list[dict[str, object]] = []
    for summary in summaries:
        with open(summary) as f:
            payload = json.load(f)

        results = payload.get("results", [])
        if not isinstance(results, list) or not results:
            typer.echo(f"Error: summary contains no results: {summary}", err=True)
            raise typer.Exit(1)

        benchmark_info = payload.get("benchmark", {})
        if isinstance(benchmark_info, dict):
            dims = benchmark_info.get("judge_dimensions", [])
            if isinstance(dims, list):
                configured_judge_dimensions = merge_dimensions(
                    [str(dim).strip() for dim in dims if str(dim).strip()],
                    configured_judge_dimensions,
                )

        judge_dimensions = merge_dimensions(
            configured_judge_dimensions,
            ACTIVE_BEHAVIORAL_DIMENSIONS,
        )
        experiments_root = experiments_dir or summary.parent.parent

        for result in results:
            if not isinstance(result, dict):
                continue
            experiment_id = result.get("experiment_id")
            if not isinstance(experiment_id, str):
                continue

            run_data_path = experiments_root / experiment_id / "run_data.json"
            run_data = {}
            if run_data_path.exists():
                with open(run_data_path) as f:
                    loaded = json.load(f)
                if isinstance(loaded, dict):
                    run_data = loaded

            orchestration = run_data.get("evals", {}).get("orchestration", {})
            parallel = orchestration.get("parallelism_efficiency", {}).get("value")
            coord_ratio = orchestration.get("coordination_overhead", {}).get(
                "coordination_to_output_ratio"
            )
            task_verification = run_data.get("run", {}).get("task_verification", {})
            judge_categories = load_dimension_categories(
                run_data,
                result.get("judge_scores") if isinstance(result, dict) else None,
            )
            pattern = run_data.get("experiment", {}).get("pattern")
            if not isinstance(pattern, str):
                pattern = result.get("pattern")
            matrix = run_data.get("experiment", {}).get("matrix")
            if not isinstance(matrix, dict):
                candidate_matrix = result.get("matrix")
                matrix = candidate_matrix if isinstance(candidate_matrix, dict) else None

            row: dict[str, object] = {
                "example_id": result.get("example_id"),
                "experiment_id": experiment_id,
                "pattern": pattern,
                "matrix": matrix,
                "summary_source": str(summary),
                "run_success": result.get("success"),
                "run_outcome": result.get("outcome"),
                "termination_reason": result.get("termination_reason"),
                "system_failure": result.get("system_failure"),
                "duration_seconds": result.get("duration_seconds"),
                "task_verification_status": (
                    task_verification.get("status")
                    if isinstance(task_verification, dict)
                    else result.get("task_verification_status")
                ),
                "task_verification_score": (
                    task_verification.get("score")
                    if isinstance(task_verification, dict)
                    else result.get("task_verification_score")
                ),
                "parallelism_efficiency": parallel,
                "coordination_to_output_ratio": coord_ratio,
                "behavior_profile": compact_behavior_profile(
                    judge_categories,
                    judge_dimensions,
                ),
            }
            row.update(flatten_matrix_fields(matrix))
            for dim in judge_dimensions:
                row[dim] = judge_categories.get(dim)
            rows.append(row)

    judge_dimensions = merge_dimensions(
        configured_judge_dimensions,
        ACTIVE_BEHAVIORAL_DIMENSIONS,
    )

    def avg(values: list[float | int | None]) -> float | None:
        filtered = [float(v) for v in values if isinstance(v, (int, float))]
        if not filtered:
            return None
        return sum(filtered) / len(filtered)

    completed = len(rows)
    succeeded = sum(1 for row in rows if row.get("run_success") is True)
    verified_pass = sum(
        1 for row in rows if row.get("task_verification_status") == "pass"
    )
    avg_task_score = avg(
        [row.get("task_verification_score") for row in rows]  # type: ignore[list-item]
    )
    avg_parallel = avg(
        [row.get("parallelism_efficiency") for row in rows]  # type: ignore[list-item]
    )
    avg_coord_ratio = avg(
        [row.get("coordination_to_output_ratio") for row in rows]  # type: ignore[list-item]
    )

    format = format.strip().lower()
    if format not in {"markdown", "csv"}:
        typer.echo("Error: --format must be 'markdown' or 'csv'.", err=True)
        raise typer.Exit(1)

    if format == "csv":
        if output is not None:
            out_path = output
        elif len(summaries) == 1:
            out_path = summaries[0].with_suffix(".report.csv")
        else:
            out_path = summaries[0].parent / "benchmark-compare.report.csv"
        fieldnames = [
            "example_id",
            "experiment_id",
            "pattern",
            *MATRIX_FIELD_NAMES,
            "summary_source",
            "run_success",
            "run_outcome",
            "termination_reason",
            "system_failure",
            "task_verification_status",
            "task_verification_score",
            "parallelism_efficiency",
            "coordination_to_output_ratio",
            "behavior_profile",
            "duration_seconds",
        ]
        fieldnames.extend(judge_dimensions)
        with open(out_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                writer.writerow(row)
        typer.echo(f"Report written to: {out_path}")
        return

    lines = [
        "# Benchmark Report",
        "",
        (
            f"- Summary source: `{summaries[0]}`"
            if len(summaries) == 1
            else f"- Summary sources: {len(summaries)}"
        ),
        f"- Completed runs: {completed}",
        f"- Run success rate: {(succeeded / completed * 100):.1f}%",
        f"- Verification pass rate: {(verified_pass / completed * 100):.1f}%",
        f"- Average task score: {avg_task_score:.3f}" if avg_task_score is not None else "- Average task score: n/a",
        f"- Average parallelism efficiency: {avg_parallel:.3f}" if avg_parallel is not None else "- Average parallelism efficiency: n/a",
        f"- Average coordination-to-output ratio: {avg_coord_ratio:.3f}" if avg_coord_ratio is not None else "- Average coordination-to-output ratio: n/a",
        "- Behavioral profile legend: "
        + ", ".join(
            f"{DIMENSION_SHORT_LABELS.get(dim, dim)}={dim}" for dim in judge_dimensions
        ),
        "",
        "| example_id | pattern | experiment_id | run_success | run_outcome | reason | verify_status | verify_score | behavior_profile | parallelism | coord_to_output | duration_s |",
        "|---|---|---|---:|---|---|---|---:|---|---:|---:|---:|",
    ]
    for row in rows:
        verify_score = row.get("task_verification_score")
        verify_score_text = (
            f"{float(verify_score):.3f}"
            if isinstance(verify_score, (int, float))
            else "n/a"
        )
        parallel = row.get("parallelism_efficiency")
        parallel_text = (
            f"{float(parallel):.3f}" if isinstance(parallel, (int, float)) else "n/a"
        )
        coord_ratio = row.get("coordination_to_output_ratio")
        coord_ratio_text = (
            f"{float(coord_ratio):.3f}"
            if isinstance(coord_ratio, (int, float))
            else "n/a"
        )
        duration = row.get("duration_seconds")
        duration_text = (
            f"{float(duration):.1f}" if isinstance(duration, (int, float)) else "n/a"
        )
        lines.append(
            "| "
            + f"{row.get('example_id', 'n/a')} | "
            + f"{row.get('pattern', 'n/a')} | "
            + f"{row.get('experiment_id', 'n/a')} | "
            + f"{row.get('run_success', 'n/a')} | "
            + f"{row.get('run_outcome', 'n/a')} | "
            + f"{row.get('termination_reason', 'n/a')} | "
            + f"{row.get('task_verification_status', 'n/a')} | "
            + f"{verify_score_text} | "
            + f"{row.get('behavior_profile', 'n/a')} | "
            + f"{parallel_text} | "
            + f"{coord_ratio_text} | "
            + f"{duration_text} |"
        )

    behavior_diff_groups: list[tuple[tuple[str, str], list[dict[str, object]]]] = []
    grouped: dict[tuple[str, str], list[dict[str, object]]] = {}
    for row in rows:
        example_id = row.get("example_id")
        verify_score = row.get("task_verification_score")
        if not isinstance(example_id, str) or not isinstance(verify_score, (int, float)):
            continue
        key = (example_id, f"{float(verify_score):.3f}")
        grouped.setdefault(key, []).append(row)

    for key, group_rows in grouped.items():
        if len(group_rows) < 2:
            continue
        signatures = {
            (
                row.get("run_outcome"),
                row.get("termination_reason"),
                tuple(row.get(dim) for dim in judge_dimensions),
            )
            for row in group_rows
        }
        if len(signatures) > 1:
            behavior_diff_groups.append((key, group_rows))

    if behavior_diff_groups:
        lines.extend(["", "## Benchmark-Equal Behavioral Differences", ""])
        for (example_id, verify_score), group_rows in behavior_diff_groups:
            lines.append(f"- `{example_id}` at benchmark score `{verify_score}`:")
            for row in group_rows:
                profile = compact_behavior_profile(
                    {
                        dim: str(row.get(dim))
                        for dim in judge_dimensions
                        if isinstance(row.get(dim), str)
                    },
                    judge_dimensions,
                )
                lines.append(
                    "  - "
                    + f"`{row.get('pattern', 'unknown')}` / `{row.get('experiment_id', '')}` "
                    + f"→ outcome `{row.get('run_outcome', '')}` "
                    + f"({row.get('termination_reason', '')}), profile `{profile}`"
                )

    report_text = "\n".join(lines)
    if output:
        with open(output, "w") as f:
            f.write(report_text)
        typer.echo(f"Report written to: {output}")
    else:
        typer.echo(report_text)


def benchmark_export_impl(
    summary: Path,
    output: Path | None = None,
    experiments_dir: Path | None = None,
    include_failures: bool = True,
    min_reward: float | None = None,
    per_agent: bool = False,
) -> None:
    with open(summary) as f:
        payload = json.load(f)

    results = payload.get("results", [])
    if not isinstance(results, list) or not results:
        typer.echo("Error: summary contains no results.", err=True)
        raise typer.Exit(1)

    experiments_root = experiments_dir or summary.parent.parent
    out_path = output or summary.with_suffix(".train.jsonl")

    exported = 0
    skipped = 0

    with open(out_path, "w") as out_f:
        for result in results:
            if not isinstance(result, dict):
                skipped += 1
                continue
            if not include_failures and result.get("success") is not True:
                skipped += 1
                continue

            experiment_id = result.get("experiment_id")
            if not isinstance(experiment_id, str):
                skipped += 1
                continue

            run_dir = experiments_root / experiment_id
            run_data_path = run_dir / "run_data.json"
            transcript_path = run_dir / "transcripts" / "full.json"
            if not run_data_path.exists() or not transcript_path.exists():
                skipped += 1
                continue

            with open(run_data_path) as f:
                run_data = json.load(f)
            with open(transcript_path) as f:
                transcript = json.load(f)

            if not isinstance(run_data, dict) or not isinstance(transcript, dict):
                skipped += 1
                continue

            if per_agent:
                records = build_per_agent_training_records(run_data, transcript)
                if not records:
                    skipped += 1
                    continue
                for record in records:
                    reward = record.get("reward")
                    if min_reward is not None:
                        if not isinstance(reward, (int, float)) or float(reward) < min_reward:
                            continue
                    out_f.write(json.dumps(record))
                    out_f.write("\n")
                    exported += 1
            else:
                record = build_training_record(run_data, transcript)
                reward = record.get("reward")
                if min_reward is not None:
                    if not isinstance(reward, (int, float)) or float(reward) < min_reward:
                        skipped += 1
                        continue

                out_f.write(json.dumps(record))
                out_f.write("\n")
                exported += 1

    mode_label = "per-agent" if per_agent else "per-experiment"
    typer.echo(f"Exported records: {exported} ({mode_label})")
    typer.echo(f"Skipped records: {skipped}")
    typer.echo(f"Output JSONL: {out_path}")


def benchmark_export_orchestration_impl(
    source: Path,
    output: Path | None = None,
    min_reward: float | None = None,
    max_records: int | None = None,
) -> None:
    out_path = output or source.with_name(f"{source.stem}.orchestration.jsonl")

    exported = 0
    skipped = 0
    parse_errors = 0

    with open(source) as in_f, open(out_path, "w") as out_f:
        for raw_line in in_f:
            if max_records is not None and exported >= max_records:
                break

            line = raw_line.strip()
            if not line:
                continue

            try:
                loaded = json.loads(line)
            except json.JSONDecodeError:
                parse_errors += 1
                skipped += 1
                continue

            if not isinstance(loaded, dict):
                skipped += 1
                continue

            reward = loaded.get("reward")
            if min_reward is not None:
                if not isinstance(reward, (int, float)) or float(reward) < min_reward:
                    skipped += 1
                    continue

            try:
                row = normalize_orchestration_record(loaded)
            except ValueError:
                row = build_orchestration_training_row(loaded)

            out_f.write(json.dumps(row))
            out_f.write("\n")
            exported += 1

    typer.echo(f"Exported orchestration rows: {exported}")
    typer.echo(f"Skipped rows: {skipped}")
    if parse_errors:
        typer.echo(f"JSON parse errors: {parse_errors}")
    typer.echo(f"Output JSONL: {out_path}")
