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
from pydantic import BaseModel, Field, field_validator, model_validator


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
    model: str | None = None  # Declared model identity for provenance (e.g. "claude-opus-4-6")
    role: AgentRole | None = None
    system_prompt: str = ""
    disallowed_tools: list[str] = Field(default_factory=list)


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


class CoordinationChannelMedium(str, Enum):
    """Transport used for a coordination channel."""

    FILESYSTEM = "filesystem"
    LIVE_MESSAGE = "live_message"


class CoordinationChannelPersistence(str, Enum):
    """Whether coordination survives beyond the active context window."""

    PERSISTENT = "persistent"
    EPHEMERAL = "ephemeral"


class CoordinationChannelScope(str, Enum):
    """Audience shape for a coordination channel."""

    TARGETED = "targeted"
    BROADCAST = "broadcast"
    SHARED = "shared"
    MIXED = "mixed"


class CoordinationChannelAvailability(str, Enum):
    """Whether a channel is always present or depends on the harness/runtime."""

    ALWAYS = "always"
    HARNESS_DEPENDENT = "harness_dependent"
    EXPERIMENTAL = "experimental"


class CoordinationChannelConfig(BaseModel):
    """A coordination affordance exposed by the experiment condition.

    These fields describe available channels for prompts, analysis, and later
    telemetry work. They do not by themselves enforce any behavior.
    """

    id: str
    medium: CoordinationChannelMedium
    persistence: CoordinationChannelPersistence
    scope: CoordinationChannelScope
    description: str = ""
    paths: list[str] = Field(default_factory=list)
    availability: CoordinationChannelAvailability = CoordinationChannelAvailability.ALWAYS


class CoordinationMechanism(str, Enum):
    """Primary coordination channel agents should use."""

    FILESYSTEM = "filesystem"
    MESSAGING = "messaging"

    @classmethod
    def _missing_(cls, value: object) -> CoordinationMechanism | None:
        """Accept legacy string values."""
        if isinstance(value, str):
            for member in cls:
                if member.value == value.lower():
                    return member
        return None


class CoordinationConfig(BaseModel):
    """Configuration for inter-agent coordination."""

    mechanism: CoordinationMechanism = CoordinationMechanism.FILESYSTEM
    delivery: str = "poll"  # "push" or "poll"
    enforcement: str = "prompt-only"  # "mechanical" or "prompt-only"
    paths: CoordinationPaths = Field(default_factory=CoordinationPaths)
    channels: list[CoordinationChannelConfig] = Field(default_factory=list)
    backend_settings: dict[str, Any] = Field(default_factory=dict)
    task_format: str | None = None
    message_format: str | None = None
    state_schema: dict[str, Any] | None = None


class JudgeBackendType(str, Enum):
    """Backend type for the judge."""

    CLAUDE_HEADLESS = "claude-headless"
    CODEX_HEADLESS = "codex-headless"
    OPENROUTER = "openrouter"
    SDK = "sdk"


class JudgeConfig(BaseModel):
    """Configuration for the evaluation judge.

    Supports three backends:
    - claude-headless: uses Claude Code headless via CLI
    - codex-headless: uses Codex headless via CLI
    - openrouter: calls OpenRouter's OpenAI-compatible API (requires OPENROUTER_API_KEY)
    - sdk: legacy alias for claude-headless
    """

    backend: JudgeBackendType = JudgeBackendType.CLAUDE_HEADLESS
    model: str | None = None

    @field_validator("backend", mode="before")
    @classmethod
    def _normalize_backend_alias(cls, value: Any) -> Any:
        if isinstance(value, str) and value.strip().lower() == "sdk":
            return JudgeBackendType.CLAUDE_HEADLESS
        return value

    @field_validator("model", mode="before")
    @classmethod
    def _default_openrouter_model(cls, value: Any, info) -> Any:
        return value

    @model_validator(mode="after")
    def _apply_backend_defaults(self) -> "JudgeConfig":
        if self.backend == JudgeBackendType.OPENROUTER and not self.model:
            self.model = "google/gemini-2.0-flash-001"
        return self


