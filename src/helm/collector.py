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
from helm.adapters import SDKEvent

TRANSCRIPT_TEXT_PREVIEW_CHARS = 2000
TRANSCRIPT_TOOL_RESULT_PREVIEW_CHARS = 2000
TRANSCRIPT_COORDINATION_PREVIEW_CHARS = 1500
# Keys rendered inline on the tool call line for quick scanning.
# All other input keys are rendered as indented key: value pairs.
TOOL_PRIMARY_KEYS = ("command", "file_path", "path", "pattern", "query")
# Maximum length for a single tool input value before truncation.
TOOL_INPUT_VALUE_MAX_CHARS = 400


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
        return summarize_coordination_messages(
            self.coordination_messages,
            agents=self.agents,
        )

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


def _coordination_message_to_dict(message: CoordinationMessage | dict[str, Any]) -> dict[str, Any]:
    if isinstance(message, CoordinationMessage):
        return message.to_dict()
    return message


def _increment(counter: dict[str, int], key: Any) -> None:
    if not isinstance(key, str) or not key:
        return
    counter[key] = counter.get(key, 0) + 1


def _parse_iso_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _build_agent_activity_index(agents: Any) -> tuple[dict[str, list[datetime]], list[str]]:
    activity_by_agent: dict[str, list[datetime]] = {}
    agent_ids: list[str] = []

    if not isinstance(agents, dict):
        return activity_by_agent, agent_ids

    for agent_id, agent_data in agents.items():
        if not isinstance(agent_id, str):
            continue
        agent_ids.append(agent_id)
        activity_by_agent[agent_id] = []

        if isinstance(agent_data, AgentTranscript):
            items = [item.to_dict() for item in agent_data.items]
        elif isinstance(agent_data, dict):
            items = agent_data.get("items", [])
        else:
            items = []

        if not isinstance(items, list):
            continue

        for item in items:
            if not isinstance(item, dict):
                continue
            ts = _parse_iso_timestamp(item.get("timestamp"))
            if ts is not None:
                activity_by_agent[agent_id].append(ts)

        activity_by_agent[agent_id].sort()

    return activity_by_agent, agent_ids


def _message_delivery_status(message: dict[str, Any]) -> str:
    explicit = message.get("delivery_status")
    if isinstance(explicit, str) and explicit:
        return explicit

    metadata = message.get("metadata", {})
    if not isinstance(metadata, dict):
        metadata = {}

    attempted_targets = metadata.get("delivery_attempted_to", [])
    delivered_targets = metadata.get("delivered_to", [])
    if not isinstance(attempted_targets, list):
        attempted_targets = []
    if not isinstance(delivered_targets, list):
        delivered_targets = []

    if message.get("delivered"):
        return "delivered"
    if attempted_targets and delivered_targets:
        return "partial"
    if attempted_targets:
        return "failed"
    return "not_attempted"


def _resolve_message_targets(
    message: dict[str, Any],
    *,
    agent_ids: list[str],
) -> list[str]:
    metadata = message.get("metadata", {})
    if not isinstance(metadata, dict):
        metadata = {}

    attempted_targets = metadata.get("delivery_attempted_to", [])
    if isinstance(attempted_targets, list) and attempted_targets:
        return [target for target in attempted_targets if isinstance(target, str) and target]

    sender = message.get("sender")
    recipient = message.get("recipient")
    if isinstance(recipient, str) and recipient:
        if recipient == "__all__":
            return [agent_id for agent_id in agent_ids if agent_id != sender]
        return [recipient]

    scope = message.get("channel_scope")
    if isinstance(scope, str) and scope in {"broadcast", "shared"}:
        return [agent_id for agent_id in agent_ids if agent_id != sender]

    return []


