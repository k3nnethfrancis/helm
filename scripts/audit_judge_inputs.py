#!/usr/bin/env python3
"""Audit the judge input surface on a panel of saved Helm experiments."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from helm.collector import (
    TRANSCRIPT_COORDINATION_PREVIEW_CHARS,
    TRANSCRIPT_TEXT_PREVIEW_CHARS,
    TRANSCRIPT_TOOL_RESULT_PREVIEW_CHARS,
    render_transcript_markdown,
)
from helm.judge import _render_verifier_context, load_transcript


@dataclass
class ClipExample:
    kind: str
    agent_id: str
    timestamp: str
    original_length: int


@dataclass
class ExperimentAudit:
    experiment_id: str
    experiment_name: str
    pattern: str | None
    task: str
    task_length: int
    agent_count: int
    total_items: int
    coordination_message_count: int
    outcome: str | None
    termination_reason: str | None
    system_failure: bool | None
    verification_status: str | None
    verification_score: float | int | None
    rendered_transcript_length: int
    verifier_context_length: int
    combined_judge_input_length: int
    actual_judge_input_length: int
    uses_long_run_digest: bool
    globally_truncated: bool
    omitted_chars: int
    text_parts_clipped: int
    tool_results_clipped: int
    coordination_previews_clipped: int
    clip_examples: list[ClipExample]


def _parse_args() -> argparse.Namespace:
    repo_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "experiment_dirs",
        nargs="+",
        type=Path,
        help="Absolute experiment directories to audit",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Directory to write audit artifacts",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=repo_root,
        help="Helm repo root (default: inferred from script path)",
    )
    return parser.parse_args()


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def _verification_summary(experiment_dir: Path) -> tuple[str | None, float | int | None]:
    verification_path = experiment_dir / "evaluation" / "task_verification.json"
    if not verification_path.exists():
        return None, None
    verification = _load_json(verification_path)
    return verification.get("status"), verification.get("score")


def _collect_clip_examples(transcript: dict[str, Any]) -> tuple[int, int, int, list[ClipExample]]:
    text_parts_clipped = 0
    tool_results_clipped = 0
    examples: list[ClipExample] = []

    agents = transcript.get("agents", {})
    if isinstance(agents, dict):
        for agent_id, agent_data in agents.items():
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
                for part in item_data.get("content", []):
                    if not isinstance(part, dict):
                        continue
                    timestamp = str(item.get("timestamp", ""))
                    if part.get("type") == "text":
                        text = str(part.get("text", ""))
                        if len(text) > TRANSCRIPT_TEXT_PREVIEW_CHARS:
                            text_parts_clipped += 1
                            if len(examples) < 10:
                                examples.append(
                                    ClipExample(
                                        kind="text",
                                        agent_id=str(agent_id),
                                        timestamp=timestamp,
                                        original_length=len(text),
                                    )
                                )
                    elif part.get("type") == "tool_result":
                        output = str(part.get("output", part.get("text", "")))
                        if len(output) > TRANSCRIPT_TOOL_RESULT_PREVIEW_CHARS:
                            tool_results_clipped += 1
                            if len(examples) < 10:
                                examples.append(
                                    ClipExample(
                                        kind="tool_result",
                                        agent_id=str(agent_id),
                                        timestamp=timestamp,
                                        original_length=len(output),
                                    )
                                )

    coordination_previews_clipped = 0
    coordination_messages = transcript.get("coordination_messages", [])
    if isinstance(coordination_messages, list):
        for message in coordination_messages:
            if not isinstance(message, dict):
                continue
            content = message.get("content")
            if (
                isinstance(content, str)
                and len(content.strip()) > TRANSCRIPT_COORDINATION_PREVIEW_CHARS
            ):
                coordination_previews_clipped += 1
                if len(examples) < 10:
                    examples.append(
                        ClipExample(
                            kind="coordination_preview",
                            agent_id=str(message.get("sender") or "?"),
                            timestamp=str(message.get("timestamp", "")),
                            original_length=len(content.strip()),
                        )
                    )

    return text_parts_clipped, tool_results_clipped, coordination_previews_clipped, examples


def _omitted_chars(full_text: str, truncated_text: str) -> int:
    if len(full_text) <= len(truncated_text):
        return 0
    marker = "[... judge transcript truncated for budget:"
    if marker not in truncated_text:
        return len(full_text) - len(truncated_text)
    try:
        remainder = truncated_text.split(marker, 1)[1]
        omitted_text = remainder.split("chars omitted", 1)[0].strip()
        return int(omitted_text)
    except (IndexError, ValueError):
        return len(full_text) - len(truncated_text)


def _audit_experiment(experiment_dir: Path) -> tuple[ExperimentAudit, str, str]:
    metadata = _load_json(experiment_dir / "metadata.json")
    transcript_json = _load_json(experiment_dir / "transcripts" / "full.json")

    rendered_transcript = render_transcript_markdown(transcript_json)
    verifier_context = _render_verifier_context(experiment_dir, metadata)
    combined = rendered_transcript if not verifier_context else f"{rendered_transcript}\n\n{verifier_context}"
    judge_input, _ = load_transcript(experiment_dir)

    run = metadata.get("run", {})
    if not isinstance(run, dict):
        run = {}

    verification_status, verification_score = _verification_summary(experiment_dir)
    text_parts_clipped, tool_results_clipped, coordination_previews_clipped, examples = (
        _collect_clip_examples(transcript_json)
    )

    agents = transcript_json.get("agents", {})
    agent_count = len(agents) if isinstance(agents, dict) else 0
    coordination_messages = transcript_json.get("coordination_messages", [])
    coordination_message_count = (
        len(coordination_messages) if isinstance(coordination_messages, list) else 0
    )

    audit = ExperimentAudit(
        experiment_id=experiment_dir.name,
        experiment_name=str(metadata.get("experiment_name", transcript_json.get("experiment_name", ""))),
        pattern=metadata.get("pattern"),
        task=str(metadata.get("task", "")),
        task_length=len(str(metadata.get("task", ""))),
        agent_count=agent_count,
        total_items=int(transcript_json.get("total_items", 0)),
        coordination_message_count=coordination_message_count,
        outcome=run.get("outcome"),
        termination_reason=run.get("termination_reason"),
        system_failure=run.get("system_failure"),
        verification_status=verification_status,
        verification_score=verification_score,
        rendered_transcript_length=len(rendered_transcript),
        verifier_context_length=len(verifier_context),
        combined_judge_input_length=len(combined),
        actual_judge_input_length=len(judge_input),
        uses_long_run_digest="## Long-Run Digest" in judge_input,
        globally_truncated=len(judge_input) < len(combined),
        omitted_chars=_omitted_chars(combined, judge_input),
        text_parts_clipped=text_parts_clipped,
        tool_results_clipped=tool_results_clipped,
        coordination_previews_clipped=coordination_previews_clipped,
        clip_examples=examples,
    )
    return audit, rendered_transcript, judge_input


def _write_experiment_artifacts(
    experiment_dir: Path,
    output_dir: Path,
    audit: ExperimentAudit,
    rendered_transcript: str,
    judge_input: str,
) -> None:
    experiment_output_dir = output_dir / experiment_dir.name
    experiment_output_dir.mkdir(parents=True, exist_ok=True)
    (experiment_output_dir / "summary.json").write_text(
        json.dumps(
            {
                **asdict(audit),
                "clip_examples": [asdict(example) for example in audit.clip_examples],
            },
            indent=2,
        )
    )
    (experiment_output_dir / "rendered-transcript.md").write_text(rendered_transcript)
    (experiment_output_dir / "judge-input.md").write_text(judge_input)


def _write_report(audits: list[ExperimentAudit], output_dir: Path) -> None:
    lines = [
        "# Judge Input Audit",
        "",
        "| Experiment | Outcome | Verifier | Agents | Items | Coord Msgs | Combined Chars | Judge Chars | Digest | Truncated | Omitted | Text Clips | Tool Clips | Coord Clips |",
        "|---|---|---:|---:|---:|---:|---:|---:|---|---|---:|---:|---:|---:|",
    ]

    for audit in audits:
        verifier = audit.verification_status or "n/a"
        if audit.verification_score is not None:
            verifier = f"{verifier} ({audit.verification_score})"
        outcome = audit.outcome or "unknown"
        if audit.termination_reason:
            outcome = f"{outcome}/{audit.termination_reason}"
        lines.append(
            f"| `{audit.experiment_id}` | `{outcome}` | `{verifier}` | "
            f"{audit.agent_count} | {audit.total_items} | {audit.coordination_message_count} | "
            f"{audit.combined_judge_input_length} | {audit.actual_judge_input_length} | "
            f"{'yes' if audit.uses_long_run_digest else 'no'} | "
            f"{'yes' if audit.globally_truncated else 'no'} | {audit.omitted_chars} | "
            f"{audit.text_parts_clipped} | {audit.tool_results_clipped} | "
            f"{audit.coordination_previews_clipped} |"
        )

    lines.extend(["", "## Potential Blind Spots", ""])
    for audit in audits:
        warnings: list[str] = []
        if audit.globally_truncated:
            warnings.append(
                f"global truncation removed {audit.omitted_chars} chars from the middle"
            )
        if audit.uses_long_run_digest:
            warnings.append("judge input now uses the deterministic long-run digest path")
        if audit.text_parts_clipped:
            warnings.append(
                f"{audit.text_parts_clipped} assistant text blocks exceeded "
                f"{TRANSCRIPT_TEXT_PREVIEW_CHARS} chars"
            )
        if audit.tool_results_clipped:
            warnings.append(
                f"{audit.tool_results_clipped} tool results exceeded "
                f"{TRANSCRIPT_TOOL_RESULT_PREVIEW_CHARS} chars"
            )
        if audit.coordination_previews_clipped:
            warnings.append(
                f"{audit.coordination_previews_clipped} coordination artifacts exceeded "
                f"{TRANSCRIPT_COORDINATION_PREVIEW_CHARS} chars"
            )
        if audit.task_length == 0:
            warnings.append("task description missing from metadata")
        if not warnings:
            warnings.append("no obvious clipping or truncation flags")
        lines.append(f"- `{audit.experiment_id}`: " + "; ".join(warnings))

    (output_dir / "summary.json").write_text(
        json.dumps(
            {
                "experiments": [
                    {
                        **asdict(audit),
                        "clip_examples": [asdict(example) for example in audit.clip_examples],
                    }
                    for audit in audits
                ]
            },
            indent=2,
        )
    )
    (output_dir / "report.md").write_text("\n".join(lines) + "\n")


def main() -> None:
    args = _parse_args()
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    audits: list[ExperimentAudit] = []
    for experiment_dir in args.experiment_dirs:
        audit, rendered_transcript, judge_input = _audit_experiment(experiment_dir)
        audits.append(audit)
        _write_experiment_artifacts(
            experiment_dir,
            output_dir,
            audit,
            rendered_transcript,
            judge_input,
        )

    _write_report(audits, output_dir)


if __name__ == "__main__":
    main()
