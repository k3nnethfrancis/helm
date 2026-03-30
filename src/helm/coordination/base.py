"""Abstract coordination backend protocol and shared types.

Defines the interface that all coordination backends must implement,
plus shared message types for tracking coordination events.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Protocol, runtime_checkable

from helm.sdk import SDKClient


class MessageType(str, Enum):
    """Types of coordination messages between agents."""

    TASK_ASSIGNMENT = "task_assignment"
    STATUS_UPDATE = "status_update"
    COMPLETION_SIGNAL = "completion_signal"
    QUESTION = "question"
    DECISION = "decision"
    PEER_MESSAGE = "peer_message"
    NUDGE = "nudge"


class DeliveryStatus(str, Enum):
    """Delivery state for transient live follow-up messages."""

    NOT_ATTEMPTED = "not_attempted"
    DELIVERED = "delivered"
    PARTIAL = "partial"
    FAILED = "failed"


@dataclass
class CoordinationMessage:
    """A single coordination event observed by the backend."""

    timestamp: datetime
    sender: str | None
    recipient: str | None
    message_type: MessageType
    content: str
    source_path: str | None = None
    channel_id: str | None = None
    channel_medium: str | None = None
    channel_persistence: str | None = None
    channel_scope: str | None = None
    channel_availability: str | None = None
    observed_via: str | None = None
    delivered: bool = False
    delivery_status: DeliveryStatus = DeliveryStatus.NOT_ATTEMPTED
    delivery_timestamp: datetime | None = None
    nudge_text: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "sender": self.sender,
            "recipient": self.recipient,
            "message_type": self.message_type.value,
            # Keep full payload for offline analysis/training.
            "content": self.content,
            "source_path": self.source_path,
            "channel_id": self.channel_id,
            "channel_medium": self.channel_medium,
            "channel_persistence": self.channel_persistence,
            "channel_scope": self.channel_scope,
            "channel_availability": self.channel_availability,
            "observed_via": self.observed_via,
            "delivered": self.delivered,
            "delivery_status": self.delivery_status.value,
            "delivery_timestamp": (
                self.delivery_timestamp.isoformat() if self.delivery_timestamp else None
            ),
            "nudge_text": self.nudge_text,
            "metadata": self.metadata,
        }


# Callback type for coordination message reporting
OnMessageCallback = Callable[[CoordinationMessage], None]


@runtime_checkable
class CoordinationBackend(Protocol):
    """Protocol defining the coordination backend interface.

    A backend owns the full coordination lifecycle:
    - Setting up the coordination environment (directories, queues, etc.)
    - Watching for new coordination artifacts and delivering nudges
    - Detecting experiment completion via coordination signals
    - Cleaning up resources

    Implementations must be async-compatible. The poll/watch loop runs
    as an asyncio task managed by start_watching/stop_watching.
    """

    async def setup(
        self,
        experiment_dir: Any,
        agents: list[str],
        config: dict[str, Any],
    ) -> None:
        """Initialize the coordination environment.

        Args:
            experiment_dir: Path to the experiment directory.
            agents: List of agent IDs participating.
            config: Full coordination config dict from the pattern YAML.
        """
        ...

    def get_prompt_instructions(self, agent_id: str) -> str:
        """Return coordination instructions to inject into an agent's prompt.

        Returns empty string if the backend doesn't need to override
        the YAML-defined system prompts (e.g., filesystem backend).
        """
        ...

    async def start_watching(
        self,
        sdk: SDKClient,
        agent_sessions: dict[str, str],
        on_message: OnMessageCallback,
        push_callback: Any = None,
    ) -> None:
        """Begin monitoring for coordination events and delivering nudges.

        Args:
            sdk: The SDK client for sending nudge messages.
            agent_sessions: Mapping of agent_id -> session_id.
            on_message: Callback invoked for each coordination message observed.
            push_callback: Optional async callback ``(agent_id, content) -> None``
                for pushing messages into running agent sessions (tmux push delivery).
        """
        ...

    async def stop_watching(self) -> None:
        """Stop the monitoring loop."""
        ...

    def is_complete(self, agents: list[str]) -> bool:
        """Check if the coordination protocol signals that work is done.

        Args:
            agents: List of agent IDs to check completion for.

        Returns:
            True if the coordination mechanism indicates all work is complete.
        """
        ...

    async def teardown(self) -> None:
        """Clean up any resources held by the backend."""
        ...
