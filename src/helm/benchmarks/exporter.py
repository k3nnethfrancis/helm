"""Export benchmark runs into training-friendly JSONL records."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from helm.collector import extract_agent_transcript


def _parse_ts(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def extract_last_assistant_text(transcript: dict[str, Any]) -> str:
    """Extract the latest assistant text message across all agents."""
    latest_ts: datetime | None = None
    latest_text = ""

    agents = transcript.get("agents", {})
    if not isinstance(agents, dict):
        return latest_text

    for agent_data in agents.values():
        if not isinstance(agent_data, dict):
            continue
        items = agent_data.get("items", [])
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            if item.get("event_type") != "item.completed":
                continue
            data = item.get("data", {})
            if not isinstance(data, dict):
                continue
            item_data = data.get("item", {})
            if not isinstance(item_data, dict):
                continue
            if item_data.get("role") != "assistant":
                continue
            content = item_data.get("content", [])
            if not isinstance(content, list):
                continue
            text_parts: list[str] = []
            fallback_parts: list[str] = []
            for part in content:
                if not isinstance(part, dict):
                    continue
                part_type = part.get("type")
                if part_type == "text":
                    text = part.get("text")
                    if isinstance(text, str) and text.strip():
                        text_parts.append(text.strip())
                elif part_type == "tool_call":
                    tool_name = part.get("name") or "unknown_tool"
                    fallback_parts.append(f"tool_call:{tool_name}")
                elif part_type == "file_ref":
                    action = part.get("action") or "file"
                    path = part.get("path") or "unknown_path"
                    fallback_parts.append(f"{action}:{path}")

            merged_text = "\n\n".join(text_parts)
            if not merged_text and fallback_parts:
                merged_text = "\n".join(fallback_parts)
            if not merged_text:
                continue
            ts = _parse_ts(item.get("timestamp"))
            if ts is None:
                # Fallback if timestamp missing: keep last seen.
                latest_text = merged_text
                continue
            if latest_ts is None or ts >= latest_ts:
                latest_ts = ts
                latest_text = merged_text

    return latest_text


def compute_composite_reward(run_data: dict[str, Any]) -> tuple[float, dict[str, float]]:
    """Compute a bounded composite reward from task + orchestration signals."""
    run = run_data.get("run", {})
    if not isinstance(run, dict):
        run = {}
    evals = run_data.get("evals", {})
    if not isinstance(evals, dict):
        evals = {}
    orchestration = evals.get("orchestration", {})
    if not isinstance(orchestration, dict):
        orchestration = {}

    task_verification = run.get("task_verification", {})
    if not isinstance(task_verification, dict):
        task_verification = {}

    score_raw = task_verification.get("score")
    task_score: float
    if isinstance(score_raw, (int, float)):
        task_score = float(score_raw)
    else:
        status = str(task_verification.get("status", "unknown"))
        if status == "pass":
            task_score = 1.0
        elif status == "fail":
            task_score = 0.0
        else:
            task_score = 0.5 if run.get("success") else 0.0

    parallel = orchestration.get("parallelism_efficiency", {})
    if not isinstance(parallel, dict):
        parallel = {}
    parallel_score_raw = parallel.get("value")
    parallel_score = (
        float(parallel_score_raw)
        if isinstance(parallel_score_raw, (int, float))
        else 0.0
    )

    overhead = orchestration.get("coordination_overhead", {})
    if not isinstance(overhead, dict):
        overhead = {}
    coord_ratio_raw = overhead.get("coordination_to_output_ratio")
    coord_ratio = (
        float(coord_ratio_raw)
        if isinstance(coord_ratio_raw, (int, float))
        else 1.0
    )
    efficiency_score = max(0.0, min(1.0, 1.0 - coord_ratio))

    reward = (0.7 * task_score) + (0.2 * parallel_score) + (0.1 * efficiency_score)
    reward = max(0.0, min(1.0, reward))

    return reward, {
        "task_score": task_score,
        "parallelism_score": parallel_score,
        "efficiency_score": efficiency_score,
    }


def build_training_record(
    run_data: dict[str, Any],
    transcript: dict[str, Any],
) -> dict[str, Any]:
    """Build one JSON-serializable training record."""
    experiment = run_data.get("experiment", {})
    if not isinstance(experiment, dict):
        experiment = {}
    run = run_data.get("run", {})
    if not isinstance(run, dict):
        run = {}
    provenance = run_data.get("provenance", {})
    if not isinstance(provenance, dict):
        provenance = {}
    policy_trace = run.get("orchestration_policy_trace")
    if not isinstance(policy_trace, dict):
        policy_trace = {
            "events": [],
            "summary": {
                "total_events": 0,
                "by_action": {},
                "by_action_family": {},
                "by_source": {},
                "by_agent": {},
            },
        }

    task = experiment.get("task")
    if not isinstance(task, str):
        task = ""

    assistant_output = extract_last_assistant_text(transcript)
    if not assistant_output:
        assistant_output = "[NO_ASSISTANT_OUTPUT]"
    reward, components = compute_composite_reward(run_data)
    matrix = experiment.get("matrix")
    if not isinstance(matrix, dict):
        matrix = None

    return {
        "id": experiment.get("id"),
        "messages": [
            {"role": "user", "content": task},
            {"role": "assistant", "content": assistant_output},
        ],
        "reward": reward,
        "reward_components": components,
        "run_success": run.get("success"),
        "run_outcome": run.get("outcome"),
        "termination_reason": run.get("termination_reason"),
        "run_system_failure": run.get("system_failure"),
        "task_verification": run.get("task_verification"),
        "orchestration_policy_trace": policy_trace,
        "benchmark": provenance.get("benchmark"),
        "matrix": matrix,
        "orchestration": run_data.get("evals", {}).get("orchestration"),
    }


def build_per_agent_training_records(
    run_data: dict[str, Any],
    transcript: dict[str, Any],
) -> list[dict[str, Any]]:
    """Build one training record per agent from a multi-agent experiment.

    Each record contains the agent's individual trace (their events only),
    tagged with their role and the experiment's shared reward.

    Reward attribution: all agents receive the same composite reward.
    This is a simplification — reward attribution across agents is an open
    research question. Shared reward is a valid starting point that lets us
    begin training while deferring credit assignment to future work.
    """
    agents_data = transcript.get("agents", {})
    if not isinstance(agents_data, dict) or not agents_data:
        return []

    experiment = run_data.get("experiment", {})
    if not isinstance(experiment, dict):
        experiment = {}
    run = run_data.get("run", {})
    if not isinstance(run, dict):
        run = {}
    provenance = run_data.get("provenance", {})
    if not isinstance(provenance, dict):
        provenance = {}

    task = experiment.get("task")
    if not isinstance(task, str):
        task = ""

    # Shared reward — same for all agents in the experiment
    reward, components = compute_composite_reward(run_data)

    # Extract agent metadata from experiment config
    agent_meta: dict[str, dict[str, Any]] = {}
    exp_agents = experiment.get("agents", [])
    if isinstance(exp_agents, list):
        for a in exp_agents:
            if isinstance(a, dict) and isinstance(a.get("id"), str):
                agent_meta[a["id"]] = a

    topology = experiment.get("pattern", "unknown")
    matrix = experiment.get("matrix")
    if not isinstance(matrix, dict):
        matrix = None

    records: list[dict[str, Any]] = []
    for agent_id in agents_data:
        agent_transcript = extract_agent_transcript(transcript, agent_id)
        if agent_transcript is None:
            continue

        agent_output = extract_last_assistant_text(agent_transcript)
        if not agent_output:
            agent_output = "[NO_ASSISTANT_OUTPUT]"

        meta = agent_meta.get(agent_id, {})

        records.append({
            "id": f"{experiment.get('id')}:{agent_id}",
            "experiment_id": experiment.get("id"),
            "agent_id": agent_id,
            "agent_role": meta.get("role"),
            "agent_harness": meta.get("harness"),
            "agent_model": meta.get("model"),
            "topology": topology,
            "messages": [
                {"role": "user", "content": task},
                {"role": "assistant", "content": agent_output},
            ],
            "trace": agent_transcript,
            "reward": reward,
            "reward_components": components,
            "reward_attribution": "shared",
            "run_success": run.get("success"),
            "run_outcome": run.get("outcome"),
            "termination_reason": run.get("termination_reason"),
            "run_system_failure": run.get("system_failure"),
            "task_verification": run.get("task_verification"),
            "benchmark": provenance.get("benchmark"),
            "matrix": matrix,
            "orchestration": run_data.get("evals", {}).get("orchestration"),
        })

    return records
