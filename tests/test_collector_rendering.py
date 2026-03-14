from __future__ import annotations

import json

from helm.collector import render_transcript_markdown, summarize_coordination_messages
from helm.judge import load_transcript


def _sample_transcript() -> dict:
    return {
        "experiment_id": "exp-1",
        "experiment_name": "exp-1",
        "start_time": "2026-03-07T20:00:00",
        "end_time": "2026-03-07T20:00:05",
        "agents": {
            "researcher": {
                "start_time": "2026-03-07T20:00:00",
                "end_time": "2026-03-07T20:00:01",
                "item_count": 1,
                "items": [
                    {
                        "timestamp": "2026-03-07T20:00:00",
                        "session_id": "researcher",
                        "agent_id": "researcher",
                        "event_type": "session.started",
                        "data": {},
                    }
                ],
            },
            "implementer": {
                "start_time": "2026-03-07T20:00:02",
                "end_time": "2026-03-07T20:00:03",
                "item_count": 1,
                "items": [
                    {
                        "timestamp": "2026-03-07T20:00:03",
                        "session_id": "implementer",
                        "agent_id": "implementer",
                        "event_type": "item.completed",
                        "data": {"item": {"role": "assistant", "content": []}},
                    }
                ],
            }
        },
        "coordination_messages": [
            {
                "timestamp": "2026-03-07T20:00:02",
                "sender": "researcher",
                "recipient": "implementer",
                "message_type": "peer_message",
                "content": "Please apply the fix.",
                "source_path": "messages/001-researcher-implementer.md",
                "channel_id": "persistent_peer_messages",
                "channel_medium": "filesystem",
                "channel_persistence": "persistent",
                "channel_scope": "mixed",
                "observed_via": "filesystem_poll",
                "delivered": False,
                "delivery_status": "failed",
                "nudge_text": "[New coordination message]",
                "metadata": {
                    "delivery_attempted_to": ["implementer"],
                    "delivery_failures": {
                        "implementer": "follow_up_messages_unsupported"
                    },
                },
            }
        ],
    }


def test_summarize_coordination_messages_separates_artifacts_from_nudges() -> None:
    transcript = _sample_transcript()
    summary = summarize_coordination_messages(
        transcript["coordination_messages"],
        agents=transcript["agents"],
    )

    assert summary["observed_messages"] == 1
    assert summary["file_backed_messages"] == 1
    assert summary["nudge_attempts"] == 1
    assert summary["delivered"] == 0
    assert summary["nudge_delivery_rate"] == 0.0
    assert summary["delivery_rate"] == 0.0
    assert summary["by_channel"]["persistent_peer_messages"] == 1
    assert summary["by_medium"]["filesystem"] == 1
    assert summary["by_persistence"]["persistent"] == 1
    assert summary["by_delivery_status"]["failed"] == 1
    assert summary["recipient_activity_checks"] == 1
    assert summary["recipient_activity_hits"] == 1
    assert summary["recipient_activity_rate"] == 1.0


def test_render_transcript_markdown_clarifies_nudge_semantics() -> None:
    rendered = render_transcript_markdown(_sample_transcript())

    assert "**Observed Artifacts**: 1" in rendered
    assert "**Live Nudges Attempted**: 1" in rendered
    assert "**Live Nudges Delivered**: 0" in rendered
    assert "**Recipient Activity After Coordination**: 1/1" in rendered
    assert "filesystem artifacts observed by the backend" in rendered
    assert "Live delivery status: `failed`" in rendered
    assert "Channel: `persistent_peer_messages, filesystem, persistent, mixed`" in rendered
    assert "Content Preview:" in rendered
    assert "Please apply the fix." in rendered


def test_load_transcript_prefers_json_rendering(tmp_path) -> None:
    experiment_dir = tmp_path / "exp-1"
    transcripts_dir = experiment_dir / "transcripts"
    evaluation_dir = experiment_dir / "evaluation"
    transcripts_dir.mkdir(parents=True)
    evaluation_dir.mkdir(parents=True)

    with open(transcripts_dir / "full.json", "w") as f:
        json.dump(_sample_transcript(), f)
    with open(transcripts_dir / "full.md", "w") as f:
        f.write("STALE MARKDOWN")
    with open(experiment_dir / "metadata.json", "w") as f:
        json.dump(
            {
                "task": "sample task",
                "run": {
                    "outcome": "completed",
                    "termination_reason": "completion_signal",
                    "system_failure": False,
                },
            },
            f,
        )
    with open(evaluation_dir / "task_verification.json", "w") as f:
        json.dump(
            {
                "status": "partial",
                "score": 0.75,
                "reason": "3/4 FAIL_TO_PASS pass, 1 regression",
                "details": {
                    "fail_to_pass_passed": 3,
                    "fail_to_pass_total": 4,
                    "pass_to_pass_passed": 19,
                    "pass_to_pass_total": 20,
                    "warnings": ["Ignored agent edits to benchmark-owned test files"],
                },
            },
            f,
        )

    transcript, task = load_transcript(experiment_dir)

    assert task == "sample task"
    assert "STALE MARKDOWN" not in transcript
    assert "**Observed Artifacts**: 1" in transcript
    assert "**Recipient Activity After Coordination**: 1/1" in transcript
    assert "## Experiment Outcome" in transcript
    assert "- Outcome: `completed`" in transcript
    assert "## Benchmark Verification" in transcript
    assert "- Status: `partial`" in transcript
    assert "- PASS_TO_PASS: `19/20` (regressions: `1`)" in transcript
    assert "Ignored agent edits to benchmark-owned test files" in transcript


def test_load_transcript_truncates_large_judge_prompt(tmp_path) -> None:
    experiment_dir = tmp_path / "exp-large"
    transcripts_dir = experiment_dir / "transcripts"
    transcripts_dir.mkdir(parents=True)

    transcript = _sample_transcript()
    long_text = "x" * 5000
    items = []
    for idx in range(80):
        items.append(
            {
                "timestamp": f"2026-03-07T20:00:{idx % 60:02d}",
                "session_id": "implementer",
                "agent_id": "implementer",
                "event_type": "item.completed",
                "data": {
                    "item": {
                        "role": "assistant",
                        "content": [{"type": "text", "text": f"{idx}:{long_text}"}],
                    }
                },
            }
        )
    transcript["agents"]["implementer"]["items"] = items
    transcript["agents"]["implementer"]["item_count"] = len(items)

    with open(transcripts_dir / "full.json", "w") as f:
        json.dump(transcript, f)
    with open(experiment_dir / "metadata.json", "w") as f:
        json.dump({"task": "large task"}, f)

    rendered, task = load_transcript(experiment_dir)

    assert task == "large task"
    assert "[... judge transcript truncated for budget:" in rendered
    assert len(rendered) < 120_000
