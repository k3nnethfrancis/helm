"""Helpers for structured run outcome normalization and metadata backfill."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def normalize_run_record(run: dict[str, Any]) -> dict[str, Any]:
    """Backfill structured run outcome fields from older metadata when absent."""
    success = bool(run.get("success"))
    outcome = run.get("outcome")
    termination_reason = run.get("termination_reason")
    system_failure = run.get("system_failure")
    message = run.get("message")
    error = run.get("error")

    if isinstance(outcome, str) and outcome:
        return {
            "success": success,
            "outcome": outcome,
            "termination_reason": termination_reason,
            "system_failure": bool(system_failure),
            "message": message,
            "error": error,
        }

    if success:
        return {
            "success": True,
            "outcome": "completed",
            "termination_reason": "completion_signal",
            "system_failure": False,
            "message": message or "Run reached completion signals.",
            "error": error,
        }

    error_text = str(error or "")
    lowered = error_text.lower()

    if "turn limit reached" in lowered:
        return {
            "success": False,
            "outcome": "incomplete",
            "termination_reason": "turn_limit",
            "system_failure": False,
            "message": message or error_text or "Turn limit reached before completion signals were observed.",
            "error": None,
        }
    if "timeout exceeded" in lowered:
        return {
            "success": False,
            "outcome": "incomplete",
            "termination_reason": "timeout",
            "system_failure": False,
            "message": message or "Timeout reached before completion signals were observed.",
            "error": None,
        }
    if "escalation required human input" in lowered:
        return {
            "success": False,
            "outcome": "paused",
            "termination_reason": "human_escalation",
            "system_failure": False,
            "message": message or error_text,
            "error": None,
        }
    if "event stream failed" in lowered:
        return {
            "success": False,
            "outcome": "failed",
            "termination_reason": "stream_error",
            "system_failure": True,
            "message": message or error_text,
            "error": error_text or None,
        }
    if "stopped before completion signals" in lowered:
        return {
            "success": False,
            "outcome": "incomplete",
            "termination_reason": "stopped",
            "system_failure": False,
            "message": message or error_text,
            "error": None,
        }
    if "before completion signals were observed" in lowered:
        return {
            "success": False,
            "outcome": "incomplete",
            "termination_reason": "missing_completion_signal",
            "system_failure": False,
            "message": message or error_text,
            "error": None,
        }

    return {
        "success": False,
        "outcome": "failed",
        "termination_reason": "legacy_error",
        "system_failure": True,
        "message": message or error_text or "Run failed before completion signals were observed.",
        "error": error_text or None,
    }


def merge_normalized_run_record(run: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of `run` with normalized structured outcome fields applied."""
    updated = dict(run)
    normalized = normalize_run_record(updated)
    updated.update(normalized)
    return updated


def normalize_topology_pattern(metadata: dict[str, Any]) -> str | None:
    """Infer the canonical topology label from stored agent metadata."""
    agents = metadata.get("agents")
    if not isinstance(agents, list) or not agents:
        pattern = metadata.get("pattern")
        return pattern if isinstance(pattern, str) and pattern else None

    if len(agents) <= 1:
        return "single-agent"

    for agent in agents:
        if not isinstance(agent, dict):
            continue
        role = agent.get("role")
        if isinstance(role, str) and role == "hub":
            return "hub-and-spoke"

    return "peer-network"


def backfill_metadata_file(metadata_path: Path) -> bool:
    """Rewrite a metadata file with normalized structured run outcome fields."""
    if not metadata_path.exists():
        raise FileNotFoundError(metadata_path)

    with open(metadata_path) as f:
        metadata = json.load(f)

    if not isinstance(metadata, dict):
        raise ValueError(f"Metadata file must contain a JSON object: {metadata_path}")

    run = metadata.get("run", {})
    if not isinstance(run, dict):
        run = {}

    updated_run = merge_normalized_run_record(run)
    pattern = normalize_topology_pattern(metadata)
    metadata_changed = updated_run != run
    if pattern is not None and metadata.get("pattern") != pattern:
        metadata["pattern"] = pattern
        metadata_changed = True

    if not metadata_changed:
        return False

    metadata["run"] = updated_run
    metadata_path.write_text(json.dumps(metadata, indent=2) + "\n")
    return True
