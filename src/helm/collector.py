"""Event collection and transcript generation.

Aggregates events from multiple agent sessions into unified transcripts
for analysis and evaluation.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from helm.coordination.base import CoordinationMessage
from helm.sdk import SDKEvent


@dataclass
class TranscriptItem:
    """A single item in a transcript."""

    timestamp: datetime
    session_id: str
    agent_id: str
    event_type: str
    data: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "session_id": self.session_id,
            "agent_id": self.agent_id,
            "event_type": self.event_type,
            "data": self.data,
        }


@dataclass
class AgentTranscript:
    """Transcript for a single agent."""

    agent_id: str
    session_id: str
    items: list[TranscriptItem] = field(default_factory=list)
    start_time: datetime | None = None
    end_time: datetime | None = None

    def add_event(self, event: SDKEvent, timestamp: datetime | None = None) -> None:
        """Add an event to this transcript."""
        ts = timestamp or datetime.now()
        if self.start_time is None:
            self.start_time = ts

        item = TranscriptItem(
            timestamp=ts,
            session_id=self.session_id,
            agent_id=self.agent_id,
            event_type=event.type,
            data=event.data,
        )
        self.items.append(item)
        self.end_time = ts

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "session_id": self.session_id,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "item_count": len(self.items),
            "items": [item.to_dict() for item in self.items],
        }


@dataclass
class MultiAgentTranscript:
    """Aggregated transcript from multiple agents."""

    experiment_id: str
    experiment_name: str
    agents: dict[str, AgentTranscript] = field(default_factory=dict)
    coordination_messages: list[CoordinationMessage] = field(default_factory=list)
    start_time: datetime | None = None
    end_time: datetime | None = None

    def add_agent(self, agent_id: str, session_id: str) -> AgentTranscript:
        """Add a new agent transcript."""
        transcript = AgentTranscript(agent_id=agent_id, session_id=session_id)
        self.agents[agent_id] = transcript
        return transcript

    def record(
        self,
        agent_id: str,
        event: SDKEvent,
        timestamp: datetime | None = None,
    ) -> None:
        """Record an event from an agent."""
        ts = timestamp or datetime.now()
        if self.start_time is None:
            self.start_time = ts

        if agent_id not in self.agents:
            raise ValueError(f"Unknown agent: {agent_id}")

        self.agents[agent_id].add_event(event, ts)
        self.end_time = ts

    def record_coordination(self, message: CoordinationMessage) -> None:
        """Record a coordination message observed by the backend."""
        self.coordination_messages.append(message)

    def get_all_items(self) -> list[TranscriptItem]:
        """Get all items across all agents, sorted by timestamp."""
        all_items = []
        for transcript in self.agents.values():
            all_items.extend(transcript.items)
        return sorted(all_items, key=lambda x: x.timestamp)

    def _coordination_summary(self) -> dict[str, Any]:
        """Build a summary of coordination activity."""
        total = len(self.coordination_messages)
        delivered = sum(1 for m in self.coordination_messages if m.delivered)
        by_type: dict[str, int] = {}
        for m in self.coordination_messages:
            by_type[m.message_type.value] = by_type.get(m.message_type.value, 0) + 1

        return {
            "total_messages": total,
            "delivered": delivered,
            "delivery_rate": delivered / total if total > 0 else 0.0,
            "by_type": by_type,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "experiment_id": self.experiment_id,
            "experiment_name": self.experiment_name,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "agents": {aid: t.to_dict() for aid, t in self.agents.items()},
            "total_items": sum(len(t.items) for t in self.agents.values()),
            "coordination_messages": [m.to_dict() for m in self.coordination_messages],
            "coordination_summary": self._coordination_summary(),
        }


class EventCollector:
    """Collects and aggregates events from multiple agent sessions."""

    def __init__(self, experiment_id: str, experiment_name: str):
        self.transcript = MultiAgentTranscript(
            experiment_id=experiment_id,
            experiment_name=experiment_name,
        )
        self._session_to_agent: dict[str, str] = {}

    def register_agent(self, agent_id: str, session_id: str) -> None:
        """Register an agent for event collection."""
        self.transcript.add_agent(agent_id, session_id)
        self._session_to_agent[session_id] = agent_id

    def record(self, session_id: str, event: SDKEvent) -> None:
        """Record an event from a session."""
        agent_id = self._session_to_agent.get(session_id)
        if agent_id is None:
            raise ValueError(f"Unknown session: {session_id}")

        self.transcript.record(agent_id, event)

    def record_coordination(self, message: CoordinationMessage) -> None:
        """Record a coordination message from the backend."""
        self.transcript.record_coordination(message)

    def get_agent_by_session(self, session_id: str) -> str | None:
        """Get agent ID for a session ID."""
        return self._session_to_agent.get(session_id)

    def to_transcript(self) -> MultiAgentTranscript:
        """Get the aggregated transcript."""
        return self.transcript

    def save(self, path: Path) -> None:
        """Save the transcript to a file."""
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(self.transcript.to_dict(), f, indent=2)

    def save_markdown(self, path: Path) -> None:
        """Save the transcript as readable markdown."""
        path.parent.mkdir(parents=True, exist_ok=True)

        lines = [
            f"# Experiment: {self.transcript.experiment_name}",
            f"ID: `{self.transcript.experiment_id}`",
            "",
            f"**Start**: {self.transcript.start_time}",
            f"**End**: {self.transcript.end_time}",
            "",
            "---",
            "",
        ]

        for item in self.transcript.get_all_items():
            # Skip streaming deltas — item.completed has the full content
            if item.event_type == "item.delta":
                continue

            # Skip item.started — it carries no content
            if item.event_type == "item.started":
                continue

            lines.append(f"## [{item.timestamp.strftime('%H:%M:%S')}] {item.agent_id}")
            lines.append(f"**Event**: `{item.event_type}`")
            lines.append("")

            # Format event data nicely
            if item.event_type == "item.completed":
                item_data = item.data.get("item", {})
                role = item_data.get("role", item_data.get("kind", "unknown"))
                lines.append(f"**Role**: {role}")

                for part in item_data.get("content", []):
                    if part.get("type") == "text":
                        text = part.get("text", "")[:2000]
                        if len(part.get("text", "")) > 2000:
                            text += "..."
                        lines.append(f"\n```\n{text}\n```")
                    elif part.get("type") == "tool_call":
                        tool_name = part.get("name", "unknown")
                        # arguments can be a JSON string or a dict
                        raw_args = part.get("arguments", part.get("input", {}))
                        if isinstance(raw_args, str):
                            try:
                                tool_args = json.loads(raw_args)
                            except (json.JSONDecodeError, TypeError):
                                tool_args = {}
                        else:
                            tool_args = raw_args or {}
                        # Show tool name and key arguments
                        lines.append(f"**Tool**: `{tool_name}`")
                        if isinstance(tool_args, dict):
                            # Show command for Bash, path for Read/Write/Edit, pattern for Grep/Glob
                            for key in ("command", "file_path", "path", "pattern", "query"):
                                if key in tool_args:
                                    val = str(tool_args[key])[:300]
                                    lines.append(f"  {key}: `{val}`")
                                    break
                    elif part.get("type") == "tool_result":
                        output = part.get("output", part.get("text", ""))
                        is_error = part.get("is_error", False)
                        if output:
                            output_str = str(output)[:1000]
                            if len(str(output)) > 1000:
                                output_str += "..."
                            label = "**Error Output**" if is_error else "**Output**"
                            lines.append(f"{label}:")
                            lines.append(f"\n```\n{output_str}\n```")
                    elif part.get("type") == "file_ref":
                        lines.append(f"**File**: {part.get('action')} `{part.get('path')}`")

            elif item.event_type == "permission.requested":
                lines.append(f"**Action**: `{item.data.get('action')}`")

            elif item.event_type == "permission.resolved":
                resolution = item.data.get("resolution", "unknown")
                lines.append(f"**Resolution**: {resolution}")

            elif item.event_type == "question.requested":
                lines.append(f"**Prompt**: {item.data.get('prompt')}")

            elif item.event_type == "session.started":
                lines.append("*Session started*")

            elif item.event_type == "session.ended":
                lines.append("*Session ended*")

            lines.append("")
            lines.append("---")
            lines.append("")

        # Coordination messages section
        coord_msgs = self.transcript.coordination_messages
        if coord_msgs:
            lines.append("## Coordination Messages")
            lines.append("")
            summary = self.transcript._coordination_summary()
            lines.append(
                f"**Total**: {summary['total_messages']} | "
                f"**Delivered**: {summary['delivered']} | "
                f"**Rate**: {summary['delivery_rate']:.0%}"
            )
            lines.append("")

            for msg in coord_msgs:
                ts = msg.timestamp.strftime("%H:%M:%S")
                direction = f"{msg.sender or '?'} → {msg.recipient or '?'}"
                lines.append(
                    f"- `[{ts}]` **{msg.message_type.value}** {direction}"
                )
                if msg.source_path:
                    lines.append(f"  - File: `{msg.source_path}`")
                if msg.delivered:
                    lines.append("  - Nudge delivered")
                lines.append("")

            lines.append("---")
            lines.append("")

        with open(path, "w") as f:
            f.write("\n".join(lines))
