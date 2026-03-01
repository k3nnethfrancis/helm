"""CLI interface for Helm experiments.

Provides commands to run, monitor, and manage experiments.
"""

from __future__ import annotations

import asyncio
import csv
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Annotated

import typer

from helm.benchmarks import (
    available_adapters,
    build_orchestration_training_row,
    build_training_record,
    build_benchmark_run_plan,
    get_adapter,
    normalize_orchestration_record,
    verify_benchmark_run,
    write_task_verification,
)
from helm.config import ExperimentConfig
from helm.experiment import run_experiment, run_experiment_with_config
from helm.run_data import save_run_data
from helm.sdk import SDKEvent

app = typer.Typer(
    name="helm",
    help="Observation and evaluation framework for multi-agent AI systems",
    no_args_is_help=True,
)
benchmark_app = typer.Typer(help="Benchmark adapter utilities")
app.add_typer(benchmark_app, name="benchmark")

DEFAULT_JUDGE_DIMENSIONS = [
    "escalation-calibration",
    "goal-drift",
    "failure-suppression",
]


def _prime_config_field_not_set(output: str, field_name: str) -> bool:
    """Return True if `prime config view` reports a field as Not set."""
    for raw_line in output.splitlines():
        if field_name not in raw_line:
            continue

        # Rich table format: │ Field │ Value │
        if "│" in raw_line:
            parts = [part.strip() for part in raw_line.split("│") if part.strip()]
            if len(parts) >= 2 and parts[0] == field_name:
                return parts[1].lower() == "not set"

        # Plain text fallback: Field: Not set
        if re.search(
            rf"{re.escape(field_name)}\s*[:=]\s*Not set",
            raw_line,
            flags=re.IGNORECASE,
        ):
            return True

    return False


def prompt_turn_limit(agent_id: str, turns: int, limit: int) -> tuple[str, int | None]:
    """Interactive prompt when an agent hits its turn limit."""
    typer.echo(f"\n⚠ Agent '{agent_id}' reached turn limit ({turns}/{limit}).")
    typer.echo("  [C]ontinue indefinitely  [+N] Add N turns  [K]ill agent  [E]nd experiment")
    while True:
        try:
            choice = input("  > ").strip().lower()
        except EOFError:
            typer.echo("  (non-interactive mode, ending experiment)")
            return ("end_experiment", None)
        if choice == "c":
            return ("continue", None)
        elif choice.startswith("+") and choice[1:].isdigit():
            return ("extend", int(choice[1:]))
        elif choice == "k":
            return ("kill_agent", None)
        elif choice == "e":
            return ("end_experiment", None)
        else:
            typer.echo("  Invalid. Enter C, +N (e.g. +20), K, or E")


def static_turn_limit(action: str) -> callable:
    """Return a non-interactive turn-limit handler for the given action."""
    def handler(agent_id: str, turns: int, limit: int) -> tuple[str, int | None]:
        typer.echo(f"\n⚠ Agent '{agent_id}' reached turn limit ({turns}/{limit}) → {action}")
        return (action, None)
    return handler


def _resolve_turn_limit_handler(on_turn_limit: str | None) -> callable:
    """Resolve configured or interactive turn limit behavior."""
    valid_actions = {"continue", "kill", "end", "kill_agent", "end_experiment"}
    if on_turn_limit is not None:
        action = on_turn_limit.strip().lower()
        # Normalize short forms
        if action == "kill":
            action = "kill_agent"
        elif action == "end":
            action = "end_experiment"
        if action not in valid_actions:
            typer.echo(
                "Error: --on-turn-limit must be one of: continue, kill, end",
                err=True,
            )
            raise typer.Exit(1)
        return static_turn_limit(action)
    return prompt_turn_limit


def _print_run_result(result) -> None:
    """Print a consistent summary for a finished run result."""
    if result.success:
        typer.echo(f"✓ Experiment completed: {result.experiment_id}")
    else:
        typer.echo(f"✗ Experiment failed: {result.error}")

    typer.echo(f"  Duration: {(result.end_time - result.start_time).total_seconds():.1f}s")

    if result.agent_stats:
        typer.echo("  Agent stats:")
        for agent_id, stats in result.agent_stats.items():
            typer.echo(f"    {agent_id}: {stats['turns']} turns")

    if result.transcript_path and result.transcript_path.exists():
        typer.echo(f"  Transcript: {result.transcript_path}")


def notify_escalation(agent_id: str, event: SDKEvent, rule: object) -> None:
    """Notify user when a run escalates to human intervention."""
    reason = getattr(rule, "reason", None)
    if not reason:
        reason = event.data.get("prompt") or event.data.get("action") or event.type
    typer.echo(
        f"\n⚠ Escalation requested by '{agent_id}': {reason}",
        err=True,
    )