class EvaluationConfig(BaseModel):
    """Configuration for experiment evaluation."""

    dimensions: list[str] = Field(default_factory=list)
    judge: JudgeConfig = Field(default_factory=JudgeConfig)


class BenchmarkConfig(BaseModel):
    """Configuration for benchmark-backed experiment tasks."""

    adapter: str
    dataset_path: str
    benchmark_id: str | None = Field(None, alias="id")
    split: str | None = None
    seed: int | None = None
    example_id: str | None = None
    example_ids: list[str] = Field(default_factory=list)
    max_examples: int | None = None
    example_metadata: dict[str, Any] = Field(default_factory=dict)
    verifier: dict[str, Any] = Field(default_factory=dict)

    model_config = {"populate_by_name": True}

    def selected_example_ids(self) -> list[str]:
        """Return de-duplicated configured example IDs in priority order."""
        ordered: list[str] = []
        if self.example_id:
            ordered.append(self.example_id)
        ordered.extend(self.example_ids)

        seen: set[str] = set()
        deduped: list[str] = []
        for example_id in ordered:
            if example_id in seen:
                continue
            deduped.append(example_id)
            seen.add(example_id)
        return deduped

    def verifier_mode(self) -> str:
        """Return verifier mode (defaults to completion)."""
        mode = self.verifier.get("mode", "completion")
        if isinstance(mode, str):
            return mode.strip().lower() or "completion"
        return "completion"

    def verifier_command(self) -> str | None:
        """Return optional verifier command string."""
        command = self.verifier.get("command")
        if isinstance(command, str) and command.strip():
            return command.strip()
        return None

    def verifier_pass_exit_codes(self) -> list[int]:
        """Return list of command exit codes treated as success."""
        raw = self.verifier.get("pass_exit_codes", [0])
        if not isinstance(raw, list):
            return [0]
        out: list[int] = []
        for item in raw:
            if isinstance(item, int):
                out.append(item)
        return out if out else [0]


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


class MatrixMetadata(BaseModel):
    """Structured metadata for experiment-matrix generated conditions."""

    matrix_id: str
    condition_id: str
    base_condition_id: str | None = None
    harness: str | None = None
    architecture_family: str
    swarm_size: int
    task_pack: str
    task_structure: str
    prompt_family: str
    coordination_family: str
    replication_index: int = 1
    replication_count: int = 1
    turn_limit_variant: int | None = None


class PairedEvaluationMetadata(BaseModel):
    """Metadata describing a paired-run comparison design."""

    comparison_id: str
    comparison_role: str
    comparison_axis: str = "monitoring-evasion"
    visible_monitoring: bool | None = None
    partner_condition_id: str | None = None
    notes: str | None = None


class ExperimentMetadata(BaseModel):
    """Metadata about the experiment pattern."""

    created: str | None = None
    author: str | None = None
    version: int = 1
    matrix: MatrixMetadata | None = None
    paired_evaluation: PairedEvaluationMetadata | None = None

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
    benchmark: BenchmarkConfig | None = None
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

    def topology_label(self) -> str:
        """Return the experiment topology label used in metadata and prompts."""
        if len(self.agents) <= 1:
            return "single-agent"
        if self.is_hub_and_spoke():
            return "hub-and-spoke"
        return "peer-network"

    def matrix_metadata(self) -> dict[str, Any] | None:
        """Return matrix metadata as a plain dict when present."""
        if self.metadata.matrix is None:
            return None
        return self.metadata.matrix.model_dump()

    def paired_evaluation_metadata(self) -> dict[str, Any] | None:
        """Return paired-evaluation metadata as a plain dict when present."""
        if self.metadata.paired_evaluation is None:
            return None
        return self.metadata.paired_evaluation.model_dump(exclude_none=True)

    def get_hub_agent(self) -> AgentConfig | None:
        """Get the hub agent if this is hub-and-spoke."""
        for agent in self.agents:
            if agent.role == AgentRole.HUB:
                return agent
        return None

    def get_worker_agents(self) -> list[AgentConfig]:
        """Get worker agents (non-hub agents)."""
        return [agent for agent in self.agents if agent.role != AgentRole.HUB]
