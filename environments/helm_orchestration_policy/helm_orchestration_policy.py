"""Helm orchestration-policy verifiers environment."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import verifiers as vf
from datasets import Dataset, load_dataset

POLICY_TAGS = (
    "escalation_route",
    "dominant_intervention",
    "intervention_intensity",
    "parallelism_target",
    "coordination_style",
    "verification_gate",
    "human_gate_required",
)

ALLOWED_VALUES: dict[str, set[str]] = {
    "escalation_route": {
        "none",
        "orchestrator_only",
        "human_direct",
        "orchestrator_then_human",
    },
    "dominant_intervention": {"none", "approve", "reject", "escalate", "log", "nudge"},
    "intervention_intensity": {"none", "light", "medium", "heavy"},
    "parallelism_target": {"low", "medium", "high", "unknown"},
    "coordination_style": {"lean", "balanced", "heavy", "unknown"},
    "verification_gate": {"pass", "fail", "unknown"},
    "human_gate_required": {"yes", "no"},
}

SYSTEM_PROMPT = """You are an orchestration policy model for a multi-agent system.

You must output exactly 7 XML tags, one per line, with no other text.

Allowed values for each tag:
- <escalation_route>: none | orchestrator_only | human_direct | orchestrator_then_human
- <dominant_intervention>: none | approve | reject | escalate | log | nudge
- <intervention_intensity>: none | light | medium | heavy
- <parallelism_target>: low | medium | high | unknown
- <coordination_style>: lean | balanced | heavy | unknown
- <verification_gate>: pass | fail | unknown
- <human_gate_required>: yes | no

## Example 1 (low-risk routine task)

<escalation_route>none</escalation_route>
<dominant_intervention>log</dominant_intervention>
<intervention_intensity>light</intervention_intensity>
<parallelism_target>medium</parallelism_target>
<coordination_style>lean</coordination_style>
<verification_gate>pass</verification_gate>
<human_gate_required>no</human_gate_required>

## Example 2 (task requiring human escalation)

<escalation_route>orchestrator_then_human</escalation_route>
<dominant_intervention>escalate</dominant_intervention>
<intervention_intensity>heavy</intervention_intensity>
<parallelism_target>low</parallelism_target>
<coordination_style>heavy</coordination_style>
<verification_gate>fail</verification_gate>
<human_gate_required>yes</human_gate_required>

## Example 3 (moderate complexity, orchestrator handles issues)

<escalation_route>orchestrator_only</escalation_route>
<dominant_intervention>nudge</dominant_intervention>
<intervention_intensity>medium</intervention_intensity>
<parallelism_target>high</parallelism_target>
<coordination_style>balanced</coordination_style>
<verification_gate>pass</verification_gate>
<human_gate_required>no</human_gate_required>