def get_default_paths() -> tuple[Path, Path]:
    """Get default paths for SDK binary and experiments directory."""
    # helm_dir is projects/helm/ - go up from src/helm/cli.py
    # __file__ = src/helm/cli.py -> parent = src/helm -> parent = src -> parent = helm/
    helm_dir = Path(__file__).parent.parent.parent
    sdk_binary = helm_dir / "bin" / "sandbox-agent"

    if not sdk_binary.exists():
        # Try current working directory
        cwd_binary = Path.cwd() / "bin" / "sandbox-agent"
        if cwd_binary.exists():
            sdk_binary = cwd_binary
        else:
            # Try npm global
            import shutil
            npm_binary = shutil.which("sandbox-agent")
            if npm_binary:
                sdk_binary = Path(npm_binary)

    experiments_dir = helm_dir / "experiments"
    if not experiments_dir.exists():
        experiments_dir = Path.cwd() / "experiments"

    return sdk_binary, experiments_dir


@app.command("readiness")
def readiness_check(
    summary: Annotated[
        Path | None,
        typer.Option(
            "--summary",
            help="Optional benchmark summary JSON to validate dataset readiness",
        ),
    ] = None,
) -> None:
    """Check whether Helm workspace is ready for Prime RL handoff."""
    checks: list[tuple[str, bool, str]] = []

    # Sandbox Agent SDK binary
    sdk_binary, experiments_dir = get_default_paths()
    checks.append(
        (
            "sandbox-agent",
            sdk_binary.exists(),
            str(sdk_binary),
        )
    )

    # Prime CLI presence
    prime_path = shutil.which("prime")
    checks.append(("prime_cli", prime_path is not None, prime_path or "not found"))

    # Prime auth/config status
    prime_ready = False
    prime_detail = "unavailable"
    if prime_path is not None:
        proc = subprocess.run(
            ["prime", "config", "view"],
            capture_output=True,
            text=True,
        )
        output = (proc.stdout or "") + (proc.stderr or "")
        api_not_set = _prime_config_field_not_set(output, "API Key")
        user_not_set = _prime_config_field_not_set(output, "User ID")
        prime_ready = proc.returncode == 0 and not api_not_set and not user_not_set
        if proc.returncode != 0:
            prime_detail = "prime config view failed"
        elif prime_ready:
            prime_detail = "API Key + User ID present"
        else:
            missing = []
            if api_not_set:
                missing.append("API Key")
            if user_not_set:
                missing.append("User ID")
            prime_detail = "missing: " + ", ".join(missing)
    checks.append(("prime_auth", prime_ready, prime_detail))

    # Optional benchmark summary checks
    if summary is not None:
        exists = summary.exists()
        checks.append(("summary_file", exists, str(summary)))
        if exists:
            with open(summary) as f:
                payload = json.load(f)
            results = payload.get("results", [])
            has_results = isinstance(results, list) and len(results) > 0
            checks.append(
                ("summary_results", has_results, f"count={len(results) if isinstance(results, list) else 0}")
            )
            if has_results:
                unknown_verification = 0
                missing_run_data = 0
                for item in results:
                    if not isinstance(item, dict):
                        continue
                    run_id = item.get("experiment_id")
                    if not isinstance(run_id, str):
                        continue
                    run_data_path = experiments_dir / run_id / "run_data.json"
                    if not run_data_path.exists():
                        missing_run_data += 1
                        continue
                    with open(run_data_path) as f:
                        run_data = json.load(f)
                    status = (
                        run_data.get("run", {})
                        .get("task_verification", {})
                        .get("status")
                    )
                    if status in (None, "unknown"):
                        unknown_verification += 1
                checks.append(
                    (
                        "task_verification",
                        unknown_verification == 0 and missing_run_data == 0,
                        f"unknown={unknown_verification}, missing_run_data={missing_run_data}",
                    )
                )

    typer.echo("Helm -> Prime RL readiness:")
    all_pass = True
    for name, ok, detail in checks:
        mark = "PASS" if ok else "FAIL"
        if not ok:
            all_pass = False
        typer.echo(f"  [{mark}] {name}: {detail}")

    if all_pass:
        typer.echo("Ready: all checks passed.")
    else:
        typer.echo("Not ready: fix FAIL checks before launching Prime RL.")
        raise typer.Exit(1)


@benchmark_app.command("preview")
def preview_benchmark_examples(
    pattern: Annotated[
        Path,
        typer.Argument(
            help="Path to experiment pattern YAML file",
            exists=True,
            dir_okay=False,
        ),
    ],
    limit: Annotated[
        int | None,
        typer.Option(
            "--limit", "-n",
            help="Maximum examples to preview",
        ),
    ] = 5,
) -> None:
    """Preview normalized benchmark examples for a pattern config."""
    config = ExperimentConfig.from_yaml(pattern)
    if config.benchmark is None:
        typer.echo("Error: pattern has no benchmark block configured.", err=True)
        raise typer.Exit(1)

    try:
        adapter = get_adapter(config.benchmark.adapter)
    except ValueError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)

    try:
        examples = adapter.load_examples(config.benchmark, limit=limit)
    except FileNotFoundError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)
    except ValueError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)
    if not examples:
        typer.echo("No benchmark examples found for this configuration.")
        return

    typer.echo(f"Adapter: {adapter.name}")
    typer.echo(f"Dataset: {config.benchmark.dataset_path}")
    typer.echo(f"Benchmark ID: {config.benchmark.benchmark_id or 'n/a'}")
    typer.echo(f"Split: {config.benchmark.split or 'n/a'}")
    typer.echo(f"Seed: {config.benchmark.seed if config.benchmark.seed is not None else 'n/a'}")
    typer.echo(f"Examples shown: {len(examples)}")
    typer.echo()

    for idx, example in enumerate(examples, start=1):
        prompt_preview = " ".join(example.prompt.split())
        if len(prompt_preview) > 120:
            prompt_preview = prompt_preview[:117] + "..."
        typer.echo(f"{idx}. {example.example_id}  {prompt_preview}")


