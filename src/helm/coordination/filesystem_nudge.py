"""Filesystem + nudge coordination backend.

Watches the coordination directory for new files, classifies them by
path convention, and delivers nudge messages to the appropriate agents
via the SDK. This is the default backend — it makes the existing
filesystem-based coordination protocol active rather than passive.
"""

from __future__ import annotations

import asyncio
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from helm.coordination.base import CoordinationMessage, MessageType, OnMessageCallback
from helm.sdk import SDKClient


class FilesystemNudgeBackend:
    """Coordination backend that polls the filesystem and nudges agents.

    Agents still coordinate via files (the YAML prompts tell them how).
    This backend watches for new files and proactively nudges recipients,
    solving the "poll once and go idle" problem.
    """

    # Max content bytes to include in a nudge (full file if under this)
    MAX_NUDGE_CONTENT = 4000

    def __init__(self, poll_interval: float = 2.0, content_preview_length: int = 200):
        self._poll_interval = poll_interval
        self._content_preview_length = content_preview_length

        self._experiment_dir: Path | None = None
        self._coord_dir: Path | None = None
        self._workspace_dir: Path | None = None
        self._agents: list[str] = []
        self._config: dict[str, Any] = {}
        self._is_hub_spoke: bool = False
        self._agent_roles: dict[str, str] = {}
        self._hub_agent_id: str | None = None

        # Watched artifact patterns in workspace/ that trigger nudges
        self._workspace_watches: list[str] = []

        # Watcher state
        self._sdk: SDKClient | None = None
        self._agent_sessions: dict[str, str] = {}
        self._on_message: OnMessageCallback | None = None
        self._known_files: set[str] = set()
        self._known_workspace_files: set[str] = set()
        self._poll_task: asyncio.Task | None = None
        self._running = False

    async def setup(
        self,
        experiment_dir: Any,
        agents: list[str],
        config: dict[str, Any],
    ) -> None:
        """Create coordination directories from config paths."""
        self._experiment_dir = Path(experiment_dir)
        self._agents = agents
        self._config = config
        self._agent_roles = {
            agent_id: (role or "peer")
            for agent_id, role in config.get("agent_roles", {}).items()
        }
        self._hub_agent_id = config.get("hub_agent_id")

        paths = config.get("paths", {})
        base = paths.get("base", "coordination/")
        self._coord_dir = self._experiment_dir / base

        # Create coordination base dir
        self._coord_dir.mkdir(parents=True, exist_ok=True)

        # Create all configured subdirectories
        for key, path_str in paths.items():
            if key == "base" or path_str is None:
                continue
            # Skip non-directory paths (e.g., state.json)
            if "." in Path(path_str).name:
                continue
            (self._experiment_dir / path_str).mkdir(parents=True, exist_ok=True)

        # Detect hub-and-spoke: check if tasks/ path is configured
        tasks_path = paths.get("tasks")
        if tasks_path:
            self._is_hub_spoke = True
            # Create per-agent task directories for hub-and-spoke
            tasks_dir = self._experiment_dir / tasks_path
            for agent_id in agents:
                (tasks_dir / agent_id / "pending").mkdir(parents=True, exist_ok=True)
                (tasks_dir / agent_id / "completed").mkdir(parents=True, exist_ok=True)

        # Set up workspace watching
        self._workspace_dir = self._experiment_dir / "workspace"
        self._workspace_watches = config.get("workspace_watches", [])

        # Snapshot existing files so we only react to new ones
        self._known_files = self._scan_all_files()
        self._known_workspace_files = self._scan_workspace_files()

    def get_prompt_instructions(self, agent_id: str) -> str:
        """Return empty string — existing YAML prompts already have filesystem instructions."""
        return ""

    async def start_watching(
        self,
        sdk: SDKClient,
        agent_sessions: dict[str, str],
        on_message: OnMessageCallback,
    ) -> None:
        """Launch the async poll loop."""
        self._sdk = sdk
        self._agent_sessions = agent_sessions
        self._on_message = on_message
        self._running = True
        self._poll_task = asyncio.create_task(self._poll_loop())

    async def stop_watching(self) -> None:
        """Stop the poll loop."""
        self._running = False
        if self._poll_task and not self._poll_task.done():
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
            self._poll_task = None
        # Final best-effort flush so late files (often *.done) are captured
        # in coordination_messages before teardown.
        await self._poll_once(deliver_nudges=False)

    def is_complete(self, agents: list[str]) -> bool:
        """Check signal files for completion."""
        if self._experiment_dir is None:
            return False

        paths = self._config.get("paths", {})
        signals_path = paths.get("signals")
        if not signals_path:
            return False

        signals_dir = self._experiment_dir / signals_path

        if not signals_dir.exists():
            return False

        if self._is_hub_spoke:
            # Hub-and-spoke: done when coordinator writes signals/done
            return (signals_dir / "done").exists()
        else:
            # Peer network: done when all agents write {agent_id}.done
            return all((signals_dir / f"{aid}.done").exists() for aid in agents)

    async def teardown(self) -> None:
        """Stop watching and release references."""
        await self.stop_watching()
        self._sdk = None
        self._agent_sessions = {}

    # ── Internal ──────────────────────────────────────────────────

    def _scan_all_files(self) -> set[str]:
        """Scan the coordination directory tree and return all file paths."""
        if self._coord_dir is None or not self._coord_dir.exists():
            return set()
        return {str(p) for p in self._coord_dir.rglob("*") if p.is_file()}

    def _scan_workspace_files(self) -> set[str]:
        """Scan workspace for watched artifact patterns."""
        if not self._workspace_dir or not self._workspace_dir.exists():
            return set()
        if not self._workspace_watches:
            return set()
        found: set[str] = set()
        for pattern in self._workspace_watches:
            found.update(str(p) for p in self._workspace_dir.glob(pattern) if p.is_file())
        return found

    async def _poll_loop(self) -> None:
        """Poll for new files and process them."""
        while self._running:
            try:
                await self._poll_once(deliver_nudges=True)
            except Exception as e:
                # Log but don't crash the poll loop
                print(f"[coordination] poll error: {e}")

            await asyncio.sleep(self._poll_interval)

    async def _poll_once(self, *, deliver_nudges: bool) -> None:
        """Process newly observed coordination/workspace files once."""
        # Scan coordination directory
        current_files = self._scan_all_files()
        new_files = current_files - self._known_files
        for file_path in sorted(new_files):
            await self._handle_new_file(Path(file_path), deliver_nudges=deliver_nudges)
        self._known_files = current_files

        # Scan workspace for watched artifacts
        if not self._workspace_watches:
            return

        current_ws = self._scan_workspace_files()
        new_ws = current_ws - self._known_workspace_files
        for file_path in sorted(new_ws):
            await self._handle_workspace_file(
                Path(file_path),
                deliver_nudges=deliver_nudges,
            )
        self._known_workspace_files = current_ws

    async def _handle_new_file(self, file_path: Path, *, deliver_nudges: bool) -> None:
        """Classify a new file and deliver appropriate nudge."""
        if self._coord_dir is None:
            return

        relative = str(file_path.relative_to(self._coord_dir))
        full_content = self._read_text(file_path)
        nudge_content = self._truncate_for_nudge(full_content, file_path.name)
        now = datetime.now()

        # Classify by path convention
        msg_type, sender, recipient = self._classify_file(relative, file_path.name)

        message = CoordinationMessage(
            timestamp=now,
            sender=sender,
            recipient=recipient,
            message_type=msg_type,
            content=full_content,
            source_path=relative,
        )

        # Deliver nudge if we have a target
        # Skip completion signals in hub-spoke (signals/done = experiment over),
        # but deliver them in peer networks (agent.done = notify peers)
        skip_nudge = msg_type == MessageType.COMPLETION_SIGNAL and self._is_hub_spoke
        if deliver_nudges and recipient and not skip_nudge:
            nudge_text = self._build_nudge_text(message, nudge_content)
            message.nudge_text = nudge_text

            if recipient == "__all__":
                for agent_id in self._agents:
                    if agent_id != sender:
                        await self._deliver_nudge(agent_id, nudge_text)
                message.delivered = True
                message.delivery_timestamp = datetime.now()
            elif recipient in self._agent_sessions:
                await self._deliver_nudge(recipient, nudge_text)
                message.delivered = True
                message.delivery_timestamp = datetime.now()

        # Report to collector
        if self._on_message:
            self._on_message(message)

    async def _handle_workspace_file(self, file_path: Path, *, deliver_nudges: bool) -> None:
        """Handle a new watched workspace artifact — notify all agents."""
        if self._experiment_dir is None:
            return

        relative = str(file_path.relative_to(self._experiment_dir))
        full_content = self._read_text(file_path)
        nudge_content = self._truncate_for_nudge(full_content, file_path.name)
        now = datetime.now()

        message = CoordinationMessage(
            timestamp=now,
            sender=None,
            recipient="__all__",
            message_type=MessageType.STATUS_UPDATE,
            content=full_content,
            source_path=relative,
        )

        nudge_text = (
            f"[Artifact Created] {relative}\n\n"
            f"A new file has appeared in the workspace. Here is its content:\n\n"
            f"---\n{nudge_content}\n---\n\n"
            f"Continue your work based on this new information."
        )
        if deliver_nudges:
            message.nudge_text = nudge_text
            for agent_id in self._agents:
                await self._deliver_nudge(agent_id, nudge_text)
            message.delivered = True
            message.delivery_timestamp = datetime.now()

        if self._on_message:
            self._on_message(message)

    def _classify_file(
        self, relative_path: str, filename: str
    ) -> tuple[MessageType, str | None, str | None]:
        """Classify a file by its path into (type, sender, recipient).

        Path conventions:
            tasks/{agent}/pending/*     → TASK_ASSIGNMENT, hub→agent
            tasks/{agent}/completed/*   → STATUS_UPDATE, agent→hub
            status/{agent}.json         → STATUS_UPDATE, agent→hub
            messages/*-{sender}-{recipient}.md → PEER_MESSAGE, sender→recipient
            signals/done                → COMPLETION_SIGNAL
            signals/{agent}.done        → COMPLETION_SIGNAL
            decisions/*                 → DECISION, hub→all workers
            blocked/{agent}.*           → QUESTION, agent→hub
            questions/*                 → QUESTION, agent→hub
            reviews/*                   → PEER_MESSAGE, reviewer→author
        """
        parts = relative_path.replace("\\", "/").split("/")

        # tasks/{agent}/pending/* → task assignment to that agent
        if len(parts) >= 3 and parts[0] == "tasks" and parts[2] == "pending":
            return MessageType.TASK_ASSIGNMENT, self._find_hub(), parts[1]

        # tasks/{agent}/completed/* → status update from that agent
        if len(parts) >= 3 and parts[0] == "tasks" and parts[2] == "completed":
            return MessageType.STATUS_UPDATE, parts[1], self._find_hub()

        # status/{agent}.json → status update (hub in hub-spoke, all peers otherwise)
        if parts[0] == "status" and filename.endswith(".json"):
            agent_id = filename.rsplit(".", 1)[0]
            return MessageType.STATUS_UPDATE, agent_id, self._find_recipient_or_all()

        # messages/*-{sender}-{recipient}.md → peer message
        if parts[0] == "messages" and filename.endswith(".md"):
            sender, recipient = self._parse_message_filename(filename)
            return MessageType.PEER_MESSAGE, sender, recipient

        # signals/done or signals/{agent}.done → completion
        if parts[0] == "signals":
            agent_id = None
            if filename != "done":
                agent_id = filename.rsplit(".", 1)[0]
            if self._is_hub_spoke:
                return MessageType.COMPLETION_SIGNAL, agent_id, None
            else:
                return MessageType.COMPLETION_SIGNAL, agent_id, "__all__"

        # decisions/* → decision from hub to all workers
        if parts[0] == "decisions":
            return MessageType.DECISION, self._find_hub(), "__all__"

        # blocked/{agent}.md → question/block from agent (hub or all peers)
        if parts[0] == "blocked":
            agent_id = filename.rsplit(".", 1)[0]
            return MessageType.QUESTION, agent_id, self._find_recipient_or_all()

        # questions/* → question to coordinator (hub or all peers)
        if parts[0] == "questions":
            return MessageType.QUESTION, None, self._find_recipient_or_all()

        # reviews/* → peer message from reviewer to all peers
        if parts[0] == "reviews":
            return MessageType.PEER_MESSAGE, None, "__all__"

        # Unknown file type
        return MessageType.STATUS_UPDATE, None, None

    def _parse_message_filename(self, filename: str) -> tuple[str | None, str | None]:
        """Parse sender and recipient from message filename.

        Expected format: {timestamp}-{sender}-{recipient}.md
        E.g.: 20260207-143000-researcher-implementer.md
              20260207-143000-reviewer-all.md (broadcast)
        """
        stem = filename.rsplit(".", 1)[0]  # Remove .md
        # Try to match against known agent IDs
        for agent_id in self._agents:
            for other_id in self._agents:
                if agent_id == other_id:
                    continue
                pattern = f"-{agent_id}-{other_id}"
                if pattern in stem:
                    return agent_id, other_id
            # Check for broadcast pattern: -{agent}-all
            if f"-{agent_id}-all" in stem:
                return agent_id, "__all__"
        return None, None

    def _find_hub(self) -> str | None:
        """Find the hub agent from explicit config/roles."""
        if not self._is_hub_spoke:
            return None

        if self._hub_agent_id and self._hub_agent_id in self._agents:
            return self._hub_agent_id

        for agent_id in self._agents:
            if self._agent_roles.get(agent_id, "").lower() == "hub":
                return agent_id

        if self._agents:
            # Backward-compatible fallback when no role metadata is available.
            return self._agents[0]
        return None

    def _find_recipient_or_all(self) -> str:
        """Find the hub agent, or '__all__' for peer networks."""
        hub = self._find_hub()
        return hub if hub else "__all__"

    def _read_preview(self, file_path: Path) -> str:
        """Read a preview of a file's content."""
        try:
            text = file_path.read_text(errors="replace")
            if len(text) > self._content_preview_length:
                return text[: self._content_preview_length] + "..."
            return text
        except Exception:
            return ""

    def _read_text(self, file_path: Path) -> str:
        """Read full file content for transcript capture."""
        try:
            return file_path.read_text(errors="replace")
        except Exception:
            return ""

    def _truncate_for_nudge(self, text: str, filename: str) -> str:
        """Cap message content when injecting it into agent context."""
        if len(text) <= self.MAX_NUDGE_CONTENT:
            return text
        return (
            text[: self.MAX_NUDGE_CONTENT]
            + f"\n\n[... truncated at {self.MAX_NUDGE_CONTENT} chars — read full file at {filename}]"
        )

    def _build_nudge_text(self, message: CoordinationMessage, full_content: str) -> str:
        """Build the text injected into an agent's conversation as a user turn.

        Unlike the old approach (a pointer saying "check this file"), this
        delivers the actual content so the agent can act on it immediately.
        """
        type_label = message.message_type.value.replace("_", " ").title()
        parts: list[str] = []

        # Header
        header = f"[Coordination] {type_label}"
        if message.sender:
            header += f" from {message.sender}"
        parts.append(header)

        if message.source_path:
            parts.append(f"File: {message.source_path}")

        # Deliver actual content inline
        if full_content.strip():
            parts.append("")
            parts.append(full_content)

        # Brief instruction
        parts.append("")
        parts.append("Act on this information and continue your work.")

        return "\n".join(parts)

    async def _deliver_nudge(self, agent_id: str, nudge_text: str) -> None:
        """Send a nudge message to an agent via the SDK."""
        if self._sdk is None:
            return

        session_id = self._agent_sessions.get(agent_id)
        if not session_id:
            return

        try:
            await self._sdk.post_message(session_id, nudge_text)
        except Exception as e:
            print(f"[coordination] nudge delivery failed for {agent_id}: {e}")
