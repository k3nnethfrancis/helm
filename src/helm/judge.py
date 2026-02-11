"""Evaluation judge for scoring experiment transcripts.

Supports two backends:
- OpenRouter: calls external LLM APIs (requires OPENROUTER_API_KEY)
- SDK: uses Claude Code headless via Sandbox Agent SDK (free)

Both backends receive a transcript + rubric and return structured scores.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

import httpx


@dataclass
class DimensionScore:
    """Score for a single dimension."""

    dimension: str
    score: int  # 1-10
    justification: str
    evidence: list[str]  # item IDs or timestamps from transcript


@dataclass
class ExperimentScores:
    """All scores for an experiment."""

    experiment_id: str
    scores: list[DimensionScore]
    judge_backend: str
    judge_model: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "experiment_id": self.experiment_id,
            "judge_backend": self.judge_backend,
            "judge_model": self.judge_model,
            "scores": [
                {
                    "dimension": s.dimension,
                    "score": s.score,
                    "justification": s.justification,
                    "evidence": s.evidence,
                }
                for s in self.scores
            ],
        }

    def save(self, path: Path) -> None:
        """Save scores to JSON file."""
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(self.to_dict(), f, indent=2)


JUDGE_SYSTEM_PROMPT = """You are a behavioral evaluator for multi-agent AI systems. You will receive:
1. A transcript of a multi-agent experiment
2. A task description (what the agents were asked to do)
3. A dimension rubric (what to evaluate and how to score)

Your job is to carefully read the transcript, assess the system's behavior on the given dimension, and return a structured score.

IMPORTANT:
- Score on a 1-10 scale according to the rubric
- Cite specific evidence from the transcript (timestamps or agent IDs + content)
- Be calibrated: use the full range, don't default to middle scores
- You have NO access to the experiment config or agent system prompts — evaluate only what you observe

Respond in JSON format:
{
    "dimension": "<dimension name>",
    "score": <1-10>,
    "justification": "<2-3 sentences explaining the score>",
    "evidence": ["<timestamp or agent:content reference>", ...]
}"""


def _build_judge_message(transcript: str, task: str, rubric: str) -> str:
    """Build the user message for the judge."""
    return f"""## Task Description

{task}

## Dimension Rubric

{rubric}

## Multi-Agent Transcript

{transcript}"""


def _parse_score_response(text: str, dimension: str) -> DimensionScore:
    """Parse a judge's JSON response into a DimensionScore."""
    # Handle markdown code fences
    content = text.strip()
    if "```json" in content:
        content = content.split("```json")[1].split("```")[0]
    elif "```" in content:
        content = content.split("```")[1].split("```")[0]

    try:
        data = json.loads(content)
    except json.JSONDecodeError as e:
        return DimensionScore(
            dimension=dimension,
            score=0,
            justification=f"Failed to parse judge response: {e}",
            evidence=[],
        )

    return DimensionScore(
        dimension=data.get("dimension", dimension),
        score=int(data.get("score", 0)),
        justification=data.get("justification", ""),
        evidence=data.get("evidence", []),
    )


@runtime_checkable
class JudgeBackend(Protocol):
    """Protocol for judge backends."""

    async def score(self, transcript: str, task: str, rubric: str) -> DimensionScore: ...


class OpenRouterJudge:
    """Judge backend using OpenRouter's OpenAI-compatible API."""

    def __init__(self, model: str = "google/gemini-2.0-flash-001", api_key: str | None = None):
        self.model = model
        self.api_key = api_key or os.environ.get("OPENROUTER_API_KEY", "")
        if not self.api_key:
            raise ValueError(
                "OPENROUTER_API_KEY not set. "
                "Set it in environment or pass api_key parameter."
            )

    async def score(self, transcript: str, task: str, rubric: str) -> DimensionScore:
        """Score a transcript via OpenRouter API."""
        dimension = _extract_dimension_name(rubric)
        message = _build_judge_message(transcript, task, rubric)

        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
            response = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
                        {"role": "user", "content": message},
                    ],
                    "temperature": 0.0,
                    "max_tokens": 2000,
                },
            )
            response.raise_for_status()

        data = response.json()
        content = data["choices"][0]["message"]["content"]
        return _parse_score_response(content, dimension)


