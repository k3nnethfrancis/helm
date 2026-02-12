"""CLI interface for Helm experiments.

Provides commands to run, monitor, and manage experiments.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Annotated

import typer

from helm.config import ExperimentConfig
from helm.experiment import run_experiment
from helm.sdk import SDKEvent

app = typer.Typer(
    name="helm",
    help="Observation and evaluation framework for multi-agent AI systems",
    no_args_is_help=True,
)


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

    # Select turn-limit handler
    valid_actions = {"continue", "kill", "end", "kill_agent", "end_experiment"}
    if on_turn_limit is not None:
        action = on_turn_limit.strip().lower()
        # Normalize short forms
        if action == "kill":
            action = "kill_agent"
        elif action == "end":
            action = "end_experiment"
        if action not in valid_actions:
            typer.echo(f"Error: --on-turn-limit must be one of: continue, kill, end", err=True)
            raise typer.Exit(1)
        turn_limit_handler = static_turn_limit(action)
    else:
        turn_limit_handler = prompt_turn_limit

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
        str,
        typer.Option(
            "--dimensions", "-d",
            help="Comma-separated dimension names to score",
        ),
    ] = "escalation-calibration,goal-drift,failure-suppression",
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

    dimension_list = [d.strip() for d in dimensions.split(",")]

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
            typer.echo(f"  {s.dimension}: {s.score}/10")
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
        for s in scores.get("scores", []):
            typer.echo(f"  {s['dimension']}: {s['score']}/10 — {s['justification'][:80]}...")
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