def summarize_coordination_messages(
    messages: list[CoordinationMessage | dict[str, Any]],
    *,
    agents: Any = None,
) -> dict[str, Any]:
    """Summarize coordination artifacts and live nudge delivery separately."""
    total = len(messages)
    nudge_attempts = 0
    nudge_delivered = 0
    file_backed_messages = 0
    by_type: dict[str, int] = {}
    by_channel: dict[str, int] = {}
    by_medium: dict[str, int] = {}
    by_persistence: dict[str, int] = {}
    by_scope: dict[str, int] = {}
    by_delivery_status: dict[str, int] = {}
    by_observed_via: dict[str, int] = {}
    agent_activity_by_agent, agent_ids = _build_agent_activity_index(agents)
    recipient_activity_checks = 0
    recipient_activity_hits = 0
    messages_with_any_recipient_activity = 0
    messages_without_recipient_activity = 0

    for raw_message in messages:
        message = _coordination_message_to_dict(raw_message)
        message_type = str(message.get("message_type", "unknown"))
        by_type[message_type] = by_type.get(message_type, 0) + 1

        if message.get("source_path"):
            file_backed_messages += 1

        metadata = message.get("metadata", {})
        attempted_targets = []
        if isinstance(metadata, dict):
            attempted_targets = metadata.get("delivery_attempted_to", [])

        attempted = bool(message.get("nudge_text")) or bool(attempted_targets)
        if attempted:
            nudge_attempts += 1
        if message.get("delivered"):
            nudge_delivered += 1

        _increment(by_channel, message.get("channel_id"))
        _increment(by_medium, message.get("channel_medium"))
        _increment(by_persistence, message.get("channel_persistence"))
        _increment(by_scope, message.get("channel_scope"))
        _increment(by_observed_via, message.get("observed_via"))

        delivery_status = _message_delivery_status(message)
        _increment(by_delivery_status, delivery_status)

        targets = _resolve_message_targets(message, agent_ids=agent_ids)
        if targets:
            ts = _parse_iso_timestamp(message.get("timestamp"))
            active_targets = 0
            recipient_activity_checks += len(targets)
            for target in targets:
                if ts is None:
                    continue
                if any(event_ts > ts for event_ts in agent_activity_by_agent.get(target, [])):
                    active_targets += 1
            recipient_activity_hits += active_targets
            if active_targets > 0:
                messages_with_any_recipient_activity += 1
            else:
                messages_without_recipient_activity += 1

    nudge_delivery_rate = None
    if nudge_attempts > 0:
        nudge_delivery_rate = nudge_delivered / nudge_attempts

    recipient_activity_rate = None
    if recipient_activity_checks > 0:
        recipient_activity_rate = recipient_activity_hits / recipient_activity_checks

    return {
        "total_messages": total,
        "observed_messages": total,
        "file_backed_messages": file_backed_messages,
        "nudge_attempts": nudge_attempts,
        "delivered": nudge_delivered,
        # Backward-compatible alias for older consumers.
        "delivery_rate": nudge_delivery_rate,
        "nudge_delivery_rate": nudge_delivery_rate,
        "by_type": by_type,
        "by_channel": by_channel,
        "by_medium": by_medium,
        "by_persistence": by_persistence,
        "by_scope": by_scope,
        "by_delivery_status": by_delivery_status,
        "by_observed_via": by_observed_via,
        "recipient_activity_checks": recipient_activity_checks,
        "recipient_activity_hits": recipient_activity_hits,
        "recipient_activity_rate": recipient_activity_rate,
        "messages_with_any_recipient_activity": messages_with_any_recipient_activity,
        "messages_without_recipient_activity": messages_without_recipient_activity,
    }


