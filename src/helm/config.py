"""Configuration models for Helm experiments.

Pydantic models that match the YAML pattern definitions.
Supports both hub-and-spoke and peer-network coordination patterns.
"""

from __future__ import annotations

from datetime import date
from enum import Enum
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator


class AgentRole(str, Enum):
    """Role an agent plays in a coordination pattern."""

    HUB = "hub"
    WORKER = "worker"
    PEER = "peer"  # Implicit when no role specified


class OrchestratorAction(str, Enum):
    """Actions the orchestrator can take."""

    APPROVE = "approve"
    REJECT = "reject"
    ESCALATE = "escalate"
    ESCALATE_TO_HUMAN = "escalate_to_human"
    LOG = "log"
    NUDGE = "nudge"
    NUDGE_COORDINATOR = "nudge_coordinator"


class AgentConfig(BaseModel):
    """Configuration for a single agent in the experiment."""

    id: str
    harness: str = "claude-code"
    role: AgentRole | None = None
    system_prompt: str = ""


class OrchestratorRule(BaseModel):
    """A rule defining when and how the orchestrator intervenes.

    Note: YAML parses `on:` as True (boolean), but we fix this in _fix_yaml_boolean_keys.
    """

    on: str  # Event type: permission.requested, question.requested, no_activity
    if_condition: str | None = Field(None, alias="if")
    from_agent: str | None = Field(None, alias="from")
    after: str | None = None  # Duration string like "120s", "5m"
    then: OrchestratorAction
    reason: str | None = None
    message: str | None = None

    model_config = {"populate_by_name": True}


class OrchestratorConfig(BaseModel):
    """Configuration for the orchestrator's behavior."""

    role: str = "observer"
    description: str = ""
    rules: list[OrchestratorRule] = Field(default_factory=list)


class CoordinationPaths(BaseModel):
    """Filesystem paths for coordination."""

    base: str = "coordination/"
    # Hub-and-spoke paths
    tasks: str | None = None
    status: str | None = None
    blocked: str | None = None
    questions: str | None = None
    decisions: str | None = None
    # Peer-network paths
    messages: str | None = None
    state: str | None = None
    signals: str | None = None
    reviews: str | None = None


class CoordinationConfig(BaseModel):
    """Configuration for inter-agent coordination."""

    mechanism: str = "filesystem"
    paths: CoordinationPaths = Field(default_factory=CoordinationPaths)
    backend_settings: dict[str, Any] = Field(default_factory=dict)
    task_format: str | None = None
    message_format: str | None = None
    state_schema: dict[str, Any] | None = None


class JudgeBackendType(str, Enum):
    """Backend type for the judge."""

    OPENROUTER = "openrouter"
    SDK = "sdk"


class JudgeConfig(BaseModel):
    """Configuration for the evaluation judge.

    Supports two backends:
    - openrouter: calls OpenRouter's OpenAI-compatible API (requires OPENROUTER_API_KEY)
    - sdk: uses Claude Code headless via SDK (free, uses Claude Code login)
    """

    backend: JudgeBackendType = JudgeBackendType.SDK
    model: str = "google/gemini-2.0-flash-001"  # Only used for openrouter backend


class EvaluationConfig(BaseModel):
    """Configuration for experiment evaluation."""

    dimensions: list[str] = Field(default_factory=list)
    judge: JudgeConfig = Field(default_factory=JudgeConfig)


class LimitsConfig(BaseModel):
    """Resource limits for the experiment."""

    max_duration: str = "30m"
    max_turns_per_agent: int = 50
    max_budget_usd: float = 15.00
    blocked_commands: list[str] = Field(
        default_factory=lambda: ["rm -rf", "sudo"]
    )
    workspace_files: dict[str, str] = Field(default_factory=dict)

    def duration_seconds(self) -> int:
        """Parse duration string to seconds."""
        duration = self.max_duration.strip().lower()
        if duration.endswith("s"):
            return int(duration[:-1])
        elif duration.endswith("m"):
            return int(duration[:-1]) * 60
        elif duration.endswith("h"):
            return int(duration[:-1]) * 3600
        else:
            return int(duration)


class ExperimentMetadata(BaseModel):
    """Metadata about the experiment pattern."""

    created: str | None = None
    author: str | None = None
    version: int = 1

    @field_validator("created", mode="before")
    @classmethod
    def coerce_date_to_string(cls, v: Any) -> str | None:
        """Convert date objects to strings."""
        if v is None:
            return None
        if isinstance(v, date):
            return v.isoformat()
        return str(v)


def _fix_yaml_boolean_keys(data: dict[str, Any]) -> dict[str, Any]:
    """Fix YAML 1.1 boolean key parsing issue.

    YAML 1.1 parses `on:`, `off:`, `yes:`, `no:` as boolean keys.
    This function converts them back to strings where expected.
    """
    if "orchestrator" in data and "rules" in data["orchestrator"]:
        fixed_rules = []
        for rule in data["orchestrator"]["rules"]:
            if True in rule:
                # YAML parsed `on:` as True - fix it
                fixed_rule = {"on": rule.pop(True)}
                fixed_rule.update(rule)
                fixed_rules.append(fixed_rule)
            else:
                fixed_rules.append(rule)
        data["orchestrator"]["rules"] = fixed_rules
    return data


class ExperimentConfig(BaseModel):
    """Complete experiment configuration."""

    name: str
    description: str = ""
    agents: list[AgentConfig]
    orchestrator: OrchestratorConfig = Field(default_factory=OrchestratorConfig)
    coordination: CoordinationConfig = Field(default_factory=CoordinationConfig)
    evaluation: EvaluationConfig = Field(default_factory=EvaluationConfig)
    limits: LimitsConfig = Field(default_factory=LimitsConfig)
    metadata: ExperimentMetadata = Field(default_factory=ExperimentMetadata)

    @classmethod
    def from_yaml(cls, path: Path) -> ExperimentConfig:
        """Load configuration from a YAML file."""
        with open(path) as f:
            data = yaml.safe_load(f)
        # Fix YAML 1.1 boolean key parsing
        data = _fix_yaml_boolean_keys(data)
        return cls.model_validate(data)

    def is_hub_and_spoke(self) -> bool:
        """Check if this is a hub-and-spoke pattern."""
        return any(agent.role == AgentRole.HUB for agent in self.agents)

    def get_hub_agent(self) -> AgentConfig | None:
        """Get the hub agent if this is hub-and-spoke."""
        for agent in self.agents:
            if agent.role == AgentRole.HUB:
                return agent
        return None

    def get_worker_agents(self) -> list[AgentConfig]:
        """Get worker agents (non-hub agents)."""
        return [agent for agent in self.agents if agent.role != AgentRole.HUB]
