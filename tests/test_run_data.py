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
        "benchmark": {
            "adapter": "swebench",
            "id": "princeton-nlp/SWE-bench_Verified",
            "dataset_path": "/tmp/swebench-mini.jsonl",
            "split": "verified",
            "seed": 13,
            "verifier": {"mode": "completion"},
            "example_id": "swe-1",
            "example_ids": ["swe-1"],
        },
        "agents": [{"id": "a"}, {"id": "b"}],
        "limits": {"blocked_commands": ["rm -rf", "sudo"]},
        "run": {
            "success": True,
            "duration_seconds": 3.0,
            "benchmark": {
                "adapter": "swebench",
                "benchmark_id": "princeton-nlp/SWE-bench_Verified",
                "split": "verified",
                "seed": 13,
                "verifier_mode": "completion",
                "selected_example_id": "swe-1",
                "configured_example_ids": ["swe-1"],
            },
            "escalations": [
                {
                    "timestamp": "2026-02-11T10:00:01.150000",
                    "agent_id": "a",
                    "event_type": "permission.requested",
                    "reason": "Network action requires human review",
                    "event_data": {
                        "permission_id": "p1",
                        "action": "curl https://example.com",
                    }
                }
            ],
            "interventions": [
                {
                    "timestamp": "2026-02-11T10:00:01.100000",
                    "agent_id": "a",
                    "action_taken": "escalate",
                    "event_type": "permission.requested",
                    "event_data": {
                        "permission_id": "p1",
                        "action": "curl https://example.com",
                    },
                    "rule": {
                        "on": "permission.requested",
                        "then": "escalate",
                    },
                    "details": {"escalated": True},
                },
                {
                    "timestamp": "2026-02-11T10:00:01.200000",
                    "agent_id": "a",
                    "action_taken": "log",
                    "event_type": "permission.requested",
                    "event_data": {
                        "permission_id": "p2",
                        "action": "ls -la",
                    },
                    "rule": {
                        "on": "permission.requested",
                        "then": "log",
                    },
                    "details": {"logged_only": True},
                },
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

    intervention_profile = metrics["intervention_profile"]
    assert intervention_profile["total_interventions"] == 2
    assert intervention_profile["by_action"]["escalate"] == 1
    assert intervention_profile["by_action"]["log"] == 1
    assert intervention_profile["by_event_type"]["permission.requested"] == 2
    assert intervention_profile["by_agent"]["a"] == 2


def test_save_run_data_includes_judge_scores(tmp_path) -> None:
    experiment_dir = tmp_path / "exp-1"
    transcripts_dir = experiment_dir / "transcripts"
    eval_dir = experiment_dir / "evaluation"
    transcripts_dir.mkdir(parents=True)
    eval_dir.mkdir(parents=True)
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
    with open(eval_dir / "task_verification.json", "w") as f:
        json.dump(
            {
                "status": "pass",
                "score": 1.0,
                "reason": "All benchmark assertions passed",
                "details": {"suite": "smoke"},
            },
            f,
        )

    out_path = save_run_data(experiment_dir)
    payload = json.loads(out_path.read_text())

    assert out_path.name == "run_data.json"
    assert payload["schema_version"] == "helm.run_data.v1"
    assert payload["experiment"]["id"] == "exp-1"
    assert payload["evals"]["judge"]["scores"]["goal-drift"] == 7
    assert payload["transcript"]["total_events"] == 12
    assert payload["run"]["interventions"][0]["action_taken"] == "escalate"
    policy_trace = payload["run"]["orchestration_policy_trace"]
    assert policy_trace["summary"]["total_events"] == 3
    assert policy_trace["summary"]["by_action"]["escalate"] == 1
    assert policy_trace["summary"]["by_action"]["log"] == 1
    assert policy_trace["summary"]["by_action"]["escalate_to_human"] == 1
    assert policy_trace["summary"]["by_action_family"]["escalate"] == 2
    assert policy_trace["summary"]["by_source"]["runtime_guard"] == 2
    assert policy_trace["summary"]["by_source"]["experiment_escalation"] == 1
    assert policy_trace["events"][0]["action"] == "escalate"
    assert policy_trace["events"][1]["action"] == "escalate_to_human"
    assert policy_trace["events"][2]["action"] == "log"
    assert payload["evals"]["orchestration"]["intervention_profile"]["total_interventions"] == 2
    assert payload["provenance"]["benchmark"]["benchmark_id"] == "princeton-nlp/SWE-bench_Verified"
    assert payload["provenance"]["benchmark"]["example_id"] == "swe-1"
    assert payload["provenance"]["benchmark"]["seed"] == 13
    assert payload["provenance"]["benchmark"]["verifier_mode"] == "completion"
    assert payload["run"]["benchmark"]["selected_example_id"] == "swe-1"
    assert payload["run"]["task_verification"]["status"] == "pass"
    assert payload["run"]["task_verification"]["score"] == 1.0
    assert payload["artifacts"]["task_verification"] == "evaluation/task_verification.json"

    rebuilt = build_run_data(experiment_dir)
    assert rebuilt["experiment"]["id"] == "exp-1"


def test_run_data_v2_categorical_scores(tmp_path) -> None:
    """Verify v2 categorical judge scores are ingested correctly."""
    experiment_dir = tmp_path / "exp-cat"
    transcripts_dir = experiment_dir / "transcripts"
    transcripts_dir.mkdir(parents=True)
    (experiment_dir / "workspace").mkdir(parents=True)

    metadata = {
        "experiment_id": "exp-cat",
        "experiment_name": "exp-cat",
        "pattern": "hub-and-spoke",
        "created_at": "2026-02-28T12:00:00",
        "task": "categorical test",
        "agents": [{"id": "a"}],
        "limits": {},
        "run": {"success": True, "duration_seconds": 1.0},
    }
    transcript = {
        "start_time": "2026-02-28T12:00:00",
        "end_time": "2026-02-28T12:00:01",
        "total_items": 1,
        "agents": {"a": {"item_count": 1, "items": []}},
    }
    scores_v2 = {
        "schema_version": "v2",
        "experiment_id": "exp-cat",
        "judge_backend": "openrouter",
        "judge_model": "google/gemini-2.0-flash-001",
        "scores": [
            {
                "dimension": "goal-drift",
                "category": "minor-drift",
                "severity": "minor",
                "justification": "Small scope additions",
                "evidence": ["agent-a: added unrequested feature"],
            },
            {
                "dimension": "failure-suppression",
                "category": "transparent",
                "severity": "none",
                "justification": "All errors reported",
                "evidence": [],
            },
        ],
    }

    with open(experiment_dir / "metadata.json", "w") as f:
        json.dump(metadata, f)
    with open(transcripts_dir / "full.json", "w") as f:
        json.dump(transcript, f)
    with open(experiment_dir / "scores.json", "w") as f:
        json.dump(scores_v2, f)

    payload = build_run_data(experiment_dir)

    judge = payload["evals"]["judge"]
    assert judge is not None
    assert judge["schema_version"] == "v2"

    gd = judge["scores"]["goal-drift"]
    assert gd["category"] == "minor-drift"
    assert gd["severity"] == "minor"

    fs = judge["scores"]["failure-suppression"]
    assert fs["category"] == "transparent"
    assert fs["severity"] == "none"


def test_run_data_v1_numeric_scores_backward_compat(tmp_path) -> None:
    """Verify old v1 numeric scores still work."""
    experiment_dir = tmp_path / "exp-v1"
    transcripts_dir = experiment_dir / "transcripts"
    transcripts_dir.mkdir(parents=True)
    (experiment_dir / "workspace").mkdir(parents=True)

    metadata = {
        "experiment_id": "exp-v1",
        "experiment_name": "exp-v1",
        "pattern": "peer-network",
        "created_at": "2026-02-20T10:00:00",
        "task": "v1 compat test",
        "agents": [{"id": "a"}],
        "limits": {},
        "run": {"success": True, "duration_seconds": 1.0},
    }
    transcript = {
        "start_time": "2026-02-20T10:00:00",
        "end_time": "2026-02-20T10:00:01",
        "total_items": 1,
        "agents": {"a": {"item_count": 1, "items": []}},
    }
    scores_v1 = {
        "experiment_id": "exp-v1",
        "judge_backend": "sdk",
        "judge_model": None,
        "scores": [
            {
                "dimension": "goal-drift",
                "score": 7,
                "justification": "mostly aligned",
                "evidence": [],
            },
        ],
    }

    with open(experiment_dir / "metadata.json", "w") as f:
        json.dump(metadata, f)
    with open(transcripts_dir / "full.json", "w") as f:
        json.dump(transcript, f)
    with open(experiment_dir / "scores.json", "w") as f:
        json.dump(scores_v1, f)

    payload = build_run_data(experiment_dir)

    judge = payload["evals"]["judge"]
    assert judge is not None
    assert judge["schema_version"] == "v1"
    assert judge["scores"]["goal-drift"] == 7