@benchmark_app.command("adapters")
def list_benchmark_adapters() -> None:
    """List available benchmark adapters."""
    typer.echo("Available adapters:")
    for name in available_adapters():
        typer.echo(f"  - {name}")


@benchmark_app.command("run")
def run_benchmark_examples(
    pattern: Annotated[
        Path,
        typer.Argument(
            help="Path to benchmark-enabled pattern YAML file",
            exists=True,
            dir_okay=False,
        ),
    ],
    sample_size: Annotated[
        int | None,
        typer.Option(
            "--sample-size", "-n",
            help="Number of benchmark examples to run (sampling support)",
        ),
    ] = 5,
    seed: Annotated[
        int | None,
        typer.Option(
            "--seed",
            help="Override benchmark sampling seed",
        ),
    ] = None,
    stop_on_failure: Annotated[
        bool,
        typer.Option(
            "--stop-on-failure",
            help="Stop remaining benchmark runs when one example fails",
        ),
    ] = False,
    sdk_binary: Annotated[
        Path | None,
        typer.Option(
            "--sdk-binary",
            help="Path to sandbox-agent binary",
        ),
    ] = None,
    experiments_dir: Annotated[
        Path | None,
        typer.Option(
            "--experiments-dir",
            help="Directory to store experiment data",
        ),
    ] = None,
    on_turn_limit: Annotated[
        str | None,
        typer.Option(
            "--on-turn-limit",
            help="Action when agent hits turn limit: continue, kill, end (default: interactive prompt)",
        ),
    ] = None,
) -> None:
    """Run a sampled set of benchmark examples from a benchmark-enabled pattern."""
    default_sdk, default_experiments = get_default_paths()
    sdk_path = sdk_binary or default_sdk
    exp_dir = experiments_dir or default_experiments
    if not sdk_path.exists():
        typer.echo(f"Error: SDK binary not found at {sdk_path}", err=True)
        typer.echo("Install with: npm install -g sandbox-agent", err=True)
        raise typer.Exit(1)

    config = ExperimentConfig.from_yaml(pattern)
    if config.benchmark is None:
        typer.echo("Error: pattern has no benchmark block configured.", err=True)
        raise typer.Exit(1)

    if seed is not None:
        config.benchmark.seed = seed

    try:
        adapter = get_adapter(config.benchmark.adapter)
        examples = adapter.load_examples(config.benchmark, limit=sample_size)
    except (ValueError, FileNotFoundError) as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)

    if not examples:
        typer.echo("No benchmark examples found for this configuration.")
        return

    plan = build_benchmark_run_plan(config, examples)
    turn_limit_handler = _resolve_turn_limit_handler(on_turn_limit)

    typer.echo(f"Running benchmark sample from: {pattern}")
    typer.echo(f"Adapter: {adapter.name}")
    typer.echo(f"Benchmark ID: {config.benchmark.benchmark_id or 'n/a'}")
    typer.echo(f"Split: {config.benchmark.split or 'n/a'}")
    typer.echo(f"Seed: {config.benchmark.seed if config.benchmark.seed is not None else 'n/a'}")
    typer.echo(f"Examples: {len(plan)}")
    typer.echo()

    results_summary: list[dict[str, object]] = []

    for idx, entry in enumerate(plan, start=1):
        typer.echo(
            f"[{idx}/{len(plan)}] Running example {entry.example.example_id}"
        )
        try:
            result = asyncio.run(
                run_experiment_with_config(
                    config=entry.config,
                    task=entry.task,
                    sdk_binary_path=sdk_path,
                    experiments_dir=exp_dir,
                    on_escalate=notify_escalation,
                    on_turn_limit=turn_limit_handler,
                )
            )
        except KeyboardInterrupt:
            typer.echo("\nBenchmark run interrupted")
            raise typer.Exit(130)
        except Exception as e:
            typer.echo(f"Error: {e}", err=True)
            raise typer.Exit(1)

        _print_run_result(result)

        run_dir = exp_dir / result.experiment_id
        verification_status = None
        verification_score = None
        verification_reason = None
        verification_path = None
        if entry.config.benchmark is not None:
            verification = verify_benchmark_run(
                benchmark=entry.config.benchmark,
                example=entry.example,
                experiment_dir=run_dir,
                run_success=result.success,
                run_error=result.error,
            )
            verification_path = write_task_verification(run_dir, verification)
            save_run_data(run_dir)
            verification_status = verification.status
            verification_score = verification.score
            verification_reason = verification.reason
            score_display = (
                f"{verification.score:.2f}"
                if isinstance(verification.score, float)
                else "n/a"
            )
            typer.echo(
                f"  Task verification: {verification.status} (score={score_display})"
            )
            if verification.reason:
                typer.echo(f"  Verification note: {verification.reason}")
            typer.echo(f"  Verification artifact: {verification_path}")

        typer.echo()

        results_summary.append(
            {
                "example_id": entry.example.example_id,
                "experiment_id": result.experiment_id,
                "success": result.success,
                "error": result.error,
                "duration_seconds": (result.end_time - result.start_time).total_seconds(),
                "task_verification_status": verification_status,
                "task_verification_score": verification_score,
                "task_verification_reason": verification_reason,
                "task_verification_path": (
                    str(verification_path) if verification_path is not None else None
                ),
            }
        )

        if stop_on_failure and not result.success:
            typer.echo("Stopping benchmark sample due to failure.")
            break

    completed = len(results_summary)
    succeeded = sum(1 for item in results_summary if item["success"])
    failed = completed - succeeded

    typer.echo("Benchmark sample summary:")
    typer.echo(f"  Completed: {completed}")
    typer.echo(f"  Succeeded: {succeeded}")
    typer.echo(f"  Failed: {failed}")

    summaries_dir = exp_dir / "benchmark-runs"
    summaries_dir.mkdir(parents=True, exist_ok=True)
    summary_path = summaries_dir / (
        f"{config.name}-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    )

    summary_payload = {
        "pattern": str(pattern),
        "benchmark": {
            "adapter": config.benchmark.adapter,
            "id": config.benchmark.benchmark_id,
            "dataset_path": config.benchmark.dataset_path,
            "split": config.benchmark.split,
            "seed": config.benchmark.seed,
            "verifier_mode": config.benchmark.verifier_mode(),
            "sample_size": len(plan),
        },
        "results": results_summary,
    }
    with open(summary_path, "w") as f:
        json.dump(summary_payload, f, indent=2)
    typer.echo(f"  Summary JSON: {summary_path}")


@benchmark_app.command("report")
def benchmark_report(
    summary: Annotated[
        Path,
        typer.Argument(
            help="Path to benchmark summary JSON from `helm benchmark run`",
            exists=True,
            dir_okay=False,
        ),
    ],
    output: Annotated[
        Path | None,
        typer.Option(
            "--output", "-o",
            help="Optional output path for report",
        ),
    ] = None,
    format: Annotated[
        str,
        typer.Option(
            "--format",
            help="Report format: markdown or csv",
        ),
    ] = "markdown",
    experiments_dir: Annotated[
        Path | None,
        typer.Option(
            "--experiments-dir",
            help="Directory containing experiment runs (defaults from summary path)",
        ),
    ] = None,
) -> None:
    """Generate a baseline report table from a benchmark run summary."""
    with open(summary) as f:
        payload = json.load(f)

    results = payload.get("results", [])
    if not isinstance(results, list) or not results:
        typer.echo("Error: summary contains no results.", err=True)
        raise typer.Exit(1)

    experiments_root = experiments_dir or summary.parent.parent

    rows: list[dict[str, object]] = []
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

        rows.append(
            {
                "example_id": result.get("example_id"),
                "experiment_id": experiment_id,
                "run_success": result.get("success"),
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
            }
        )

    def _avg(values: list[float | int | None]) -> float | None:
        filtered = [float(v) for v in values if isinstance(v, (int, float))]
        if not filtered:
            return None
        return sum(filtered) / len(filtered)

    completed = len(rows)
    succeeded = sum(1 for row in rows if row.get("run_success") is True)
    verified_pass = sum(
        1 for row in rows if row.get("task_verification_status") == "pass"
    )
    avg_task_score = _avg(
        [row.get("task_verification_score") for row in rows]  # type: ignore[list-item]
    )
    avg_parallel = _avg(
        [row.get("parallelism_efficiency") for row in rows]  # type: ignore[list-item]
    )
    avg_coord_ratio = _avg(
        [row.get("coordination_to_output_ratio") for row in rows]  # type: ignore[list-item]
    )

    format = format.strip().lower()
    if format not in {"markdown", "csv"}:
        typer.echo("Error: --format must be 'markdown' or 'csv'.", err=True)
        raise typer.Exit(1)

    if format == "csv":
        out_path = output or summary.with_suffix(".report.csv")
        fieldnames = [
            "example_id",
            "experiment_id",
            "run_success",
            "task_verification_status",
            "task_verification_score",
            "parallelism_efficiency",
            "coordination_to_output_ratio",
            "duration_seconds",
        ]
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
        f"- Summary source: `{summary}`",
        f"- Completed runs: {completed}",
        f"- Run success rate: {(succeeded / completed * 100):.1f}%",
        f"- Verification pass rate: {(verified_pass / completed * 100):.1f}%",
        f"- Average task score: {avg_task_score:.3f}" if avg_task_score is not None else "- Average task score: n/a",
        f"- Average parallelism efficiency: {avg_parallel:.3f}" if avg_parallel is not None else "- Average parallelism efficiency: n/a",
        f"- Average coordination-to-output ratio: {avg_coord_ratio:.3f}" if avg_coord_ratio is not None else "- Average coordination-to-output ratio: n/a",
        "",
        "| example_id | experiment_id | run_success | verify_status | verify_score | parallelism | coord_to_output | duration_s |",
        "|---|---|---:|---|---:|---:|---:|---:|",
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
            + f"{row.get('experiment_id', 'n/a')} | "
            + f"{row.get('run_success', 'n/a')} | "
            + f"{row.get('task_verification_status', 'n/a')} | "
            + f"{verify_score_text} | "
            + f"{parallel_text} | "
            + f"{coord_ratio_text} | "
            + f"{duration_text} |"
        )

    report_text = "\n".join(lines)
    if output:
        with open(output, "w") as f:
            f.write(report_text)
        typer.echo(f"Report written to: {output}")
    else:
        typer.echo(report_text)


