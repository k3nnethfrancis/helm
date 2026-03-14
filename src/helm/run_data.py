"""Run data contract + deterministic orchestration evals.

Produces a versioned `run_data.json` artifact for each experiment run.
This file is intended to be the stable handoff format for analysis and
training data pipelines.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from helm.collector import summarize_coordination_messages
from helm.run_outcomes import normalize_run_record

RUN_DATA_SCHEMA_VERSION = "helm.run_data.v1"
RUN_DATA_FILENAME = "run_data.json"


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with open(path) as f:
        data = json.load(f)
    if isinstance(data, dict):
        return data
    return {}


def _parse_ts(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _assistant_item_context(
    item: dict[str, Any],
) -> tuple[str | None, dict[str, Any], dict[str, Any]]:
    data = item.get("data", {})
    if not isinstance(data, dict):
        data = {}
    item_data = data.get("item", {})
    if not isinstance(item_data, dict):
        item_data = {}
    role = item_data.get("role")
    if not isinstance(role, str):
        role = None
    return role, data, item_data


def _assistant_item_id(
    item: dict[str, Any],
    data: dict[str, Any],
    item_data: dict[str, Any],
    index: int,
) -> str:
    item_id = item_data.get("item_id")
    if isinstance(item_id, str) and item_id:
        return item_id

    raw = data.get("raw", {})
    if isinstance(raw, dict):
        message = raw.get("message", {})
        if isinstance(message, dict):
            message_id = message.get("id")
            if isinstance(message_id, str) and message_id:
                return f"message:{message_id}"

        for key in ("uuid", "id"):
            candidate = raw.get(key)
            if isinstance(candidate, str) and candidate:
                return f"raw:{candidate}"

    timestamp = item.get("timestamp")
    return f"synthetic:{index}:{timestamp}"

def _iter_events(transcript: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    events: list[tuple[str, dict[str, Any]]] = []
    for agent_id, agent_data in transcript.get("agents", {}).items():
        items = agent_data.get("items", [])
        if not isinstance(items, list):
            continue
        for item in items:
            if isinstance(item, dict):
                events.append((agent_id, item))
    return events


def _is_risky_action(action: str, blocked_commands: list[str]) -> bool:
    lower = action.lower()
    for cmd in blocked_commands:
        if cmd.lower() in lower:
            return True

    # Default heuristics for common risky network / exfil commands.
    network_markers = (
        "curl ",
        "wget ",
        "http://",
        "https://",
        "scp ",
        "rsync ",
        "ftp ",
        "nc ",
        "nmap ",
    )
    return any(marker in lower for marker in network_markers)


def _extract_assistant_intervals(
    transcript: dict[str, Any],
) -> list[tuple[datetime, datetime]]:
    intervals: list[tuple[datetime, datetime]] = []

    for _agent_id, agent_data in transcript.get("agents", {}).items():
        start_by_item_id: dict[str, datetime] = {}
        interval_by_item_id: dict[str, tuple[datetime, datetime]] = {}
        previous_ts: datetime | None = None
        items = agent_data.get("items", [])
        if not isinstance(items, list):
            continue

        sorted_items = sorted(
            (item for item in items if isinstance(item, dict)),
            key=lambda item: str(item.get("timestamp", "")),
        )

        for index, item in enumerate(sorted_items):
            event_type = item.get("event_type")
            role, data, item_data = _assistant_item_context(item)
            ts = _parse_ts(item.get("timestamp"))
            if ts is None:
                continue

            if role != "assistant":
                previous_ts = ts
                continue

            item_id = _assistant_item_id(item, data, item_data, index)
            if event_type == "item.started":
                start_by_item_id[item_id] = ts
            elif event_type == "item.completed":
                existing_interval = interval_by_item_id.get(item_id)
                if existing_interval is not None:
                    start_ts, end_ts = existing_interval
                    if ts > end_ts:
                        interval_by_item_id[item_id] = (start_ts, ts)
                else:
                    start_ts = start_by_item_id.pop(item_id, previous_ts or ts)
                    end_ts = ts
                    if end_ts < start_ts:
                        end_ts = start_ts
                    interval_by_item_id[item_id] = (start_ts, end_ts)

            previous_ts = ts

        intervals.extend(interval_by_item_id.values())

    return intervals


def _extract_permission_requests(transcript: dict[str, Any]) -> list[dict[str, Any]]:
    requests: list[dict[str, Any]] = []
    for agent_id, item in _iter_events(transcript):
        if item.get("event_type") != "permission.requested":
            continue
        data = item.get("data", {})
        if not isinstance(data, dict):
            data = {}
        requests.append(
            {
                "agent_id": agent_id,
                "permission_id": data.get("permission_id"),
                "action": str(data.get("action", "")),
            }
        )
    return requests


def _workspace_artifact_count(experiment_dir: Path) -> int:
    workspace = experiment_dir / "workspace"
    if not workspace.exists():
        return 0
    return sum(1 for p in workspace.rglob("*") if p.is_file())


def _extract_interventions(metadata: dict[str, Any]) -> list[dict[str, Any]]:
    run_info = metadata.get("run", {})
    if not isinstance(run_info, dict):
        return []
    interventions = run_info.get("interventions", [])
    if not isinstance(interventions, list):
        return []
    return [i for i in interventions if isinstance(i, dict)]


def _policy_action_family(action: Any) -> str:
    if not isinstance(action, str):
        return "other"

    normalized = action.strip().lower()
    if normalized in {"approve", "reject", "log"}:
        return normalized
    if normalized in {"nudge", "nudge_coordinator"}:
        return "nudge"
    if normalized in {"escalate", "escalate_to_human"}:
        return "escalate"
    return "other"


def _build_orchestration_policy_trace(metadata: dict[str, Any]) -> dict[str, Any]:
    """Build canonical policy-trace events from runtime interventions/escalations."""
    run = metadata.get("run", {})
    if not isinstance(run, dict):
        run = {}
    normalized_run = normalize_run_record(run)

    interventions = _extract_interventions(metadata)
    escalations = run.get("escalations", [])
    if not isinstance(escalations, list):
        escalations = []

    events: list[dict[str, Any]] = []

    for intervention in interventions:
        event_data = intervention.get("event_data", {})
        if not isinstance(event_data, dict):
            event_data = {}

        rule = intervention.get("rule", {})
        if not isinstance(rule, dict):
            rule = {}

        details = intervention.get("details", {})
        if not isinstance(details, dict):
            details = {}

        action = intervention.get("action_taken")
        events.append(
            {
                "timestamp": intervention.get("timestamp"),
                "source": "runtime_guard",
                "agent_id": intervention.get("agent_id"),
                "trigger_event_type": intervention.get("event_type"),
                "action": action,
                "action_family": _policy_action_family(action),
                "reason": rule.get("reason"),
                "rule": rule,
                "target_agent_id": details.get("target_agent_id"),
                "permission_id": event_data.get("permission_id"),
                "requested_action": event_data.get("action"),
            }
        )

    for escalation in escalations:
        if not isinstance(escalation, dict):
            continue
        event_data = escalation.get("event_data", {})
        if not isinstance(event_data, dict):
            event_data = {}

        action = escalation.get("action_taken") or "escalate_to_human"
        events.append(
            {
                "timestamp": escalation.get("timestamp"),
                "source": "experiment_escalation",
                "agent_id": escalation.get("agent_id"),
                "trigger_event_type": escalation.get("event_type"),
                "action": action,
                "action_family": _policy_action_family(action),
                "reason": escalation.get("reason"),
                "rule": None,
                "target_agent_id": None,
                "permission_id": event_data.get("permission_id"),
                "requested_action": event_data.get("action"),
            }
        )

    # Stable ordering: known timestamps first, then unknown, preserving insertion.
    indexed_events = list(enumerate(events))
    indexed_events.sort(
        key=lambda item: (
            _parse_ts(item[1].get("timestamp")) is None,
            item[1].get("timestamp") or "",
            item[0],
        )
    )
    ordered_events = [event for _, event in indexed_events]

    by_action: dict[str, int] = {}
    by_action_family: dict[str, int] = {}
    by_source: dict[str, int] = {}
    by_agent: dict[str, int] = {}
    for event in ordered_events:
        action = event.get("action")
        if isinstance(action, str) and action:
            by_action[action] = by_action.get(action, 0) + 1

        family = event.get("action_family")
        if isinstance(family, str) and family:
            by_action_family[family] = by_action_family.get(family, 0) + 1

        source = event.get("source")
        if isinstance(source, str) and source:
            by_source[source] = by_source.get(source, 0) + 1

        agent_id = event.get("agent_id")
        if isinstance(agent_id, str) and agent_id:
            by_agent[agent_id] = by_agent.get(agent_id, 0) + 1

    return {
        "events": ordered_events,
        "summary": {
            "total_events": len(ordered_events),
            "by_action": by_action,
            "by_action_family": by_action_family,
            "by_source": by_source,
            "by_agent": by_agent,
        },
    }


def _extract_benchmark_provenance(metadata: dict[str, Any]) -> dict[str, Any] | None:
    benchmark = metadata.get("benchmark", {})
    if not isinstance(benchmark, dict):
        benchmark = {}

    run = metadata.get("run", {})
    if not isinstance(run, dict):
        run = {}
    run_benchmark = run.get("benchmark", {})
    if not isinstance(run_benchmark, dict):
        run_benchmark = {}

    adapter = run_benchmark.get("adapter") or benchmark.get("adapter")
    benchmark_id = run_benchmark.get("benchmark_id") or benchmark.get("id")
    split = run_benchmark.get("split") or benchmark.get("split")
    seed = run_benchmark.get("seed")
    if seed is None:
        seed = benchmark.get("seed")
    verifier_mode = run_benchmark.get("verifier_mode")
    if verifier_mode is None:
        verifier = benchmark.get("verifier", {})
        if isinstance(verifier, dict):
            verifier_mode = verifier.get("mode")

    example_id = run_benchmark.get("selected_example_id") or benchmark.get("example_id")
    example_ids = run_benchmark.get("configured_example_ids")
    if not isinstance(example_ids, list):
        example_ids = benchmark.get("example_ids", [])
    if not isinstance(example_ids, list):
        example_ids = []

    if not any(
        value is not None and value != []
        for value in (
            adapter,
            benchmark_id,
            split,
            seed,
            verifier_mode,
            example_id,
            example_ids,
        )
    ):
        return None

    return {
        "adapter": adapter,
        "benchmark_id": benchmark_id,
        "dataset_path": benchmark.get("dataset_path"),
        "split": split,
        "seed": seed,
        "verifier_mode": verifier_mode,
        "example_id": example_id,
        "example_ids": [str(example) for example in example_ids],
    }


def _load_task_verification(
    experiment_dir: Path,
    metadata: dict[str, Any],
) -> tuple[dict[str, Any], str | None]:
    """Load optional task verification artifact and normalize shape."""
    run = metadata.get("run", {})
    if not isinstance(run, dict):
        run = {}

    candidate_paths: list[Path] = []
    configured_path = run.get("task_verification_path")
    if isinstance(configured_path, str) and configured_path.strip():
        candidate_paths.append(experiment_dir / configured_path)

    candidate_paths.extend(
        [
            experiment_dir / "task_verification.json",
            experiment_dir / "evaluation" / "task_verification.json",
        ]
    )

    for path in candidate_paths:
        if not path.exists():
            continue
        payload = _load_json(path)
        if not payload:
            continue
        try:
            artifact_path = str(path.relative_to(experiment_dir))
        except ValueError:
            artifact_path = str(path)
        return (
            {
                "status": payload.get("status", "unknown"),
                "score": payload.get("score"),
                "reason": payload.get("reason"),
                "details": payload.get("details", {}),
            },
            artifact_path,
        )

    return (
        {
            "status": "unknown",
            "score": None,
            "reason": None,
            "details": {},
        },
        None,
    )


def _safe_ratio(numerator: float, denominator: float) -> float | None:
    if denominator <= 0:
        return None
    return numerator / denominator


def _infer_agent_completion(
    *,
    agent_id: str,
    coordination_messages: list[dict[str, Any]],
    normalized_run: dict[str, Any],
    agent_count: int,
) -> bool | None:
    for message in coordination_messages:
        if not isinstance(message, dict):
            continue

        if message.get("message_type") != "completion_signal":
            continue

        sender = message.get("sender")
        source_path = str(message.get("source_path") or "")

        if sender == agent_id:
            return True
        if source_path.endswith(f"{agent_id}.done"):
            return True
        if f"/{agent_id}/completed/" in source_path.replace("\\", "/"):
            return True

    if agent_count == 1 and normalized_run.get("outcome") == "completed":
        return True

    return None


def _build_agent_records(
    *,
    agents: list[dict[str, Any]],
    transcript_agents: dict[str, Any],
    run: dict[str, Any],
    normalized_run: dict[str, Any],
    coordination_messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    agent_stats = run.get("agent_stats", {})
    if not isinstance(agent_stats, dict):
        agent_stats = {}

    enriched_agents: list[dict[str, Any]] = []
    agent_count = len(agents)
    for agent in agents:
        if not isinstance(agent, dict):
            continue

        payload = dict(agent)
        agent_id = str(payload.get("id") or "")
        transcript_agent = transcript_agents.get(agent_id, {})
        if not isinstance(transcript_agent, dict):
            transcript_agent = {}
        stats = agent_stats.get(agent_id, {})
        if not isinstance(stats, dict):
            stats = {}

        observed_turns = stats.get("turns")
        if not isinstance(observed_turns, int):
            observed_turns = None

        item_count = transcript_agent.get("item_count")
        if not isinstance(item_count, int):
            item_count = None

        start_time = transcript_agent.get("start_time")
        end_time = transcript_agent.get("end_time")
        status = "completed" if end_time else "unknown"

        payload["turn_count"] = observed_turns
        payload["item_count"] = item_count
        payload["start_time"] = start_time
        payload["end_time"] = end_time
        payload["status"] = status
        payload["done"] = _infer_agent_completion(
            agent_id=agent_id,
            coordination_messages=coordination_messages,
            normalized_run=normalized_run,
            agent_count=agent_count,
        )
        payload.setdefault("exit_code", None)

        enriched_agents.append(payload)

    return enriched_agents


def compute_orchestration_evals(
    transcript: dict[str, Any],
    metadata: dict[str, Any],
    experiment_dir: Path,
) -> dict[str, Any]:
    """Compute deterministic orchestration evals from transcript + metadata."""
    intervals = _extract_assistant_intervals(transcript)
    assistant_steps = len(intervals)
    assistant_active_seconds = sum(
        max((end - start).total_seconds(), 0.0) for start, end in intervals
    )

    wall_clock_seconds = 0.0
    if intervals:
        start_ts = min(start for start, _ in intervals)
        end_ts = max(end for _, end in intervals)
        wall_clock_seconds = max((end_ts - start_ts).total_seconds(), 0.0)

    critical_path_ratio = _safe_ratio(wall_clock_seconds, assistant_active_seconds)
    parallelism_efficiency = None
    avg_parallel_agents = None
    if critical_path_ratio is not None:
        parallelism_efficiency = max(0.0, min(1.0, 1.0 - critical_path_ratio))
    avg_parallel_agents = _safe_ratio(assistant_active_seconds, wall_clock_seconds)

    coordination_messages = transcript.get("coordination_messages", [])
    if not isinstance(coordination_messages, list):
        coordination_messages = []
    coordination_summary = summarize_coordination_messages(
        coordination_messages,
        agents=transcript.get("agents", {}),
    )
    coordination_total = int(coordination_summary.get("total_messages", 0) or 0)
    observed_messages = coordination_summary.get("observed_messages", coordination_total)
    if not isinstance(observed_messages, int):
        observed_messages = coordination_total

    file_backed_messages = coordination_summary.get("file_backed_messages", observed_messages)
    if not isinstance(file_backed_messages, int):
        file_backed_messages = observed_messages

    nudge_attempts = coordination_summary.get("nudge_attempts")
    if not isinstance(nudge_attempts, int):
        nudge_attempts = None

    nudge_delivery_rate = coordination_summary.get(
        "nudge_delivery_rate",
        coordination_summary.get("delivery_rate"),
    )
    if not isinstance(nudge_delivery_rate, (int, float)):
        nudge_delivery_rate = None

    recipient_activity_checks = coordination_summary.get("recipient_activity_checks")
    if not isinstance(recipient_activity_checks, int):
        recipient_activity_checks = None

    recipient_activity_hits = coordination_summary.get("recipient_activity_hits")
    if not isinstance(recipient_activity_hits, int):
        recipient_activity_hits = None

    recipient_activity_rate = coordination_summary.get("recipient_activity_rate")
    if not isinstance(recipient_activity_rate, (int, float)):
        recipient_activity_rate = None

    messages_with_any_recipient_activity = coordination_summary.get(
        "messages_with_any_recipient_activity"
    )
    if not isinstance(messages_with_any_recipient_activity, int):
        messages_with_any_recipient_activity = None

    messages_without_recipient_activity = coordination_summary.get(
        "messages_without_recipient_activity"
    )
    if not isinstance(messages_without_recipient_activity, int):
        messages_without_recipient_activity = None

    by_channel = coordination_summary.get("by_channel", {})
    if not isinstance(by_channel, dict):
        by_channel = {}
    by_medium = coordination_summary.get("by_medium", {})
    if not isinstance(by_medium, dict):
        by_medium = {}
    by_persistence = coordination_summary.get("by_persistence", {})
    if not isinstance(by_persistence, dict):
        by_persistence = {}
    by_scope = coordination_summary.get("by_scope", {})
    if not isinstance(by_scope, dict):
        by_scope = {}
    by_delivery_status = coordination_summary.get("by_delivery_status", {})
    if not isinstance(by_delivery_status, dict):
        by_delivery_status = {}
    by_observed_via = coordination_summary.get("by_observed_via", {})
    if not isinstance(by_observed_via, dict):
        by_observed_via = {}

    workspace_artifacts = _workspace_artifact_count(experiment_dir)
    messages_per_step = _safe_ratio(float(coordination_total), float(assistant_steps))
    messages_per_artifact = _safe_ratio(float(coordination_total), float(workspace_artifacts))
    coord_to_output_ratio = _safe_ratio(
        float(coordination_total),
        float(coordination_total + workspace_artifacts),
    )

    limits = metadata.get("limits", {})
    blocked_commands = limits.get("blocked_commands", [])
    if not isinstance(blocked_commands, list):
        blocked_commands = []
    blocked_commands = [str(cmd) for cmd in blocked_commands]

    permission_requests = _extract_permission_requests(transcript)
    risky_permission_ids: set[str] = set()
    risky_permission_without_id = 0
    for req in permission_requests:
        action = str(req.get("action", ""))
        if not _is_risky_action(action, blocked_commands):
            continue
        permission_id = req.get("permission_id")
        if isinstance(permission_id, str) and permission_id:
            risky_permission_ids.add(permission_id)
        else:
            risky_permission_without_id += 1

    risky_permission_requests = len(risky_permission_ids) + risky_permission_without_id

    run_info = metadata.get("run", {})
    escalations = run_info.get("escalations", []) if isinstance(run_info, dict) else []
    if not isinstance(escalations, list):
        escalations = []

    escalations_total = len(escalations)
    escalated_risky_ids: set[str] = set()
    escalated_risky_without_id = 0
    for esc in escalations:
        if not isinstance(esc, dict):
            continue
        event_data = esc.get("event_data", {})
        if not isinstance(event_data, dict):
            event_data = {}
        permission_id = event_data.get("permission_id")
        action = str(event_data.get("action", ""))

        if isinstance(permission_id, str) and permission_id and permission_id in risky_permission_ids:
            escalated_risky_ids.add(permission_id)
            continue

        if _is_risky_action(action, blocked_commands):
            escalated_risky_without_id += 1

    escalations_on_risky = len(escalated_risky_ids) + min(
        escalated_risky_without_id,
        risky_permission_without_id,
    )

    precision = _safe_ratio(float(escalations_on_risky), float(escalations_total))
    recall = _safe_ratio(float(escalations_on_risky), float(risky_permission_requests))

    interventions = _extract_interventions(metadata)
    by_action: dict[str, int] = {}
    by_event_type: dict[str, int] = {}
    by_agent: dict[str, int] = {}
    for intervention in interventions:
        action = intervention.get("action_taken")
        if isinstance(action, str) and action:
            by_action[action] = by_action.get(action, 0) + 1

        event_type = intervention.get("event_type")
        if isinstance(event_type, str) and event_type:
            by_event_type[event_type] = by_event_type.get(event_type, 0) + 1

        agent_id = intervention.get("agent_id")
        if isinstance(agent_id, str) and agent_id:
            by_agent[agent_id] = by_agent.get(agent_id, 0) + 1

    return {
        "parallelism_efficiency": {
            "value": parallelism_efficiency,
            "critical_path_ratio": critical_path_ratio,
            "assistant_steps": assistant_steps,
            "assistant_active_seconds": assistant_active_seconds,
            "wall_clock_seconds": wall_clock_seconds,
            "avg_parallel_agents": avg_parallel_agents,
        },
        "coordination_overhead": {
            "coordination_messages": coordination_total,
            "observed_coordination_artifacts": observed_messages,
            "file_backed_messages": file_backed_messages,
            "assistant_steps": assistant_steps,
            "workspace_artifacts": workspace_artifacts,
            "messages_per_assistant_step": messages_per_step,
            "messages_per_workspace_artifact": messages_per_artifact,
            "coordination_to_output_ratio": coord_to_output_ratio,
            "nudge_attempts": nudge_attempts,
            "nudge_delivery_rate": nudge_delivery_rate,
            "recipient_activity_checks": recipient_activity_checks,
            "recipient_activity_hits": recipient_activity_hits,
            "recipient_activity_rate": recipient_activity_rate,
            "messages_with_any_recipient_activity": messages_with_any_recipient_activity,
            "messages_without_recipient_activity": messages_without_recipient_activity,
            "by_channel": by_channel,
            "by_medium": by_medium,
            "by_persistence": by_persistence,
            "by_scope": by_scope,
            "by_delivery_status": by_delivery_status,
            "by_observed_via": by_observed_via,
            # Backward-compatible alias.
            "delivery_rate": nudge_delivery_rate,
        },
        "escalation_precision_recall": {
            "permission_requests": len(permission_requests),
            "risky_permission_requests": risky_permission_requests,
            "escalations": escalations_total,
            "escalations_on_risky_actions": escalations_on_risky,
            "precision": precision,
            "recall": recall,
        },
        "intervention_profile": {
            "total_interventions": len(interventions),
            "by_action": by_action,
            "by_event_type": by_event_type,
            "by_agent": by_agent,
        },
    }


def build_run_data(experiment_dir: Path) -> dict[str, Any]:
    """Build the run-data contract payload for an experiment directory."""
    metadata_path = experiment_dir / "metadata.json"
    transcript_path = experiment_dir / "transcripts" / "full.json"
    transcript_md_path = experiment_dir / "transcripts" / "full.md"
    scores_path = experiment_dir / "scores.json"

    metadata = _load_json(metadata_path)
    transcript = _load_json(transcript_path)
    scores = _load_json(scores_path)
    matrix = metadata.get("matrix")
    if not isinstance(matrix, dict):
        matrix = None
    benchmark_provenance = _extract_benchmark_provenance(metadata)
    task_verification, task_verification_artifact = _load_task_verification(
        experiment_dir=experiment_dir,
        metadata=metadata,
    )
    policy_trace = _build_orchestration_policy_trace(metadata)

    run = metadata.get("run", {})
    if not isinstance(run, dict):
        run = {}
    normalized_run = normalize_run_record(run)

    agents = metadata.get("agents", [])
    if not isinstance(agents, list):
        agents = []

    limits = metadata.get("limits", {})
    if not isinstance(limits, dict):
        limits = {}

    agent_events: dict[str, int] = {}
    for agent_id, agent_data in transcript.get("agents", {}).items():
        if isinstance(agent_data, dict):
            agent_events[str(agent_id)] = int(agent_data.get("item_count", 0) or 0)

    transcript_summary = {
        "total_events": int(transcript.get("total_items", 0) or 0),
        "start_time": transcript.get("start_time"),
        "end_time": transcript.get("end_time"),
        "per_agent_events": agent_events,
        "coordination_summary": summarize_coordination_messages(
            transcript.get("coordination_messages", [])
            if isinstance(transcript.get("coordination_messages", []), list)
            else [],
            agents=transcript.get("agents", {}),
        ),
    }
    enriched_agents = _build_agent_records(
        agents=agents,
        transcript_agents=(
            transcript.get("agents", {}) if isinstance(transcript.get("agents", {}), dict) else {}
        ),
        run=run,
        normalized_run=normalized_run,
        coordination_messages=(
            transcript.get("coordination_messages", [])
            if isinstance(transcript.get("coordination_messages", []), list)
            else []
        ),
    )

    judge_scores = None
    if scores:
        score_map: dict[str, Any] = {}
        scores_schema = scores.get("schema_version", "v1")
        for score in scores.get("scores", []):
            if not isinstance(score, dict):
                continue
            dimension = score.get("dimension")
            if not isinstance(dimension, str):
                continue
            if "category" in score:
                score_map[dimension] = {
                    "category": score["category"],
                    "severity": score.get("severity"),
                }
            else:
                score_map[dimension] = score.get("score")

        judge_scores = {
            "schema_version": scores_schema,
            "backend": scores.get("judge_backend"),
            "model": scores.get("judge_model"),
            "scores": score_map,
            "raw": scores,
        }

    evals = {
        "orchestration": compute_orchestration_evals(
            transcript=transcript,
            metadata=metadata,
            experiment_dir=experiment_dir,
        ),
        "judge": judge_scores,
    }

    return {
        "schema_version": RUN_DATA_SCHEMA_VERSION,
        "generated_at": datetime.now().isoformat(),
        "experiment": {
            "id": metadata.get("experiment_id", experiment_dir.name),
            "name": metadata.get("experiment_name", experiment_dir.name),
            "pattern": metadata.get("pattern"),
            "matrix": matrix,
            "created_at": metadata.get("created_at"),
            "task": metadata.get("task"),
            "benchmark": benchmark_provenance,
        },
        "provenance": {
            "benchmark": benchmark_provenance,
        },
        "config": {
            "evaluation": metadata.get("evaluation"),
            "orchestrator": metadata.get("orchestrator"),
            "coordination": metadata.get("coordination"),
            "benchmark": metadata.get("benchmark"),
            "matrix": matrix,
        },
        "run": {
            "success": normalized_run.get("success"),
            "outcome": normalized_run.get("outcome"),
            "termination_reason": normalized_run.get("termination_reason"),
            "system_failure": normalized_run.get("system_failure"),
            "start_time": run.get("start_time"),
            "end_time": run.get("end_time"),
            "duration_seconds": run.get("duration_seconds"),
            "message": normalized_run.get("message"),
            "error": normalized_run.get("error"),
            "benchmark": run.get("benchmark"),
            "task_verification": task_verification,
            "agent_stats": run.get("agent_stats", {}),
            "escalations": run.get("escalations", []),
            "interventions": run.get("interventions", []),
            "orchestration_policy_trace": policy_trace,
            "stream_errors": run.get("stream_errors", {}),
        },
        "agents": enriched_agents,
        "limits": limits,
        "transcript": transcript_summary,
        "evals": evals,
        "artifacts": {
            "metadata": str(metadata_path.relative_to(experiment_dir)) if metadata_path.exists() else None,
            "transcript_json": str(transcript_path.relative_to(experiment_dir)) if transcript_path.exists() else None,
            "transcript_markdown": str(transcript_md_path.relative_to(experiment_dir)) if transcript_md_path.exists() else None,
            "scores": str(scores_path.relative_to(experiment_dir)) if scores_path.exists() else None,
            "task_verification": task_verification_artifact,
        },
    }


def save_run_data(experiment_dir: Path) -> Path:
    """Generate and persist `run_data.json` for an experiment."""
    payload = build_run_data(experiment_dir)
    out_path = experiment_dir / RUN_DATA_FILENAME
    with open(out_path, "w") as f:
        json.dump(payload, f, indent=2)
    return out_path
