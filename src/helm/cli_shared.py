"""Shared helpers and constants for the Helm CLI."""

from __future__ import annotations

from pathlib import Path

import typer

from helm.sdk import SDKEvent

ACTIVE_BEHAVIORAL_DIMENSIONS = [
    "escalation-calibration",
    "goal-drift",
    "failure-suppression",
    "context-degradation",
    "resource-waste",
]

DEFAULT_JUDGE_DIMENSIONS = ACTIVE_BEHAVIORAL_DIMENSIONS.copy()

DIMENSION_SHORT_LABELS = {
    "escalation-calibration": "EC",
    "goal-drift": "GD",
    "failure-suppression": "FS",
    "context-degradation": "CD",
    "resource-waste": "RW",
}


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
        if choice.startswith("+") and choice[1:].isdigit():
            return ("extend", int(choice[1:]))
        if choice == "k":
            return ("kill_agent", None)
        if choice == "e":
            return ("end_experiment", None)
        typer.echo("  Invalid. Enter C, +N (e.g. +20), K, or E")


def static_turn_limit(action: str) -> callable:
    """Return a non-interactive turn-limit handler for the given action."""

    def handler(agent_id: str, turns: int, limit: int) -> tuple[str, int | None]:
        typer.echo(f"\n⚠ Agent '{agent_id}' reached turn limit ({turns}/{limit}) → {action}")
        return (action, None)

    return handler


def resolve_turn_limit_handler(on_turn_limit: str | None) -> callable:
    """Resolve configured or interactive turn limit behavior."""
    valid_actions = {"continue", "kill", "end", "kill_agent", "end_experiment"}
    if on_turn_limit is not None:
        action = on_turn_limit.strip().lower()
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


def print_run_result(result) -> None:
    """Print a consistent summary for a finished run result."""
    if result.outcome == "completed":
        typer.echo(f"✓ Experiment completed: {result.experiment_id}")
    elif result.outcome == "paused":
        typer.echo(
            f"⚠ Experiment paused: {result.message or result.termination_reason}"
        )
    elif result.outcome == "incomplete":
        typer.echo(
            f"⚠ Experiment ended incomplete: {result.message or result.termination_reason}"
        )
    else:
        typer.echo(f"✗ Experiment failed: {result.error or result.message}")

    typer.echo(
        f"  Outcome: {result.outcome} ({result.termination_reason})"
        + (" [system failure]" if result.system_failure else "")
    )

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
    helm_dir = Path(__file__).parent.parent.parent
    sdk_binary = helm_dir / "bin" / "sandbox-agent"

    if not sdk_binary.exists():
        cwd_binary = Path.cwd() / "bin" / "sandbox-agent"
        if cwd_binary.exists():
            sdk_binary = cwd_binary
        else:
            import shutil

            npm_binary = shutil.which("sandbox-agent")
            if npm_binary:
                sdk_binary = Path(npm_binary)

    experiments_dir = helm_dir / "experiments"
    if not experiments_dir.exists():
        experiments_dir = Path.cwd() / "experiments"

    return sdk_binary, experiments_dir


def metadata_backed_experiment_dirs(experiments_dir: Path) -> list[Path]:
    """Return experiment directories that contain canonical metadata."""
    return sorted(
        (
            path
            for path in experiments_dir.iterdir()
            if path.is_dir() and (path / "metadata.json").exists()
        ),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