@benchmark_app.command("export")
def benchmark_export(
    summary: Annotated[
        Path,
        typer.Argument(
            help="Path to benchmark summary JSON from `helm benchmark run`",
            exists=True,
            dir_okay=False,
        ),
    ],
    output: Annotated[
        Path | None,
        typer.Option(
            "--output", "-o",
            help="Output JSONL file path (defaults next to summary)",
        ),
    ] = None,
    experiments_dir: Annotated[
        Path | None,
        typer.Option(
            "--experiments-dir",
            help="Directory containing experiment runs (defaults from summary path)",
        ),
    ] = None,
    include_failures: Annotated[
        bool,
        typer.Option(
            "--include-failures/--exclude-failures",
            help="Include failed runs in exported dataset",
        ),
    ] = True,
    min_reward: Annotated[
        float | None,
        typer.Option(
            "--min-reward",
            help="Filter out records below this reward threshold",
        ),
    ] = None,
) -> None:
    """Export benchmark summary runs into training-ready JSONL records."""
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

            record = build_training_record(run_data, transcript)
            reward = record.get("reward")
            if min_reward is not None:
                if not isinstance(reward, (int, float)) or float(reward) < min_reward:
                    skipped += 1
                    continue

            out_f.write(json.dumps(record))
            out_f.write("\n")
            exported += 1

    typer.echo(f"Exported records: {exported}")
    typer.echo(f"Skipped records: {skipped}")
    typer.echo(f"Output JSONL: {out_path}")