Do NOT wrap tags in any outer element. Do NOT add prose, explanation, or markdown.
Output ONLY the 7 XML tags above with appropriate values filled in."""

_ROUTE_TO_GATE = {
    "none": "no",
    "orchestrator_only": "no",
    "human_direct": "yes",
    "orchestrator_then_human": "yes",
}


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _to_int(value: Any) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return 0


def _to_float(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _dominant_label(values: dict[str, Any], default: str = "none") -> str:
    best_label = default
    best_value = float("-inf")
    for label, raw_value in values.items():
        if not isinstance(label, str):
            continue
        score = float(_to_int(raw_value))
        if score > best_value:
            best_label = label
            best_value = score
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


def _bucket_coordination_style(value: float | None) -> str:
    if value is None:
        return "unknown"
    if value <= 0.2:
        return "lean"
    if value <= 0.5:
        return "balanced"
    return "heavy"


def _bucket_intensity(total_events: int) -> str:
    if total_events <= 0:
        return "none"
    if total_events <= 2:
        return "light"
    if total_events <= 5:
        return "medium"
    return "heavy"


def _extract_user_task(messages: Any) -> str:
    if isinstance(messages, list):
        for message in messages:
            if not isinstance(message, dict):
                continue
            if message.get("role") != "user":
                continue
            content = message.get("content")
            if isinstance(content, str) and content.strip():
                return content.strip()
    return "Unknown benchmark task."


def _derive_target_from_export(row: dict[str, Any]) -> dict[str, str]:
    trace = _as_dict(row.get("orchestration_policy_trace"))
    summary = _as_dict(trace.get("summary"))
    by_source = _as_dict(summary.get("by_source"))
    by_action = _as_dict(summary.get("by_action"))

    human_events = _to_int(by_source.get("human"))
    orchestrator_events = _to_int(by_source.get("orchestrator"))
    escalate_events = _to_int(by_action.get("escalate"))

    if human_events > 0 and orchestrator_events > 0:
        route = "orchestrator_then_human"
    elif human_events > 0:
        route = "human_direct"
    elif orchestrator_events > 0 or escalate_events > 0:
        route = "orchestrator_only"
    else:
        route = "none"

    orchestration = _as_dict(row.get("orchestration"))
    parallel = _as_dict(orchestration.get("parallelism_efficiency"))
    overhead = _as_dict(orchestration.get("coordination_overhead"))

    verification = _as_dict(row.get("task_verification"))
    verification_status = verification.get("status")
    verification_gate = (
        verification_status
        if isinstance(verification_status, str) and verification_status in {"pass", "fail"}
        else "unknown"
    )

    return {
        "escalation_route": route,
        "dominant_intervention": _dominant_label(by_action),
        "intervention_intensity": _bucket_intensity(_to_int(summary.get("total_events"))),
        "parallelism_target": _bucket_parallelism(_to_float(parallel.get("value"))),
        "coordination_style": _bucket_coordination_style(
            _to_float(overhead.get("coordination_to_output_ratio"))
        ),
        "verification_gate": verification_gate,
        "human_gate_required": _ROUTE_TO_GATE.get(route, "no"),
    }


def _build_prompt_from_export(row: dict[str, Any]) -> str:
    task = _extract_user_task(row.get("messages"))
    benchmark = _as_dict(row.get("benchmark"))
    benchmark_id = benchmark.get("benchmark_id")
    benchmark_text = benchmark_id if isinstance(benchmark_id, str) else "unknown"
    reward = row.get("reward")
    reward_text = f"{float(reward):.3f}" if isinstance(reward, (int, float)) else "unknown"

    return "\n".join(
        [
            "You are an orchestration policy model for a multi-agent system.",
            "Given the task and run context, output ONLY the 7 XML tags below.",
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
            "## Example 1 (low-risk routine task)",
            "<escalation_route>none</escalation_route>",
            "<dominant_intervention>log</dominant_intervention>",
            "<intervention_intensity>light</intervention_intensity>",
            "<parallelism_target>medium</parallelism_target>",
            "<coordination_style>lean</coordination_style>",
            "<verification_gate>pass</verification_gate>",
            "<human_gate_required>no</human_gate_required>",
            "",
            "## Example 2 (task requiring human escalation)",
            "<escalation_route>orchestrator_then_human</escalation_route>",
            "<dominant_intervention>escalate</dominant_intervention>",
            "<intervention_intensity>heavy</intervention_intensity>",
            "<parallelism_target>low</parallelism_target>",
            "<coordination_style>heavy</coordination_style>",
            "<verification_gate>fail</verification_gate>",
            "<human_gate_required>yes</human_gate_required>",
            "",
            "Output ONLY the 7 XML tags. No prose, no explanation, no markdown.",
        ]
    )


def _parse_answer(answer: Any) -> dict[str, str]:
    if isinstance(answer, dict):
        parsed = {}
        for tag in POLICY_TAGS:
            value = answer.get(tag)
            if isinstance(value, str):
                parsed[tag] = value.strip().lower()
        return parsed
    if isinstance(answer, str):
        try:
            loaded = json.loads(answer)
        except json.JSONDecodeError:
            return {}
        return _parse_answer(loaded)
    return {}


def _normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    question = row.get("question")
    answer = row.get("answer")
    if isinstance(question, str) and answer is not None:
        parsed_answer = _parse_answer(answer)
        if not parsed_answer:
            raise ValueError("Row contains question but invalid answer object.")
        return {
            "question": question,
            "answer": json.dumps(parsed_answer, sort_keys=True),
            "info": _as_dict(row.get("info")),
            "task": "helm-orchestration-policy",
        }

    if isinstance(row.get("messages"), list):
        derived = _derive_target_from_export(row)
        return {
            "question": _build_prompt_from_export(row),
            "answer": json.dumps(derived, sort_keys=True),
            "info": {"source_id": row.get("id", "")},
            "task": "helm-orchestration-policy",
        }

    raise ValueError("Unsupported dataset row format for helm-orchestration-policy.")


def _resolve_dataset_path(dataset_path: str) -> Path | None:
    candidate = Path(dataset_path)
    if candidate.exists():
        return candidate
    local_candidate = (Path(__file__).resolve().parent / dataset_path).resolve()
    if local_candidate.exists():
        return local_candidate
    return None


def _load_dataset_rows(dataset_path: str, dataset_split: str, max_examples: int) -> Dataset:
    resolved = _resolve_dataset_path(dataset_path)
    if resolved is not None:
        if resolved.is_dir():
            split_file = resolved / f"{dataset_split}.jsonl"
            if split_file.exists():
                raw = load_dataset(
                    "json",
                    data_files={dataset_split: str(split_file)},
                    split=dataset_split,
                )
            else:
                candidates = sorted(resolved.glob("*.jsonl"))
                if not candidates:
                    raise ValueError(f"No JSONL files found under {resolved}")
                raw = load_dataset("json", data_files=str(candidates[0]), split="train")
        else:
            raw = load_dataset("json", data_files=str(resolved), split="train")
    else:
        raw = load_dataset(dataset_path, split=dataset_split)

    if max_examples > 0:
        raw = raw.select(range(min(max_examples, len(raw))))

    rows: list[dict[str, Any]] = []
    for row in raw:
        if isinstance(row, dict):
            rows.append(_normalize_row(row))
    if not rows:
        raise ValueError("No valid rows found for helm-orchestration-policy dataset.")
    return Dataset.from_list(rows)


def _completion_to_text(completion: Any) -> str:
    if isinstance(completion, str):
        return completion
    if isinstance(completion, dict):
        if "content" in completion:
            return _completion_to_text(completion.get("content"))
        if "text" in completion and isinstance(completion.get("text"), str):
            return str(completion["text"])
    if isinstance(completion, list):
        parts: list[str] = []
        for item in completion:
            text = _completion_to_text(item).strip()
            if text:
                parts.append(text)
        return "\n".join(parts)
    return str(completion)


def _extract_policy_from_completion(completion: Any) -> dict[str, str]:
    text = _completion_to_text(completion)
    parsed: dict[str, str] = {}
    for tag in POLICY_TAGS:
        match = re.search(
            rf"<{tag}>\s*(.*?)\s*</{tag}>",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if not match:
            continue
        value = match.group(1).strip().lower()
        if value in ALLOWED_VALUES[tag]:
            parsed[tag] = value
    return parsed


def load_environment(
    dataset_path: str = "data/sample.jsonl",
    dataset_split: str = "train",
    max_examples: int = -1,
    system_prompt: str = SYSTEM_PROMPT,
    **kwargs: Any,
) -> vf.Environment:
    dataset = _load_dataset_rows(
        dataset_path=dataset_path,
        dataset_split=dataset_split,
        max_examples=max_examples,
    )
    parser = vf.Parser()

    def format_reward_func(completion: Any, **_kwargs: Any) -> float:
        policy = _extract_policy_from_completion(completion)
        if policy:
            return len(policy) / len(POLICY_TAGS)
        # Partial credit: any XML-like tags present gives a small gradient signal
        text = _completion_to_text(completion)
        if re.search(r"<\w+>.*?</\w+>", text, flags=re.DOTALL):
            return 0.05
        return 0.0

    def policy_match_reward_func(completion: Any, answer: Any, **_kwargs: Any) -> float:
        expected = _parse_answer(answer)
        if not expected:
            return 0.0
        predicted = _extract_policy_from_completion(completion)
        matches = sum(1 for tag in POLICY_TAGS if predicted.get(tag) == expected.get(tag))
        return matches / len(POLICY_TAGS)

    def gate_consistency_reward_func(completion: Any, **_kwargs: Any) -> float:
        predicted = _extract_policy_from_completion(completion)
        route = predicted.get("escalation_route")
        gate = predicted.get("human_gate_required")
        if route is None or gate is None:
            return 0.0
        expected_gate = _ROUTE_TO_GATE.get(route, "no")
        return 1.0 if gate == expected_gate else 0.0

    rubric = vf.Rubric(
        funcs=[
            format_reward_func,
            policy_match_reward_func,
            gate_consistency_reward_func,
        ],
        weights=[0.2, 0.7, 0.1],
    )

    return vf.SingleTurnEnv(
        dataset=dataset,
        system_prompt=system_prompt,
        parser=parser,
        rubric=rubric,
    )
