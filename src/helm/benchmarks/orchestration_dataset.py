"""Build Helm orchestration-policy training rows from benchmark exports."""

from __future__ import annotations

import json
from typing import Any

_ROUTE_NONE = "none"
_ROUTE_ORCH_ONLY = "orchestrator_only"
_ROUTE_HUMAN_DIRECT = "human_direct"
_ROUTE_ORCH_THEN_HUMAN = "orchestrator_then_human"

_POLICY_TAGS = (
    "escalation_route",
    "dominant_intervention",
    "intervention_intensity",
    "parallelism_target",
    "coordination_style",
    "verification_gate",
    "human_gate_required",
)


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {}


def _to_float(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _to_int(value: Any) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return 0


def _dominant_label(values: dict[str, Any], default: str) -> str:
    best_label = default
    best_value = float("-inf")
    for label, raw_value in values.items():
        if not isinstance(label, str):
            continue
        value = float(_to_int(raw_value))
        if value > best_value:
            best_label = label
            best_value = value
    if best_value <= 0:
        return default
    return best_label


def _bucket_parallelism(value: float | None) -> str:
    if value is None:
        return "unknown"
    if value < 0.2:
        return "low"
    if value < 0.6:
        return "medium"
    return "high"


def _bucket_coordination_style(coord_ratio: float | None) -> str:
    if coord_ratio is None:
        return "unknown"
    if coord_ratio <= 0.2:
        return "lean"
    if coord_ratio <= 0.5:
        return "balanced"
    return "heavy"


def _bucket_intervention_intensity(total_events: int) -> str:
    if total_events <= 0:
        return "none"
    if total_events <= 2:
        return "light"
    if total_events <= 5:
        return "medium"
    return "heavy"


def _extract_user_task(record: dict[str, Any]) -> str:
    messages = record.get("messages")
    if isinstance(messages, list):
        for message in messages:
            if not isinstance(message, dict):
                continue
            if message.get("role") != "user":
                continue
            content = message.get("content")
            if isinstance(content, str) and content.strip():
                return content.strip()
    fallback = record.get("id")
    if isinstance(fallback, str) and fallback:
        return f"Benchmark task {fallback}"
    return "Unknown benchmark task."


def _derive_escalation_route(by_source: dict[str, Any], by_action: dict[str, Any]) -> str:
    human_events = _to_int(by_source.get("human"))
    orchestrator_events = _to_int(by_source.get("orchestrator"))
    escalate_events = _to_int(by_action.get("escalate"))

    if human_events > 0 and orchestrator_events > 0:
        return _ROUTE_ORCH_THEN_HUMAN
    if human_events > 0:
        return _ROUTE_HUMAN_DIRECT
    if orchestrator_events > 0 or escalate_events > 0:
        return _ROUTE_ORCH_ONLY
    return _ROUTE_NONE


def derive_policy_target(record: dict[str, Any]) -> dict[str, str]:
    """Derive deterministic orchestration-policy labels from an export record."""
    trace = _as_dict(record.get("orchestration_policy_trace"))
    summary = _as_dict(trace.get("summary"))
    by_source = _as_dict(summary.get("by_source"))
    by_action = _as_dict(summary.get("by_action"))
    total_events = _to_int(summary.get("total_events"))

    orchestration = _as_dict(record.get("orchestration"))
    parallel = _as_dict(orchestration.get("parallelism_efficiency"))
    overhead = _as_dict(orchestration.get("coordination_overhead"))

    task_verification = _as_dict(record.get("task_verification"))
    verification_status = task_verification.get("status")
    verification_gate = (
        verification_status
        if isinstance(verification_status, str) and verification_status in {"pass", "fail"}
        else "unknown"
    )

    escalation_route = _derive_escalation_route(by_source, by_action)
    human_gate_required = (
        "yes"
        if escalation_route in {_ROUTE_HUMAN_DIRECT, _ROUTE_ORCH_THEN_HUMAN}
        else "no"
    )

    return {
        "escalation_route": escalation_route,
        "dominant_intervention": _dominant_label(by_action, default="none"),
        "intervention_intensity": _bucket_intervention_intensity(total_events),
        "parallelism_target": _bucket_parallelism(_to_float(parallel.get("value"))),
        "coordination_style": _bucket_coordination_style(
            _to_float(overhead.get("coordination_to_output_ratio"))
        ),
        "verification_gate": verification_gate,
        "human_gate_required": human_gate_required,
    }


def build_policy_prompt(record: dict[str, Any]) -> str:
    """Construct a deterministic policy-planning prompt from a Helm export row."""
    task = _extract_user_task(record)
    benchmark = _as_dict(record.get("benchmark"))
    benchmark_id = benchmark.get("benchmark_id")
    benchmark_text = benchmark_id if isinstance(benchmark_id, str) else "unknown"

    reward_value = _to_float(record.get("reward"))
    reward_text = f"{reward_value:.3f}" if reward_value is not None else "unknown"

    return "\n".join(
        [
            "You are an orchestration policy model for a multi-agent system.",
            "Given the task and run context, output ONLY XML with one value for each required tag.",
            "",
            "Task:",
            task,
            "",
            "Run context:",
            f"- benchmark_id: {benchmark_text}",
            f"- observed_reward: {reward_text}",
            "",
            "Required tags and allowed values:",
            (
                "- <escalation_route>: none | orchestrator_only | human_direct | "
                "orchestrator_then_human"
            ),
            "- <dominant_intervention>: none | approve | reject | escalate | log | nudge",
            "- <intervention_intensity>: none | light | medium | heavy",
            "- <parallelism_target>: low | medium | high | unknown",
            "- <coordination_style>: lean | balanced | heavy | unknown",
            "- <verification_gate>: pass | fail | unknown",
            "- <human_gate_required>: yes | no",
            "",
            "Do not include any prose outside XML tags.",
        ]
    )


def normalize_orchestration_record(record: dict[str, Any]) -> dict[str, Any]:
    """Normalize either benchmark-export or policy-export rows to env dataset rows."""
    question = record.get("question")
    answer = record.get("answer")

    if isinstance(question, str) and answer is not None:
        if isinstance(answer, str):
            try:
                parsed = json.loads(answer)
                if isinstance(parsed, dict):
                    answer = parsed
            except json.JSONDecodeError:
                pass
        if not isinstance(answer, dict):
            raise ValueError("Row 'answer' must be an object or JSON object string.")
        return {
            "question": question,
            "answer": answer,
            "task": "helm-orchestration-policy",
            "info": _as_dict(record.get("info")),
        }

    return build_orchestration_training_row(record)


def build_orchestration_training_row(record: dict[str, Any]) -> dict[str, Any]:
    """Convert a benchmark-export record into a policy-training dataset row."""
    target = derive_policy_target(record)
    task_id = record.get("id")
    benchmark = _as_dict(record.get("benchmark"))

    info: dict[str, Any] = {
        "source_id": task_id if isinstance(task_id, str) else "",
        "benchmark": benchmark,
        "reward": _to_float(record.get("reward")),
        "policy_tags": list(_POLICY_TAGS),
    }

    return {
        "question": build_policy_prompt(record),
        "answer": target,
        "task": "helm-orchestration-policy",
        "info": info,
    }