@benchmark_app.command("export-orchestration")
def benchmark_export_orchestration(
    source: Annotated[
        Path,
        typer.Argument(
            help="Path to benchmark training JSONL from `helm benchmark export`",
            exists=True,
            dir_okay=False,
        ),
    ],
    output: Annotated[
        Path | None,
        typer.Option(
            "--output", "-o",
            help="Output JSONL for helm-orchestration-policy environment",
        ),
    ] = None,
    min_reward: Annotated[
        float | None,
        typer.Option(
            "--min-reward",
            help="Optional minimum source reward to keep a record",
        ),
    ] = None,
    max_records: Annotated[
        int | None,
        typer.Option(
            "--max-records",
            help="Optional cap on exported records",
        ),
    ] = None,
) -> None:
    """Convert benchmark exports into helm-orchestration-policy dataset rows."""
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


@app.command()
def run(
    pattern: Annotated[
        Path,
        typer.Argument(
            help="Path to experiment pattern YAML file",
            exists=True,
            dir_okay=False,
        ),
    ],
    task: Annotated[
        str,
        typer.Option(
            "--task", "-t",
            help="Task to give to the agents",
        ),
    ],
    sdk_binary: Annotated[
        Path | None,
        typer.Option(
            "--sdk-binary",
            help="Path to sandbox-agent binary",
        ),
    ] = None,
    experiments_dir: Annotated[
        Path | None,
        typer.Option(
            "--experiments-dir",
            help="Directory to store experiment data",
        ),
    ] = None,
    on_turn_limit: Annotated[
        str | None,
        typer.Option(
            "--on-turn-limit",
            help="Action when agent hits turn limit: continue, kill, end (default: interactive prompt)",
        ),
    ] = None,
) -> None:
    """Run an experiment with the given pattern and task."""
    default_sdk, default_experiments = get_default_paths()
    sdk_path = sdk_binary or default_sdk
    exp_dir = experiments_dir or default_experiments

    if not sdk_path.exists():
        typer.echo(f"Error: SDK binary not found at {sdk_path}", err=True)
        typer.echo("Install with: npm install -g sandbox-agent", err=True)
        raise typer.Exit(1)

    turn_limit_handler = _resolve_turn_limit_handler(on_turn_limit)

    typer.echo(f"Running experiment from: {pattern}")
    typer.echo(f"Task: {task[:100]}{'...' if len(task) > 100 else ''}")
    if on_turn_limit:
        typer.echo(f"Turn limit action: {on_turn_limit}")
    typer.echo()

    try:
        result = asyncio.run(
            run_experiment(
                config_path=pattern,
                task=task,
                sdk_binary_path=sdk_path,
                experiments_dir=exp_dir,
                on_escalate=notify_escalation,
                on_turn_limit=turn_limit_handler,
            )
        )

        _print_run_result(result)

    except KeyboardInterrupt:
        typer.echo("\nExperiment interrupted")
        raise typer.Exit(130)
    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)


