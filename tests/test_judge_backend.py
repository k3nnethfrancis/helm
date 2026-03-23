from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx

from helm.judge import (
    ClaudeHeadlessJudge,
    CodexHeadlessJudge,
    DimensionScore,
    ExperimentScores,
    OpenRouterJudge,
    _parse_judge_response,
)


def test_experiment_scores_to_dict_includes_artifacts() -> None:
    payload = ExperimentScores(
        experiment_id="exp-1",
        scores=[
            DimensionScore(
                dimension="goal-drift",
                category="aligned",
                severity="none",
                justification="ok",
                evidence=[],
            )
        ],
        judge_backend="openrouter",
        judge_model="fake-model",
        judge_role="audit",
        strategy="hierarchical",
        preparation_path="hierarchical-synthesis",
        artifacts={"communication_view": {"json": "judge_artifacts/communication_view.json"}},
        audit={"deterministic_preprocessing": True},
    ).to_dict()

    assert payload["artifacts"]["communication_view"]["json"] == (
        "judge_artifacts/communication_view.json"
    )
    assert payload["judge_role"] == "audit"
    assert payload["preparation_path"] == "hierarchical-synthesis"
    assert payload["audit"]["deterministic_preprocessing"] is True


def test_openrouter_judge_retries_parse_failure(monkeypatch) -> None:
    responses = [
        {"choices": [{"message": {"content": ""}}]},
        {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "dimension": "goal-drift",
                                "category": "aligned",
                                "justification": "Recovered on retry.",
                                "evidence": ["08:09:54"],
                            }
                        )
                    }
                }
            ]
        },
    ]
    posted_payloads: list[dict] = []

    class _FakeResponse:
        def __init__(self, payload: dict) -> None:
            self.status_code = 200
            self._payload = payload
            self.text = json.dumps(payload)
            self.request = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")

        def json(self) -> dict:
            return self._payload

    class _FakeAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self) -> _FakeAsyncClient:
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

        async def post(self, url: str, headers: dict, json: dict) -> _FakeResponse:
            posted_payloads.append(json)
            return _FakeResponse(responses[len(posted_payloads) - 1])

    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)

    judge = OpenRouterJudge(model="fake-model", api_key="test-key")
    score = asyncio.run(
        judge.score(
            transcript="Transcript",
            task="Task",
            rubric="# goal-drift\nChoose one category.",
        )
    )

    assert score.category == "aligned"
    assert len(posted_payloads) == 2


def test_claude_headless_judge_uses_configured_model(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class _DummyProcess:
        returncode = 0

        async def communicate(self):
            return (
                json.dumps(
                    {
                        "dimension": "goal-drift",
                        "category": "aligned",
                        "justification": "ok",
                        "evidence": [],
                    }
                ).encode(),
                b"",
            )

        def kill(self) -> None:
            return None

    async def _fake_create_subprocess_exec(*args, **kwargs):
        captured["cmd"] = list(args)
        return _DummyProcess()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_create_subprocess_exec)

    judge = ClaudeHeadlessJudge(model="claude-sonnet-4-5")
    score = asyncio.run(
        judge.score("Transcript", "Task", "# goal-drift\nChoose one category.")
    )

    assert score.category == "aligned"
    assert "--model" in captured["cmd"]
    assert "claude-sonnet-4-5" in captured["cmd"]


def test_codex_headless_judge_uses_output_last_message(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}
    temp_root = tmp_path / "tmp"
    temp_root.mkdir(parents=True)

    class _DummyProcess:
        returncode = 0

        async def communicate(self):
            output_path = Path(captured["output_path"])
            output_path.write_text(
                json.dumps(
                    {
                        "dimension": "goal-drift",
                        "category": "aligned",
                        "justification": "ok",
                        "evidence": [],
                    }
                )
            )
            return (b"", b"")

        def kill(self) -> None:
            return None

    class _FakeTemporaryDirectory:
        def __init__(self, *args, **kwargs) -> None:
            self.path = temp_root

        def __enter__(self) -> str:
            return str(self.path)

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

    async def _fake_create_subprocess_exec(*args, **kwargs):
        captured["cmd"] = list(args)
        output_index = captured["cmd"].index("--output-last-message") + 1
        captured["output_path"] = captured["cmd"][output_index]
        return _DummyProcess()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_create_subprocess_exec)
    monkeypatch.setattr("helm.judge.backends.tempfile.TemporaryDirectory", _FakeTemporaryDirectory)

    judge = CodexHeadlessJudge(model="gpt-5.4")
    score = asyncio.run(
        judge.score("Transcript", "Task", "# goal-drift\nChoose one category.")
    )

    assert score.category == "aligned"
    assert "--output-last-message" in captured["cmd"]
    assert "--model" in captured["cmd"]
    assert "gpt-5.4" in captured["cmd"]


def test_parse_human_model_accuracy_category() -> None:
    score = _parse_judge_response(
        json.dumps(
            {
                "dimension": "human-model-accuracy",
                "category": "minor-gaps",
                "justification": "Mostly understood the request.",
                "evidence": ["agent-1 inferred a missing requirement"],
            }
        ),
        "human-model-accuracy",
    )

    assert score.category == "minor-gaps"
    assert score.severity == "minor"


def test_openrouter_judge_retries_timeout(monkeypatch) -> None:
    posted_payloads: list[dict] = []

    class _FakeResponse:
        def __init__(self, payload: dict) -> None:
            self.status_code = 200
            self._payload = payload
            self.text = json.dumps(payload)
            self.request = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")

        def json(self) -> dict:
            return self._payload

    class _FakeAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self) -> _FakeAsyncClient:
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

        async def post(self, url: str, headers: dict, json: dict) -> _FakeResponse:
            posted_payloads.append(json)
            if len(posted_payloads) == 1:
                request = httpx.Request("POST", url)
                raise httpx.ReadTimeout("timed out", request=request)
            return _FakeResponse(
                {
                    "choices": [
                        {
                            "message": {
                                "content": json_module.dumps(
                                    {
                                        "dimension": "goal-drift",
                                        "category": "aligned",
                                        "justification": "Recovered after timeout retry.",
                                        "evidence": ["08:09:54"],
                                    }
                                )
                            }
                        }
                    ]
                }
            )

    json_module = json
    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)

    judge = OpenRouterJudge(model="fake-model", api_key="test-key")
    score = asyncio.run(
        judge.score(
            transcript="Transcript",
            task="Task",
            rubric="# goal-drift\nChoose one category.",
        )
    )

    assert score.category == "aligned"
    assert len(posted_payloads) == 2
