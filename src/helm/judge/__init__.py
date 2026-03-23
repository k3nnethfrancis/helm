"""Evaluation judge for scoring experiment transcripts.

Supports three backends:
- OpenRouter: calls external LLM APIs (requires OPENROUTER_API_KEY)
- Claude headless: uses Claude Code CLI in headless mode
- Codex headless: uses Codex CLI in headless mode

Both backends receive a transcript + rubric and return structured scores.

Schema versions:
- v1: numeric 1-10 scores (deprecated)
- v2: discrete behavioral categories with severity mapping
"""

from helm.judge.scoring import (
    CATEGORY_TO_SEVERITY,
    DIMENSION_CATEGORIES,
    SEVERITY_ORDER,
    DimensionScore,
    ExperimentScores,
    _parse_judge_response,
    _score_to_category,
)
from helm.judge.backends import (
    JUDGE_SYSTEM_PROMPT,
    ClaudeHeadlessJudge,
    CodexHeadlessJudge,
    JudgeBackend,
    JudgeBackendTimeout,
    OpenRouterJudge,
    SDKJudge,
    load_rubric,
)
from helm.judge.strategy import (
    judge_experiment,
    load_transcript,
)

__all__ = [
    "CATEGORY_TO_SEVERITY",
    "DIMENSION_CATEGORIES",
    "JUDGE_SYSTEM_PROMPT",
    "SEVERITY_ORDER",
    "ClaudeHeadlessJudge",
    "CodexHeadlessJudge",
    "DimensionScore",
    "ExperimentScores",
    "JudgeBackend",
    "JudgeBackendTimeout",
    "OpenRouterJudge",
    "SDKJudge",
    "_parse_judge_response",
    "_score_to_category",
    "judge_experiment",
    "load_rubric",
    "load_transcript",
]