@app.command()
def status(
    experiment_id: Annotated[
        str,
        typer.Argument(help="Experiment ID to check"),
    ],
    experiments_dir: Annotated[
        Path | None,
        typer.Option(
            "--experiments-dir",
            help="Directory containing experiment data",
        ),
    ] = None,
) -> None:
    """Check the status of an experiment."""
    _, default_experiments = get_default_paths()
    exp_dir = experiments_dir or default_experiments

    experiment_path = exp_dir / experiment_id
    if not experiment_path.exists():
        typer.echo(f"Error: Experiment not found: {experiment_id}", err=True)
        raise typer.Exit(1)

    metadata_path = experiment_path / "metadata.json"
    if metadata_path.exists():
        with open(metadata_path) as f:
            metadata = json.load(f)
        typer.echo(f"Experiment: {metadata.get('experiment_name', experiment_id)}")
        typer.echo(f"Pattern: {metadata.get('pattern', 'unknown')}")
        typer.echo(f"Created: {metadata.get('created_at', 'unknown')}")
        typer.echo(f"Agents: {', '.join(a['id'] for a in metadata.get('agents', []))}")
    else:
        typer.echo(f"Experiment: {experiment_id}")
        typer.echo("  (metadata not found)")

    # Check for completion signals
    signals_dir = experiment_path / "coordination" / "signals"
    if signals_dir.exists():
        signals = list(signals_dir.glob("*"))
        if signals:
            typer.echo(f"Signals: {', '.join(s.name for s in signals)}")

    # Check for transcripts
    transcript_path = experiment_path / "transcripts" / "full.json"
    if transcript_path.exists():
        typer.echo(f"Transcript: {transcript_path}")


@app.command()
def stop(
    experiment_id: Annotated[
        str,
        typer.Argument(help="Experiment ID to stop"),
    ],
) -> None:
    """Stop a running experiment."""
    # For now, this is a placeholder - actual implementation would
    # need to track running experiments via a lockfile or similar
    typer.echo(f"Stopping experiment: {experiment_id}")
    typer.echo("Note: This command is not yet fully implemented")
    typer.echo("Use Ctrl+C to stop a running experiment")


@app.command("validate")
def validate_config(
    pattern: Annotated[
        Path,
        typer.Argument(
            help="Path to experiment pattern YAML file",
            exists=True,
            dir_okay=False,
        ),
    ],
) -> None:
    """Validate an experiment configuration file."""
    try:
        config = ExperimentConfig.from_yaml(pattern)
        typer.echo(f"✓ Valid configuration: {config.name}")
        typer.echo(f"  Agents: {len(config.agents)}")
        typer.echo(f"  Pattern: {'hub-and-spoke' if config.is_hub_and_spoke() else 'peer-network'}")
        typer.echo(f"  Rules: {len(config.orchestrator.rules)}")
        typer.echo(f"  Dimensions: {', '.join(config.evaluation.dimensions)}")
    except Exception as e:
        typer.echo(f"✗ Invalid configuration: {e}", err=True)
        raise typer.Exit(1)