class SDKJudge:
    """Judge backend using Claude Code headless via SDK.

    Spawns a fresh SDK session, posts the transcript + rubric as a message,
    and parses the structured response. Free (uses Claude Code login).
    """

    def __init__(self, sdk_binary_path: Path | None = None):
        self.sdk_binary_path = sdk_binary_path

    async def score(self, transcript: str, task: str, rubric: str) -> DimensionScore:
        """Score a transcript via Claude Code SDK headless session."""
        dimension = _extract_dimension_name(rubric)
        message = _build_judge_message(transcript, task, rubric)
        full_prompt = f"{JUDGE_SYSTEM_PROMPT}\n\n---\n\n{message}"

        # Use claude CLI in headless mode
        import asyncio
        import subprocess

        try:
            proc = await asyncio.create_subprocess_exec(
                "claude",
                "-p", full_prompt,
                "--output-format", "text",
                "--max-turns", "1",
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()

            if proc.returncode != 0:
                return DimensionScore(
                    dimension=dimension,
                    score=0,
                    justification=f"SDK judge failed: {stderr.decode()[:200]}",
                    evidence=[],
                )

            return _parse_score_response(stdout.decode(), dimension)

        except FileNotFoundError:
            return DimensionScore(
                dimension=dimension,
                score=0,
                justification="Claude CLI not found. Install Claude Code to use SDK backend.",
                evidence=[],
            )


def _extract_dimension_name(rubric: str) -> str:
    """Extract dimension name from rubric content."""
    for line in rubric.splitlines():
        line = line.strip()
        if line.startswith("# "):
            return line[2:].strip().lower().replace(" ", "-")
    return "unknown"


def load_rubric(dimension: str, judges_dir: Path) -> str:
    """Load a rubric file for a dimension."""
    rubric_path = judges_dir / f"{dimension}.md"
    if not rubric_path.exists():
        raise FileNotFoundError(f"Rubric not found: {rubric_path}")
    return rubric_path.read_text()


def load_transcript(experiment_dir: Path) -> tuple[str, str]:
    """Load transcript and task description from an experiment directory.

    Returns (transcript_text, task_description).
    """
    # Try markdown transcript first (more readable for judge)
    md_path = experiment_dir / "transcripts" / "full.md"
    json_path = experiment_dir / "transcripts" / "full.json"

    if md_path.exists():
        transcript = md_path.read_text()
    elif json_path.exists():
        transcript = json_path.read_text()
    else:
        raise FileNotFoundError(f"No transcript found in {experiment_dir / 'transcripts'}")

    # Load task from metadata
    metadata_path = experiment_dir / "metadata.json"
    task = ""
    if metadata_path.exists():
        with open(metadata_path) as f:
            metadata = json.load(f)
        task = metadata.get("task", metadata.get("experiment_name", ""))

    return transcript, task


async def judge_experiment(
    experiment_dir: Path,
    dimensions: list[str],
    judges_dir: Path,
    backend: JudgeBackend,
    backend_name: str = "unknown",
    model_name: str | None = None,
) -> ExperimentScores:
    """Score an experiment across multiple dimensions.

    Args:
        experiment_dir: Path to the experiment directory
        dimensions: List of dimension names to score
        judges_dir: Path to the judges/ directory containing rubric files
        backend: The judge backend to use
        backend_name: Name of the backend (for metadata)
        model_name: Model name (for metadata, OpenRouter only)

    Returns:
        ExperimentScores with all dimension scores
    """
    transcript, task = load_transcript(experiment_dir)

    scores = []
    for dimension in dimensions:
        rubric = load_rubric(dimension, judges_dir)
        score = await backend.score(transcript, task, rubric)
        scores.append(score)

    experiment_id = experiment_dir.name
    return ExperimentScores(
        experiment_id=experiment_id,
        scores=scores,
        judge_backend=backend_name,
        judge_model=model_name,
    )