def _sorted_transcript_items(transcript: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    agents = transcript.get("agents", {})
    if not isinstance(agents, dict):
        return items

    for agent_id, agent_data in agents.items():
        if not isinstance(agent_data, dict):
            continue
        for item in agent_data.get("items", []):
            if not isinstance(item, dict):
                continue
            enriched = dict(item)
            enriched["agent_id"] = agent_id
            items.append(enriched)

    items.sort(key=lambda item: str(item.get("timestamp", "")))
    return items


def _count_agent_tools(
    items: list[dict[str, Any]],
) -> tuple[int, int, dict[str, int]]:
    """Count tool calls, errors, and per-tool-name breakdown."""
    tool_calls = 0
    tool_errors = 0
    tool_names: dict[str, int] = {}

    for item in items:
        if not isinstance(item, dict):
            continue
        if item.get("event_type") != "item.completed":
            continue
        data = item.get("data", {})
        if not isinstance(data, dict):
            continue
        item_data = data.get("item", {})
        if not isinstance(item_data, dict):
            continue
        content = item_data.get("content", [])
        if not isinstance(content, list):
            continue
        for part in content:
            if not isinstance(part, dict):
                continue
            if part.get("type") in ("tool_call", "tool_use"):
                tool_calls += 1
                name = part.get("name", "unknown")
                tool_names[name] = tool_names.get(name, 0) + 1
            elif part.get("type") == "tool_result" and part.get(
                "is_error"
            ):
                tool_errors += 1

    return tool_calls, tool_errors, tool_names


def build_communication_view(transcript: dict[str, Any]) -> dict[str, Any]:
    """Build a coordination-only judge view from a multi-agent transcript."""
    coordination_messages = transcript.get("coordination_messages", [])
    if not isinstance(coordination_messages, list):
        coordination_messages = []

    agents = transcript.get("agents", {})
    summary = summarize_coordination_messages(coordination_messages, agents=agents)
    agent_activity_by_agent, agent_ids = _build_agent_activity_index(agents)

    rendered_messages: list[dict[str, Any]] = []
    for raw_message in coordination_messages:
        if not isinstance(raw_message, (dict, CoordinationMessage)):
            continue
        message = _coordination_message_to_dict(raw_message)
        ts = _parse_iso_timestamp(message.get("timestamp"))
        targets = _resolve_message_targets(message, agent_ids=agent_ids)
        active_targets: list[str] = []
        inactive_targets: list[str] = []
        if ts is not None:
            for target in targets:
                if any(event_ts > ts for event_ts in agent_activity_by_agent.get(target, [])):
                    active_targets.append(target)
                else:
                    inactive_targets.append(target)

        rendered_messages.append(
            {
                "timestamp": message.get("timestamp"),
                "sender": message.get("sender"),
                "recipient": message.get("recipient"),
                "message_type": message.get("message_type"),
                "content": message.get("content"),
                "source_path": message.get("source_path"),
                "channel_id": message.get("channel_id"),
                "channel_medium": message.get("channel_medium"),
                "channel_persistence": message.get("channel_persistence"),
                "channel_scope": message.get("channel_scope"),
                "observed_via": message.get("observed_via"),
                "delivery_status": _message_delivery_status(message),
                "targets": targets,
                "recipient_activity": {
                    "active_targets": active_targets,
                    "inactive_targets": inactive_targets,
                    "had_any_post_message_activity": bool(active_targets) if targets else None,
                },
            }
        )

    return {
        "view_type": "coordination-only",
        "experiment_id": transcript.get("experiment_id"),
        "experiment_name": transcript.get("experiment_name"),
        "start_time": transcript.get("start_time"),
        "end_time": transcript.get("end_time"),
        "coordination_summary": summary,
        "messages": rendered_messages,
    }


def render_communication_view_markdown(view: dict[str, Any]) -> str:
    """Render a coordination-only judge view as readable markdown."""
    lines = [
        "# Coordination View",
        f"Experiment: `{view.get('experiment_id')}`",
        "",
    ]

    summary = view.get("coordination_summary", {})
    if isinstance(summary, dict):
        recipient_activity_rate = summary.get("recipient_activity_rate")
        if isinstance(recipient_activity_rate, (int, float)):
            recipient_activity_label = f"{recipient_activity_rate:.0%}"
        else:
            recipient_activity_label = "n/a"
        lines.extend(
            [
                "## Coordination Summary",
                "",
                f"- Observed messages: `{summary.get('observed_messages', 0)}`",
                f"- File-backed messages: `{summary.get('file_backed_messages', 0)}`",
                f"- Live nudges attempted: `{summary.get('nudge_attempts', 0)}`",
                f"- Live nudges delivered: `{summary.get('delivered', 0)}`",
                f"- Recipient activity rate: `{recipient_activity_label}`",
                "",
            ]
        )

    lines.extend(["## Message Timeline", ""])
    for message in view.get("messages", []):
        if not isinstance(message, dict):
            continue
        timestamp = str(message.get("timestamp", ""))
        ts = timestamp[11:19] if len(timestamp) >= 19 else timestamp or "unknown"
        lines.append(
            f"- `[{ts}]` `{message.get('sender') or '?'} -> {message.get('recipient') or '?'}` "
            f"`{message.get('message_type') or 'unknown'}`"
        )
        channel_bits = [
            bit
            for bit in [
                message.get("channel_id"),
                message.get("channel_medium"),
                message.get("channel_persistence"),
                message.get("channel_scope"),
            ]
            if isinstance(bit, str) and bit
        ]
        if channel_bits:
            lines.append(f"  - Channel: `{', '.join(channel_bits)}`")
        if message.get("source_path"):
            lines.append(f"  - Artifact: `{message['source_path']}`")
        if message.get("observed_via"):
            lines.append(f"  - Observed via: `{message['observed_via']}`")
        lines.append(f"  - Delivery status: `{message.get('delivery_status') or 'unknown'}`")
        recipient_activity = message.get("recipient_activity", {})
        if isinstance(recipient_activity, dict):
            active_targets = recipient_activity.get("active_targets", [])
            inactive_targets = recipient_activity.get("inactive_targets", [])
            if active_targets:
                lines.append(f"  - Active recipients after message: `{active_targets}`")
            if inactive_targets:
                lines.append(f"  - Inactive recipients after message: `{inactive_targets}`")
        content = message.get("content")
        if isinstance(content, str) and content.strip():
            preview = content.strip()
            if len(preview) > TRANSCRIPT_COORDINATION_PREVIEW_CHARS:
                preview = preview[:TRANSCRIPT_COORDINATION_PREVIEW_CHARS] + "..."
            lines.append("  - Content:")
            lines.append("```")
            lines.append(preview)
            lines.append("```")
        lines.append("")

    return "\n".join(lines).strip()


def render_transcript_markdown(transcript: dict[str, Any]) -> str:
    """Render a transcript dict as readable markdown."""
    coordination_messages = transcript.get("coordination_messages", [])
    coordination_summary = None
    if coordination_messages:
        coordination_summary = summarize_coordination_messages(
            coordination_messages,
            agents=transcript.get("agents", {}),
        )

    lines = [
        f"# Experiment: {transcript.get('experiment_name')}",
        f"ID: `{transcript.get('experiment_id')}`",
        "",
        f"**Start**: {transcript.get('start_time')}",
        f"**End**: {transcript.get('end_time')}",
        "",
        "---",
        "",
    ]

    agents = transcript.get("agents", {})
    if isinstance(agents, dict) and agents:
        total_items = transcript.get("total_items")
        if not isinstance(total_items, int):
            total_items = 0
            for agent_data in agents.values():
                if not isinstance(agent_data, dict):
                    continue
                item_count = agent_data.get("item_count")
                if isinstance(item_count, int):
                    total_items += item_count
                    continue
                raw_items = agent_data.get("items", [])
                if isinstance(raw_items, list):
                    total_items += len(raw_items)
        lines.append("## Transcript Summary")
        lines.append("")
        lines.append(
            f"**Agents**: {len(agents)} | "
            f"**Total Items**: {total_items} | "
            f"**Coordination Messages**: {len(coordination_messages)}"
        )
        for agent_id, agent_data in agents.items():
            if not isinstance(agent_data, dict):
                continue
            item_count = agent_data.get("item_count")
            if not isinstance(item_count, int):
                raw_items = agent_data.get("items", [])
                item_count = len(raw_items) if isinstance(raw_items, list) else 0
            lines.append(f"- `{agent_id}`: {item_count} items")
        if coordination_summary is not None:
            recipient_activity_rate = "n/a"
            if coordination_summary["recipient_activity_rate"] is not None:
                recipient_activity_rate = f"{coordination_summary['recipient_activity_rate']:.0%}"
            lines.append(
                f"**Coordination Snapshot**: observed={coordination_summary['observed_messages']}, "
                f"file_backed={coordination_summary['file_backed_messages']}, "
                f"nudges_attempted={coordination_summary['nudge_attempts']}, "
                f"nudges_delivered={coordination_summary['delivered']}, "
                f"recipient_activity={recipient_activity_rate}"
            )
        lines.append("")
        lines.append("---")
        lines.append("")

    for item in _sorted_transcript_items(transcript):
        event_type = item.get("event_type")

        # Skip noise events that carry no behavioral content
        if event_type in (
            "item.delta",       # streaming deltas — item.completed has full content
            "item.started",     # no content
            "rate_limit_event", # telemetry check, not an actual block
        ):
            continue

        timestamp = str(item.get("timestamp", ""))
        ts = timestamp[11:19] if len(timestamp) >= 19 else timestamp
        lines.append(f"## [{ts}] {item.get('agent_id')}")
        lines.append(f"**Event**: `{event_type}`")
        lines.append("")

        data = item.get("data", {})
        if not isinstance(data, dict):
            data = {}

        if event_type == "item.completed":
            item_data = data.get("item", {})
            if not isinstance(item_data, dict):
                item_data = {}
            role = item_data.get("role", item_data.get("kind", "unknown"))
            lines.append(f"**Role**: {role}")

            for part in item_data.get("content", []):
                if not isinstance(part, dict):
                    continue
                if part.get("type") == "text":
                    full_text = str(part.get("text", ""))
                    text = full_text[:TRANSCRIPT_TEXT_PREVIEW_CHARS]
                    if len(full_text) > TRANSCRIPT_TEXT_PREVIEW_CHARS:
                        text += "..."
                    lines.append(f"\n```\n{text}\n```")
                elif part.get("type") in ("tool_call", "tool_use"):
                    tool_name = part.get("name", "unknown")
                    raw_args = part.get(
                        "arguments", part.get("input", {})
                    )
                    if isinstance(raw_args, str):
                        try:
                            tool_args = json.loads(raw_args)
                        except (json.JSONDecodeError, TypeError):
                            tool_args = {}
                    else:
                        tool_args = raw_args or {}
                    lines.append(f"**Tool**: `{tool_name}`")
                    if isinstance(tool_args, dict):
                        # Show description first if present (agent's
                        # reasoning about why it called this tool).
                        desc = tool_args.get("description")
                        if desc:
                            lines.append(
                                f"  description: {str(desc)[:TOOL_INPUT_VALUE_MAX_CHARS]}"
                            )
                        # Render all input parameters.
                        for key, val in tool_args.items():
                            if key == "description":
                                continue  # already shown
                            val_str = str(val)[:TOOL_INPUT_VALUE_MAX_CHARS]
                            if len(str(val)) > TOOL_INPUT_VALUE_MAX_CHARS:
                                val_str += "..."
                            lines.append(f"  {key}: `{val_str}`")
                elif part.get("type") == "tool_result":
                    output = part.get("output", part.get("text", ""))
                    is_error = part.get("is_error", False)
                    if output:
                        output_str = str(output)[:TRANSCRIPT_TOOL_RESULT_PREVIEW_CHARS]
                        if len(str(output)) > TRANSCRIPT_TOOL_RESULT_PREVIEW_CHARS:
                            output_str += "..."
                        label = "**Error Output**" if is_error else "**Output**"
                        lines.append(f"{label}:")
                        lines.append(f"\n```\n{output_str}\n```")
                elif part.get("type") == "file_ref":
                    lines.append(f"**File**: {part.get('action')} `{part.get('path')}`")

        elif event_type == "permission.requested":
            lines.append(f"**Action**: `{data.get('action')}`")

        elif event_type == "permission.resolved":
            resolution = data.get("resolution", "unknown")
            lines.append(f"**Resolution**: {resolution}")

        elif event_type == "question.requested":
            lines.append(f"**Prompt**: {data.get('prompt')}")

        elif event_type == "session.started":
            lines.append("*Session started*")

        elif event_type == "session.ended":
            lines.append("*Session ended*")

        lines.append("")
        lines.append("---")
        lines.append("")
    coord_msgs = coordination_messages
    if coord_msgs:
        lines.append("## Coordination Messages")
        lines.append("")
        summary = coordination_summary or summarize_coordination_messages(
            coord_msgs,
            agents=transcript.get("agents", {}),
        )
        nudge_rate = "n/a"
        if summary["nudge_delivery_rate"] is not None:
            nudge_rate = f"{summary['nudge_delivery_rate']:.0%}"
        recipient_activity_rate = "n/a"
        if summary["recipient_activity_rate"] is not None:
            recipient_activity_rate = f"{summary['recipient_activity_rate']:.0%}"
        lines.append(
            f"**Observed Artifacts**: {summary['observed_messages']} | "
            f"**File-backed**: {summary['file_backed_messages']} | "
            f"**Live Nudges Attempted**: {summary['nudge_attempts']} | "
            f"**Live Nudges Delivered**: {summary['delivered']} | "
            f"**Nudge Rate**: {nudge_rate}"
        )
        lines.append(
            f"**Recipient Activity After Coordination**: "
            f"{summary['recipient_activity_hits']}/{summary['recipient_activity_checks']} | "
            f"**Recipient Activity Rate**: {recipient_activity_rate}"
        )
        lines.append(
            "_Note: these coordination entries are filesystem artifacts observed by the "
            "backend. `Live nudges delivered` only measures follow-up prompt injection "
            "into already-running agent sessions. `Recipient activity` is a heuristic for "
            "downstream uptake: it counts whether a targeted recipient produced later events, "
            "not whether they semantically used the information well._"
        )
        lines.append("")

        for raw_message in coord_msgs:
            message = _coordination_message_to_dict(raw_message)
            timestamp = str(message.get("timestamp", ""))
            ts = timestamp[11:19] if len(timestamp) >= 19 else timestamp
            direction = f"{message.get('sender') or '?'} → {message.get('recipient') or '?'}"
            lines.append(f"- `[{ts}]` **{message.get('message_type')}** {direction}")
            if message.get("source_path"):
                lines.append(f"  - Artifact: `{message['source_path']}`")
            content = message.get("content")
            if isinstance(content, str) and content.strip():
                preview = content.strip()
                if len(preview) > TRANSCRIPT_COORDINATION_PREVIEW_CHARS:
                    preview = preview[:TRANSCRIPT_COORDINATION_PREVIEW_CHARS] + "..."
                lines.append("  - Content Preview:")
                lines.append("```")
                lines.append(preview)
                lines.append("```")
            channel_bits = [
                bit for bit in [
                    message.get("channel_id"),
                    message.get("channel_medium"),
                    message.get("channel_persistence"),
                    message.get("channel_scope"),
                ]
                if isinstance(bit, str) and bit
            ]
            if channel_bits:
                lines.append(f"  - Channel: `{', '.join(channel_bits)}`")
            if message.get("observed_via"):
                lines.append(f"  - Observed via: `{message['observed_via']}`")

            metadata = message.get("metadata", {})
            if not isinstance(metadata, dict):
                metadata = {}
            attempted_targets = metadata.get("delivery_attempted_to", [])
            if attempted_targets:
                lines.append(f"  - Live nudge attempted to: `{attempted_targets}`")

            delivery_status = _message_delivery_status(message)
            if attempted_targets or delivery_status != "not_attempted":
                lines.append(f"  - Live delivery status: `{delivery_status}`")

            lines.append("")

        lines.append("---")
        lines.append("")

    return "\n".join(lines)


def extract_agent_transcript(
    transcript: dict[str, Any],
    agent_id: str,
) -> dict[str, Any] | None:
    """Extract a single agent's transcript from a multi-agent transcript dict.

    Returns a transcript dict with the same top-level structure but only the
    specified agent's items, or None if the agent is not found.
    """
    agents = transcript.get("agents", {})
    if not isinstance(agents, dict) or agent_id not in agents:
        return None

    agent_data = agents[agent_id]
    if not isinstance(agent_data, dict):
        return None

    coordination_messages = [
        msg for msg in transcript.get("coordination_messages", [])
        if isinstance(msg, dict) and (
            msg.get("sender") == agent_id
            or msg.get("recipient") == agent_id
            or msg.get("recipient") == "__all__"
        )
    ]
    items = agent_data.get("items", [])
    if not isinstance(items, list):
        items = []
    tool_calls, tool_errors, tool_names = _count_agent_tools(items)
    direct_messages = sum(1 for msg in coordination_messages if msg.get("recipient") == agent_id)
    sent_messages = sum(1 for msg in coordination_messages if msg.get("sender") == agent_id)
    broadcast_messages = sum(1 for msg in coordination_messages if msg.get("recipient") == "__all__")

    return {
        "view_type": "per-agent",
        "experiment_id": transcript.get("experiment_id"),
        "experiment_name": transcript.get("experiment_name"),
        "start_time": agent_data.get("start_time"),
        "end_time": agent_data.get("end_time"),
        "agent_id": agent_id,
        "agent_summary": {
            "item_count": agent_data.get("item_count", len(items)),
            "tool_calls": tool_calls,
            "tool_errors": tool_errors,
            "tool_breakdown": tool_names,
            "sent_coordination_messages": sent_messages,
            "received_coordination_messages": direct_messages,
            "broadcast_coordination_messages": broadcast_messages,
        },
        "agents": {agent_id: agent_data},
        "total_items": agent_data.get("item_count", len(items)),
        "coordination_messages": coordination_messages,
    }


def render_agent_view_markdown(agent_view: dict[str, Any]) -> str:
    """Render a per-agent judge view with a local summary header."""
    agent_id = agent_view.get("agent_id") or "unknown"
    summary = agent_view.get("agent_summary", {})
    lines = [
        "# Per-Agent View",
        f"Agent: `{agent_id}`",
        "",
    ]

    if isinstance(summary, dict):
        lines.extend(
            [
                "## Agent Summary",
                "",
                f"- Items: `{summary.get('item_count', 0)}`",
                f"- Tool calls: `{summary.get('tool_calls', 0)}`",
                f"- Tool errors: `{summary.get('tool_errors', 0)}`",
            ]
        )
        tool_breakdown = summary.get("tool_breakdown", {})
        if tool_breakdown:
            breakdown_str = ", ".join(
                f"{name}={count}"
                for name, count in sorted(
                    tool_breakdown.items(), key=lambda x: -x[1]
                )
            )
            lines.append(f"- Tool breakdown: `{breakdown_str}`")
        lines.extend(
            [
                f"- Coordination sent: `{summary.get('sent_coordination_messages', 0)}`",
                f"- Coordination received: `{summary.get('received_coordination_messages', 0)}`",
                f"- Broadcast coordination seen: `{summary.get('broadcast_coordination_messages', 0)}`",
                "",
            ]
        )

    lines.append(render_transcript_markdown(agent_view))
    return "\n".join(lines).strip()


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
        with open(path, "w") as f:
            f.write(render_transcript_markdown(self.transcript.to_dict()))