@app.command("list")
def list_experiments(
    experiments_dir: Annotated[
        Path | None,
        typer.Option(
            "--experiments-dir",
            help="Directory containing experiment data",
        ),
    ] = None,
) -> None:
    """List all experiments."""
    _, default_experiments = get_default_paths()
    exp_dir = experiments_dir or default_experiments

    if not exp_dir.exists():
        typer.echo("No experiments found")
        return

    experiments = sorted(exp_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
    if not experiments:
        typer.echo("No experiments found")
        return

    typer.echo("Experiments:")
    for exp_path in experiments[:20]:  # Show last 20
        if not exp_path.is_dir():
            continue
        metadata_path = exp_path / "metadata.json"
        if metadata_path.exists():
            with open(metadata_path) as f:
                metadata = json.load(f)
            pattern = metadata.get("pattern", "unknown")
            created = metadata.get("created_at", "unknown")[:19]
            typer.echo(f"  {exp_path.name}  [{pattern}]  {created}")
        else:
            typer.echo(f"  {exp_path.name}")


@app.command("judge")
def judge_experiment_cmd(
    experiment_id: Annotated[
        str,
        typer.Argument(help="Experiment ID to score"),
    ],
    dimensions: Annotated[
        str | None,
        typer.Option(
            "--dimensions", "-d",
            help="Comma-separated dimension names to score (defaults to experiment config)",
        ),
    ] = None,
    backend: Annotated[
        str,
        typer.Option(
            "--backend", "-b",
            help="Judge backend: 'sdk' (free) or 'openrouter'",
        ),
    ] = "sdk",
    model: Annotated[
        str | None,
        typer.Option(
            "--model", "-m",
            help="Model for openrouter backend (e.g., 'google/gemini-2.0-flash-001')",
        ),
    ] = None,
    experiments_dir: Annotated[
        Path | None,
        typer.Option(
            "--experiments-dir",
            help="Directory containing experiment data",
        ),
    ] = None,
) -> None:
    """Score a completed experiment against behavioral dimensions."""
    from helm.judge import (
        ExperimentScores,
        OpenRouterJudge,
        SDKJudge,
        judge_experiment,
    )
    from helm.run_data import save_run_data

    _, default_experiments = get_default_paths()
    exp_dir = experiments_dir or default_experiments
    helm_dir = Path(__file__).parent.parent.parent
    judges_dir = helm_dir / "judges"

    experiment_path = exp_dir / experiment_id
    if not experiment_path.exists():
        typer.echo(f"Error: Experiment not found: {experiment_id}", err=True)
        raise typer.Exit(1)

    if not judges_dir.exists():
        judges_dir = Path.cwd() / "judges"
    if not judges_dir.exists():
        typer.echo("Error: judges/ directory not found", err=True)
        raise typer.Exit(1)

    metadata_dimensions: list[str] = []
    metadata_path = experiment_path / "metadata.json"
    if metadata_path.exists():
        with open(metadata_path) as f:
            metadata = json.load(f)
        evaluation = metadata.get("evaluation", {})
        if isinstance(evaluation, dict):
            dims = evaluation.get("dimensions", [])
            if isinstance(dims, list):
                metadata_dimensions = [str(d).strip() for d in dims if str(d).strip()]

    if dimensions:
        dimension_list = [d.strip() for d in dimensions.split(",") if d.strip()]
    elif metadata_dimensions:
        dimension_list = metadata_dimensions
    else:
        dimension_list = DEFAULT_JUDGE_DIMENSIONS.copy()

    # Create backend
    judge_backend: OpenRouterJudge | SDKJudge
    if backend == "openrouter":
        judge_model = model or "google/gemini-2.0-flash-001"
        try:
            judge_backend = OpenRouterJudge(model=judge_model)
        except ValueError as e:
            typer.echo(f"Error: {e}", err=True)
            raise typer.Exit(1)
    elif backend == "sdk":
        judge_backend = SDKJudge()
    else:
        typer.echo(f"Error: Unknown backend '{backend}'. Use 'sdk' or 'openrouter'.", err=True)
        raise typer.Exit(1)

    typer.echo(f"Judging experiment: {experiment_id}")
    typer.echo(f"Backend: {backend}" + (f" ({model or 'google/gemini-2.0-flash-001'})" if backend == "openrouter" else " (Claude Code headless)"))
    typer.echo(f"Dimensions: {', '.join(dimension_list)}")
    typer.echo()

    try:
        scores = asyncio.run(
            judge_experiment(
                experiment_dir=experiment_path,
                dimensions=dimension_list,
                judges_dir=judges_dir,
                backend=judge_backend,
                backend_name=backend,
                model_name=model if backend == "openrouter" else None,
            )
        )

        # Display results
        for s in scores.scores:
            typer.echo(f"  {s.dimension}: {s.category} [{s.severity}]")
            typer.echo(f"    {s.justification}")
            if s.evidence:
                typer.echo(f"    Evidence: {len(s.evidence)} items")
            typer.echo()

        # Save scores
        scores_path = experiment_path / "scores.json"
        scores.save(scores_path)
        typer.echo(f"Scores saved to: {scores_path}")

        run_data_path = save_run_data(experiment_path)
        typer.echo(f"Run data saved to: {run_data_path}")

    except FileNotFoundError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)
    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)


