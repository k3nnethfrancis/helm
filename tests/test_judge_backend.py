from __future__ import annotations

import asyncio
import json

import httpx

from helm.judge import (
    DimensionScore,
    ExperimentScores,
    OpenRouterJudge,
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
        strategy="hierarchical",
        artifacts={"communication_view": {"json": "judge_artifacts/communication_view.json"}},
        audit={"deterministic_preprocessing": True},
    ).to_dict()

    assert payload["artifacts"]["communication_view"]["json"] == (
        "judge_artifacts/communication_view.json"
    )
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
    assert "IMPORTANT RETRY INSTRUCTION" in posted_payloads[1]["messages"][1]["content"]


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
