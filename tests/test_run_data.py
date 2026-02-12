from __future__ import annotations

import json

from helm.run_data import build_run_data, compute_orchestration_evals, save_run_data


def _sample_transcript() -> dict:
    return {
        "start_time": "2026-02-11T10:00:00",
        "end_time": "2026-02-11T10:00:03",
        "total_items": 12,
        "agents": {
            "a": {
                "item_count": 6,
                "items": [
                    {
                        "timestamp": "2026-02-11T10:00:00",
                        "event_type": "item.started",
                        "data": {"item": {"item_id": "a1", "role": "assistant"}},
                    },
                    {
                        "timestamp": "2026-02-11T10:00:02",
                        "event_type": "item.completed",
                        "data": {"item": {"item_id": "a1", "role": "assistant"}},
                    },
                    {
                        "timestamp": "2026-02-11T10:00:01",
                        "event_type": "permission.requested",
                        "data": {"permission_id": "p1", "action": "curl https://example.com"},
                    },
                    {
                        "timestamp": "2026-02-11T10:00:01.200000",
                        "event_type": "permission.requested",
                        "data": {"permission_id": "p2", "action": "ls -la"},
                    },
                ],
            },
            "b": {
                "item_count": 6,
                "items": [
                    {
                        "timestamp": "2026-02-11T10:00:00.500000",
                        "event_type": "item.started",
                        "data": {"item": {"item_id": "b1", "role": "assistant"}},
                    },
                    {
                        "timestamp": "2026-02-11T10:00:01.500000",
                        "event_type": "item.completed",
                        "data": {"item": {"item_id": "b1", "role": "assistant"}},
                    },
                ],
            },
        },
        "coordination_summary": {
            "total_messages": 2,
            "delivered": 2,
            "delivery_rate": 1.0,
            "by_type": {"peer_message": 2},
        },
        "coordination_messages": [
            {"source_path": "messages/001-a-b.md"},
            {"source_path": "messages/002-b-a.md"},
        ],
    }


def _sample_metadata() -> dict:
    return {
        "experiment_id": "exp-1",
        "experiment_name": "exp-1",
        "pattern": "peer-network",
        "created_at": "2026-02-11T10:00:00",
        "task": "sample task",
        "agents": [{"id": "a"}, {"id": "b"}],
        "limits": {"blocked_commands": ["rm -rf", "sudo"]},
        "run": {
            "success": True,
            "duration_seconds": 3.0,
            "escalations": [
                {
                    "event_data": {
                        "permission_id": "p1",
                        "action": "curl https://example.com",
                    }
                }
            ],
            "agent_stats": {"a": {"turns": 1}, "b": {"turns": 1}},
        },
    }


def test_compute_orchestration_evals(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True)
    (workspace / "artifact.txt").write_text("ok")

    metrics = compute_orchestration_evals(
        transcript=_sample_transcript(),
        metadata=_sample_metadata(),
        experiment_dir=tmp_path,
    )

    parallel = metrics["parallelism_efficiency"]
    assert parallel["assistant_steps"] == 2
    assert parallel["value"] is not None
    assert 0.3 < parallel["value"] < 0.35  # 1 - (2/3)

    overhead = metrics["coordination_overhead"]
    assert overhead["coordination_messages"] == 2
    assert overhead["workspace_artifacts"] == 1
    assert overhead["messages_per_assistant_step"] == 1.0

    escalation = metrics["escalation_precision_recall"]
    assert escalation["permission_requests"] == 2
    assert escalation["risky_permission_requests"] == 1
    assert escalation["escalations"] == 1
    assert escalation["precision"] == 1.0
    assert escalation["recall"] == 1.0


def test_save_run_data_includes_judge_scores(tmp_path) -> None:
    experiment_dir = tmp_path / "exp-1"
    transcripts_dir = experiment_dir / "transcripts"
    transcripts_dir.mkdir(parents=True)
    (experiment_dir / "workspace").mkdir(parents=True)
    (experiment_dir / "workspace" / "artifact.txt").write_text("ok")

    metadata = _sample_metadata()
    transcript = _sample_transcript()
    scores = {
        "experiment_id": "exp-1",
        "judge_backend": "sdk",
        "judge_model": None,
        "scores": [
            {
                "dimension": "goal-drift",
                "score": 7,
                "justification": "ok",
                "evidence": [],
            }
        ],
    }

    with open(experiment_dir / "metadata.json", "w") as f:
        json.dump(metadata, f)
    with open(transcripts_dir / "full.json", "w") as f:
        json.dump(transcript, f)
    with open(transcripts_dir / "full.md", "w") as f:
        f.write("# transcript")
    with open(experiment_dir / "scores.json", "w") as f:
        json.dump(scores, f)

    out_path = save_run_data(experiment_dir)
    payload = json.loads(out_path.read_text())

    assert out_path.name == "run_data.json"
    assert payload["schema_version"] == "helm.run_data.v1"
    assert payload["experiment"]["id"] == "exp-1"
    assert payload["evals"]["judge"]["scores"]["goal-drift"] == 7
    assert payload["transcript"]["total_events"] == 12

    rebuilt = build_run_data(experiment_dir)
    assert rebuilt["experiment"]["id"] == "exp-1"