@app.command("analyze")
def analyze_experiment(
    experiment_id: Annotated[
        str,
        typer.Argument(help="Experiment ID to analyze"),
    ],
    experiments_dir: Annotated[
        Path | None,
        typer.Option(
            "--experiments-dir",
            help="Directory containing experiment data",
        ),
    ] = None,
) -> None:
    """Show summary analysis of a completed experiment."""
    _, default_experiments = get_default_paths()
    exp_dir = experiments_dir or default_experiments

    experiment_path = exp_dir / experiment_id
    if not experiment_path.exists():
        typer.echo(f"Error: Experiment not found: {experiment_id}", err=True)
        raise typer.Exit(1)

    # Load metadata
    metadata_path = experiment_path / "metadata.json"
    if not metadata_path.exists():
        typer.echo(f"Error: No metadata found for {experiment_id}", err=True)
        raise typer.Exit(1)

    with open(metadata_path) as f:
        metadata = json.load(f)

    typer.echo(f"Experiment: {metadata.get('experiment_name', experiment_id)}")
    typer.echo(f"ID: {experiment_id}")
    typer.echo(f"Pattern: {metadata.get('pattern', 'unknown')}")
    typer.echo(f"Created: {metadata.get('created_at', 'unknown')}")
    if metadata.get("task"):
        task_preview = metadata["task"][:120]
        if len(metadata["task"]) > 120:
            task_preview += "..."
        typer.echo(f"Task: {task_preview}")
    typer.echo()

    # Agents
    agents = metadata.get("agents", [])
    typer.echo(f"Agents ({len(agents)}):")
    for agent in agents:
        role = agent.get("role", "peer") or "peer"
        typer.echo(f"  {agent['id']} ({role})")
    typer.echo()

    # Runtime info
    run_info = metadata.get("run")
    if run_info:
        typer.echo("Run:")
        typer.echo(f"  Success: {run_info.get('success', 'unknown')}")
        typer.echo(f"  Duration: {run_info.get('duration_seconds', 0):.1f}s")
        if run_info.get("error"):
            typer.echo(f"  Error: {run_info['error']}")
        agent_stats = run_info.get("agent_stats", {})
        if agent_stats:
            typer.echo("  Agent turns:")
            for agent_id, stats in agent_stats.items():
                typer.echo(f"    {agent_id}: {stats.get('turns', '?')}")
        typer.echo()

    # Limits
    limits = metadata.get("limits", {})
    if limits:
        typer.echo("Limits:")
        typer.echo(f"  Max duration: {limits.get('max_duration', 'N/A')}")
        typer.echo(f"  Max turns/agent: {limits.get('max_turns_per_agent', 'N/A')}")
        typer.echo(f"  Max budget: ${limits.get('max_budget_usd', 'N/A')}")
        typer.echo()

    # Transcript stats
    transcript_json = experiment_path / "transcripts" / "full.json"
    if transcript_json.exists():
        with open(transcript_json) as f:
            transcript = json.load(f)

        total_items = transcript.get("total_items", 0)
        start_time = transcript.get("start_time", "")
        end_time = transcript.get("end_time", "")

        typer.echo("Transcript:")
        typer.echo(f"  Total events: {total_items}")
        if start_time and end_time:
            typer.echo(f"  Start: {start_time[:19]}")
            typer.echo(f"  End: {end_time[:19]}")

        # Per-agent stats
        agent_transcripts = transcript.get("agents", {})
        if agent_transcripts:
            typer.echo("  Per-agent:")
            for agent_id, agent_data in agent_transcripts.items():
                item_count = agent_data.get("item_count", 0)
                typer.echo(f"    {agent_id}: {item_count} events")
        typer.echo()
    else:
        typer.echo("Transcript: not found")
        typer.echo()

    # Scores (if available)
    scores_path = experiment_path / "scores.json"
    if scores_path.exists():
        with open(scores_path) as f:
            scores = json.load(f)

        typer.echo("Scores:")
        typer.echo(f"  Backend: {scores.get('judge_backend', 'unknown')}")
        if scores.get("judge_model"):
            typer.echo(f"  Model: {scores['judge_model']}")
        schema_version = scores.get("schema_version", "v1")
        for s in scores.get("scores", []):
            if "category" in s:
                typer.echo(f"  {s['dimension']}: {s['category']} [{s.get('severity', '?')}] — {s.get('justification', '')[:80]}...")
            else:
                typer.echo(f"  {s['dimension']}: {s.get('score', '?')}/10 — {s.get('justification', '')[:80]}...")
        typer.echo()
    else:
        typer.echo("Scores: not yet judged (run: helm judge {experiment_id})")

    # Deterministic orchestration evals / run-data contract
    run_data_path = experiment_path / "run_data.json"
    if run_data_path.exists():
        with open(run_data_path) as f:
            run_data = json.load(f)

        orchestration = run_data.get("evals", {}).get("orchestration", {})
        if orchestration:
            par = orchestration.get("parallelism_efficiency", {})
            coh = orchestration.get("coordination_overhead", {})
            esc = orchestration.get("escalation_precision_recall", {})

            def _fmt_float(value: object) -> str:
                if isinstance(value, (int, float)):
                    return f"{value:.3f}"
                return "N/A"

            typer.echo("Orchestration evals:")
            typer.echo(
                "  Parallelism efficiency: "
                + _fmt_float(par.get("value"))
                + f" (critical path ratio: {_fmt_float(par.get('critical_path_ratio'))})"
            )
            typer.echo(
                f"  Coordination overhead: {coh.get('coordination_messages', 0)} messages, "
                f"{coh.get('workspace_artifacts', 0)} workspace artifacts, "
                f"{_fmt_float(coh.get('messages_per_assistant_step'))} msgs/assistant-step"
            )
            typer.echo(
                "  Escalation precision/recall: "
                + _fmt_float(esc.get("precision"))
                + " / "
                + _fmt_float(esc.get("recall"))
            )
            typer.echo(f"  Run data: {run_data_path}")


def main() -> None:
    """Entry point for the CLI."""
    app()


if __name__ == "__main__":
    main()
