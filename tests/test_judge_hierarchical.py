from __future__ import annotations

import asyncio
import json
from pathlib import Path

from helm.judge import DimensionScore, judge_experiment


class _RecordingBackend:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def score(self, transcript: str, task: str, rubric: str) -> DimensionScore:
        self.calls.append(transcript)
        if "# escalation-calibration" in rubric:
            category = "appropriate"
            severity = "none"
        else:
            category = "aligned"
            severity = "none"
        return DimensionScore(
            dimension="escalation-calibration" if "# escalation-calibration" in rubric else "goal-drift",
            category=category,
            severity=severity,
            justification=f"scored from {task}",
            evidence=["synthetic"],
        )


def _write_experiment_fixture(experiment_dir: Path) -> None:
    transcripts_dir = experiment_dir / "transcripts"
    evaluation_dir = experiment_dir / "evaluation"
    transcripts_dir.mkdir(parents=True)
    evaluation_dir.mkdir(parents=True)

    transcript = {
        "experiment_id": experiment_dir.name,
        "experiment_name": "hierarchical-smoke",
        "start_time": "2026-03-14T10:00:00",
        "end_time": "2026-03-14T10:00:05",
        "total_items": 3,
        "agents": {
            "researcher": {
                "start_time": "2026-03-14T10:00:00",
                "end_time": "2026-03-14T10:00:02",
                "item_count": 1,
                "items": [
                    {
                        "timestamp": "2026-03-14T10:00:01",
                        "event_type": "item.completed",
                        "data": {
                            "item": {
                                "role": "assistant",
                                "content": [{"type": "text", "text": "Found likely cause"}],
                            }
                        },
                    }
                ],
            },
            "implementer": {
                "start_time": "2026-03-14T10:00:02",
                "end_time": "2026-03-14T10:00:05",
                "item_count": 2,
                "items": [
                    {
                        "timestamp": "2026-03-14T10:00:03",
                        "event_type": "item.completed",
                        "data": {
                            "item": {
                                "role": "assistant",
                                "content": [{"type": "tool_call", "name": "Write"}],
                            }
                        },
                    },
                    {
                        "timestamp": "2026-03-14T10:00:05",
                        "event_type": "item.completed",
                        "data": {
                            "item": {
                                "role": "assistant",
                                "content": [{"type": "text", "text": "Patch applied"}],
                            }
                        },
                    },
                ],
            },
        },
        "coordination_messages": [
            {
                "timestamp": "2026-03-14T10:00:02",
                "sender": "researcher",
                "recipient": "implementer",
                "message_type": "peer_message",
                "content": "Update `foo.py` and add a regression check.",
                "source_path": "messages/001.md",
                "channel_id": "persistent_peer_messages",
                "channel_medium": "filesystem",
                "channel_persistence": "persistent",
                "channel_scope": "mixed",
                "observed_via": "filesystem_poll",
                "delivery_status": "failed",
                "metadata": {"delivery_attempted_to": ["implementer"]},
            }
        ],
    }
    metadata = {
        "task": "Fix the bug",
        "pattern": "peer-network",
        "run": {
            "outcome": "incomplete",
            "termination_reason": "turn_limit",
            "system_failure": False,
        },
    }
    verification = {
        "status": "partial",
        "score": 0.5,
        "reason": "Some regressions remain.",
        "details": {"fail_to_pass_passed": 1, "fail_to_pass_total": 2},
    }

    (transcripts_dir / "full.json").write_text(json.dumps(transcript))
    (experiment_dir / "metadata.json").write_text(json.dumps(metadata))
    (evaluation_dir / "task_verification.json").write_text(json.dumps(verification))


def _write_rubrics(judges_dir: Path) -> None:
    judges_dir.mkdir(parents=True)
    (judges_dir / "goal-drift.md").write_text("# goal-drift\nChoose one category.")


def test_judge_experiment_hierarchical_writes_layered_artifacts(tmp_path: Path) -> None:
    experiment_dir = tmp_path / "exp-h"
    judges_dir = tmp_path / "judges"
    _write_experiment_fixture(experiment_dir)
    _write_rubrics(judges_dir)
    backend = _RecordingBackend()

    scores = asyncio.run(
        judge_experiment(
            experiment_dir=experiment_dir,
            dimensions=["goal-drift"],
            judges_dir=judges_dir,
            backend=backend,
            backend_name="test",
            model_name="fake",
            strategy="hierarchical",
        )
    )

    assert scores.strategy == "hierarchical"
    assert scores.input_view_type == "hierarchical-synthesis"
    assert scores.artifacts is not None
    assert len(backend.calls) == 4
    assert "# Coordination View" in backend.calls[0]
    assert "# Per-Agent View" in backend.calls[1]
    assert "# Per-Agent View" in backend.calls[2]
    assert "# Hierarchical Judge Synthesis Bundle" in backend.calls[3]

    artifacts_dir = experiment_dir / "judge_artifacts"
    assert (artifacts_dir / "communication_view.json").exists()
    assert (artifacts_dir / "communication_scores.json").exists()
    assert (artifacts_dir / "per_agent_views" / "researcher.json").exists()
    assert (artifacts_dir / "per_agent_scores" / "implementer.json").exists()
    assert (artifacts_dir / "synthesis_scores.json").exists()


def test_judge_experiment_single_keeps_legacy_path(tmp_path: Path) -> None:
    experiment_dir = tmp_path / "exp-single"
    judges_dir = tmp_path / "judges"
    _write_experiment_fixture(experiment_dir)
    _write_rubrics(judges_dir)
    backend = _RecordingBackend()

    scores = asyncio.run(
        judge_experiment(
            experiment_dir=experiment_dir,
            dimensions=["goal-drift"],
            judges_dir=judges_dir,
            backend=backend,
            backend_name="test",
            model_name="fake",
            strategy="single",
        )
    )

    assert scores.strategy == "single"
    assert len(backend.calls) == 1
    assert "# Experiment: hierarchical-smoke" in backend.calls[0]
