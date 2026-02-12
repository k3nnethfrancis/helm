"""Experiment lifecycle management.

Orchestrates the complete experiment flow:
1. Setup - create directories, start daemon, create sessions
2. Run - send tasks, stream events, apply orchestrator rules
3. Teardown - terminate sessions, stop daemon, save artifacts
"""

from __future__ import annotations

import asyncio
import json
import shutil
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

from helm.collector import EventCollector
from helm.config import AgentConfig, ExperimentConfig
from helm.coordination import CoordinationBackend, CoordinationMessage, create_backend
from helm.runtime_guard import RuntimeGuard
from helm.sdk import SDKClient, SDKConfig, SDKEvent, SessionConfig


@dataclass
class ExperimentResult:
    """Result of an experiment run."""

    experiment_id: str
    experiment_name: str
    success: bool
    start_time: datetime
    end_time: datetime
    transcript_path: Path | None = None
    error: str | None = None
    agent_stats: dict[str, dict[str, Any]] = field(default_factory=dict)


class Experiment:
    """Manages the lifecycle of a multi-agent experiment."""

    def __init__(
        self,
        config: ExperimentConfig,
        sdk_binary_path: Path,
        experiments_dir: Path,
        on_escalate: Callable[[str, SDKEvent, Any], None] | None = None,
        on_turn_limit: Callable[[str, int, int], tuple[str, int | None]] | None = None,
    ):
        self.config = config
        self.sdk_binary_path = sdk_binary_path
        self.experiments_dir = experiments_dir
        self.on_escalate = on_escalate
        self.on_turn_limit = on_turn_limit

        self.experiment_id = f"{config.name}-{uuid.uuid4().hex[:8]}"
        self.experiment_dir = experiments_dir / self.experiment_id

        self._sdk: SDKClient | None = None
        self._backend: CoordinationBackend | None = None
        self._orchestrator: RuntimeGuard | None = None
        self._collector: EventCollector | None = None
        self._agent_sessions: dict[str, str] = {}  # agent_id -> session_id
        self._stop_event = asyncio.Event()
        self._streams_ended: set[str] = set()
        self._stream_errors: dict[str, str] = {}
        self._start_time: datetime | None = None
        self._end_time: datetime | None = None
        self._task: str | None = None
        self._ended_by_turn_limit = False
        self._escalations: list[dict[str, Any]] = []

        # Per-agent turn limits (None = no limit / run indefinitely)
        self._agent_turn_limits: dict[str, int | None] = {
            a.id: config.limits.max_turns_per_agent
            for a in config.agents
        }

    async def setup(self) -> None:
        """Set up the experiment environment."""
        # Create experiment-owned directories
        self.experiment_dir.mkdir(parents=True, exist_ok=True)
        (self.experiment_dir / "workspace").mkdir(exist_ok=True)
        (self.experiment_dir / "transcripts").mkdir(exist_ok=True)

        # Stage workspace files from config
        await self._stage_workspace_files()

        # Initialize coordination backend (owns coordination/ directories)
        agent_ids = [a.id for a in self.config.agents]
        coord_config = self.config.coordination
        self._backend = create_backend(
            coord_config.mechanism, **coord_config.backend_settings
        )
        coord_backend_config = coord_config.model_dump()
        coord_backend_config["agent_roles"] = {
            a.id: a.role.value if a.role else "peer"
            for a in self.config.agents
        }
        hub = self.config.get_hub_agent()
        coord_backend_config["hub_agent_id"] = hub.id if hub else None
        await self._backend.setup(self.experiment_dir, agent_ids, coord_backend_config)

        # Start SDK daemon
        sdk_config = SDKConfig(binary_path=self.sdk_binary_path)
        self._sdk = SDKClient(sdk_config)
        await self._sdk.start()

        # Initialize collector
        self._collector = EventCollector(self.experiment_id, self.config.name)

        # Initialize orchestrator
        self._orchestrator = RuntimeGuard(
            self.config.orchestrator,
            self._sdk,
            on_escalate=self._handle_escalation,
        )

        # Create sessions for each agent
        await self._create_sessions()

        # Save metadata
        self._save_metadata()

    async def _create_sessions(self) -> None:
        """Create sessions for all agents."""
        if self._sdk is None:
            raise RuntimeError("SDK not initialized")

        # Determine startup order
        if self.config.is_hub_and_spoke():
            # Start coordinator first
            hub = self.config.get_hub_agent()
            if hub:
                await self._create_agent_session(hub)
            for agent in self.config.get_worker_agents():
                await self._create_agent_session(agent)
        else:
            # Peer network - start all concurrently
            await asyncio.gather(
                *[self._create_agent_session(agent) for agent in self.config.agents]
            )

    async def _create_agent_session(self, agent: AgentConfig) -> None:
        """Create a session for a single agent."""
        if self._sdk is None or self._collector is None or self._orchestrator is None:
            raise RuntimeError("Experiment not initialized")

        session_id = f"helm-{self.experiment_id}-{agent.id}"
        session_config = SessionConfig(
            agent="claude",
            permission_mode="bypass",
            cwd=str(self.experiment_dir),
        )

        await self._sdk.create_session(session_id, session_config)
        self._agent_sessions[agent.id] = session_id
        self._collector.register_agent(agent.id, session_id)
        self._orchestrator.register_agent(
            agent.id,
            session_id,
            role=agent.role.value if agent.role else "peer",
        )

    async def _stage_workspace_files(self) -> None:
        """Download or copy workspace files specified in config.

        Entries in limits.workspace_files map destination filename to source.
        Sources can be URLs (http/https) or local filesystem paths.
        """
        workspace = self.experiment_dir / "workspace"
        for filename, source in self.config.limits.workspace_files.items():
            dest = workspace / filename
            dest.parent.mkdir(parents=True, exist_ok=True)

            parsed = urlparse(source)
            if parsed.scheme in ("http", "https"):
                # Download from URL
                import httpx

                async with httpx.AsyncClient(follow_redirects=True) as client:
                    resp = await client.get(source)
                    resp.raise_for_status()
                    dest.write_bytes(resp.content)
            else:
                # Copy local file
                src_path = Path(source).expanduser().resolve()
                if not src_path.exists():
                    raise FileNotFoundError(
                        f"Workspace file source not found: {source}"
                    )
                shutil.copy2(src_path, dest)

    async def run(self, task: str) -> ExperimentResult:
        """Run the experiment with the given task.

        For hub-and-spoke: sends task to coordinator only
        For peer-network: sends task to all agents
        """
        if self._sdk is None:
            raise RuntimeError("Experiment not set up")

        self._task = task
        self._start_time = datetime.now()
        timeout = self.config.limits.duration_seconds()

        try:
            # Prepare initial message with system prompt
            if self.config.is_hub_and_spoke():
                hub = self.config.get_hub_agent()
                if hub:
                    await self._run_agent(hub, task, timeout)
                # Activate workers so their sessions start executing
                for worker in self.config.get_worker_agents():
                    await self._run_agent(
                        worker,
                        "You are now active. Check your task queue for assignments.",
                        timeout,
                    )
            else:
                # Peer network - all agents get the task
                await asyncio.gather(
                    *[
                        self._run_agent(agent, task, timeout)
                        for agent in self.config.agents
                    ]
                )

            # Start coordination backend watcher
            if self._backend and self._sdk:
                await self._backend.start_watching(
                    self._sdk,
                    self._agent_sessions,
                    on_message=self._record_coordination_message,
                )

            # Wait for completion
            await self._wait_for_completion(timeout)

            self._end_time = datetime.now()
            error = self._determine_run_error()
            if error is not None:
                result = self._build_result(success=False, error=error)
                self._save_metadata(result)
                return result
            else:
                result = self._build_result(success=True)
                self._save_metadata(result)
                return result

        except asyncio.TimeoutError:
            self._end_time = datetime.now()
            result = self._build_result(success=False, error="Timeout exceeded")
            self._save_metadata(result)
            return result
        except Exception as e:
            self._end_time = datetime.now()
            result = self._build_result(success=False, error=str(e))
            self._save_metadata(result)
            return result

    async def _run_agent(
        self,
        agent: AgentConfig,
        task: str,
        timeout: float,
    ) -> None:
        """Run a single agent with the given task."""
        if self._sdk is None:
            raise RuntimeError("SDK not initialized")

        session_id = self._agent_sessions[agent.id]

        # Build context-rich message
        context = f"""## Environment
Working directory: {self.experiment_dir}
Your agent ID: {agent.id}
Coordination directory: {self.experiment_dir / 'coordination'}
Workspace directory: {self.experiment_dir / 'workspace'}

"""
        # Prepend system prompt if provided
        if agent.system_prompt:
            context = f"{agent.system_prompt}\n\n---\n\n{context}"

        # Append backend-specific coordination instructions
        if self._backend:
            backend_instructions = self._backend.get_prompt_instructions(agent.id)
            if backend_instructions:
                context += f"\n## Coordination Backend Instructions\n{backend_instructions}\n\n"

        message = f"{context}## Task\n{task}"

        # Start event stream
        asyncio.create_task(self._stream_agent_events(agent.id, session_id))

        # Send the task
        await self._sdk.post_message(session_id, message)

    async def _stream_agent_events(self, agent_id: str, session_id: str) -> None:
        """Stream and process events from an agent."""
        if self._sdk is None or self._collector is None or self._orchestrator is None:
            self._streams_ended.add(agent_id)
            return

        try:
            async for event in self._sdk.stream_events(session_id):
                if self._stop_event.is_set():
                    break

                # Record event
                self._collector.record(session_id, event)

                # Let orchestrator handle intervention
                await self._orchestrator.handle_event(session_id, event)

                # Auto-approve file operations in experiment workspace
                if event.type == "permission.requested":
                    action = event.data.get("action", "")
                    permission_id = event.data.get("permission_id")
                    if permission_id and self._is_safe_action(action):
                        try:
                            await self._sdk.reply_permission(session_id, permission_id, "always")
                        except Exception:
                            pass  # Permission may have already been resolved by bypass mode

                # Check for completion signals
                if self._check_completion_signal(agent_id, event):
                    break

        except Exception as e:
            # Log but don't crash
            print(f"Error streaming events for {agent_id}: {e}")
            self._stream_errors[agent_id] = str(e)
        finally:
            self._streams_ended.add(agent_id)

    def _is_safe_action(self, action: str) -> bool:
        """Check if an action is safe to auto-approve.

        Blocked commands are read from YAML config (limits.blocked_commands),
        not hardcoded. This lets pattern authors control the permission model.
        """
        # Allow file operations within experiment directory
        workspace_path = str(self.experiment_dir)
        if workspace_path in action:
            return True
        # Block commands from YAML config
        blocked = self.config.limits.blocked_commands
        return not any(cmd in action for cmd in blocked)

    def _check_completion_signal(self, agent_id: str, event: SDKEvent) -> bool:
        """Check if an event signals experiment completion."""
        # Check for session end
        if event.type == "session.ended":
            return True

        # Check for done signal file
        if event.type == "item.completed":
            item = event.data.get("item", {})
            for part in item.get("content", []):
                if part.get("type") == "file_ref":
                    path = part.get("path", "")
                    if "signals/done" in path or f"signals/{agent_id}.done" in path:
                        return True

        return False

    def _all_streams_ended(self) -> bool:
        """Check if all agent event streams have terminated."""
        expected = {a.id for a in self.config.agents}
        return expected.issubset(self._streams_ended)

    async def _wait_for_completion(self, timeout: float) -> None:
        """Wait for experiment completion or timeout."""
        start = time.time()

        while time.time() - start < timeout:
            if self._stop_event.is_set():
                break

            # Check if all agents have signaled completion
            if self._all_agents_done():
                break

            # Check if all event streams have ended (timeout, error, or session end)
            if self._all_streams_ended():
                break

            # Check turn limits
            if await self._check_turn_limits():
                break

            await asyncio.sleep(1)

    def _record_coordination_message(self, message: CoordinationMessage) -> None:
        """Route a coordination message from the backend to the collector."""
        if self._collector:
            self._collector.record_coordination(message)

    def _all_agents_done(self) -> bool:
        """Check if all agents have signaled done via the coordination backend."""
        if self._backend:
            agent_ids = [a.id for a in self.config.agents]
            return self._backend.is_complete(agent_ids)
        return False

    async def _check_turn_limits(self) -> bool:
        """Check turn limits per agent. Returns True if experiment should end."""
        if self._orchestrator is None:
            return False

        for agent in self.config.agents:
            if agent.id in self._streams_ended:
                continue
            limit = self._agent_turn_limits.get(agent.id)
            if limit is None:  # No limit (indefinite)
                continue
            turns = self._orchestrator.get_agent_turn_count(agent.id)
            if turns < limit:
                continue

            # Agent hit limit — invoke callback or end experiment
            if self.on_turn_limit:
                action, value = await asyncio.to_thread(
                    self.on_turn_limit, agent.id, turns, limit
                )
            else:
                action, value = "end_experiment", None

            if action == "continue":
                self._agent_turn_limits[agent.id] = None
            elif action == "extend":
                self._agent_turn_limits[agent.id] = turns + (value or 20)
            elif action == "kill_agent":
                session_id = self._agent_sessions.get(agent.id)
                if session_id and self._sdk:
                    try:
                        await self._sdk.terminate_session(session_id)
                    except Exception:
                        pass
                self._streams_ended.add(agent.id)
            elif action == "end_experiment":
                self._ended_by_turn_limit = True
                return True

        return False

    async def teardown(self) -> None:
        """Clean up experiment resources."""
        if self._backend:
            await self._backend.teardown()

        if self._orchestrator:
            self._orchestrator.stop()

        if self._sdk:
            # Terminate all sessions
            for session_id in self._agent_sessions.values():
                try:
                    await self._sdk.terminate_session(session_id)
                except Exception:
                    pass

            await self._sdk.dispose()

        # Save transcript
        if self._collector:
            transcript_path = self.experiment_dir / "transcripts" / "full.json"
            self._collector.save(transcript_path)

            markdown_path = self.experiment_dir / "transcripts" / "full.md"
            self._collector.save_markdown(markdown_path)

    def stop(self) -> None:
        """Signal the experiment to stop."""
        self._stop_event.set()

    def _determine_run_error(self) -> str | None:
        """Determine whether run termination should be considered a failure."""
        if self._stream_errors:
            details = "; ".join(
                f"{agent}: {error}" for agent, error in sorted(self._stream_errors.items())
            )
            return f"Event stream failed: {details}"

        if self._escalations:
            escalation = self._escalations[0]
            reason = escalation.get("reason") or "human input required"
            return (
                "Escalation required human input and execution was paused. "
                f"First escalation: {reason}"
            )

        if self._ended_by_turn_limit:
            return "Turn limit reached; experiment ended before completion."

        if not self._all_agents_done():
            if self._stop_event.is_set():
                return "Experiment stopped before completion signals were observed."
            return "Experiment ended before completion signals were observed."

        return None

    def _handle_escalation(self, agent_id: str, event: SDKEvent, rule: Any) -> None:
        """Handle escalation events by recording and pausing the run."""
        record = {
            "timestamp": datetime.now().isoformat(),
            "agent_id": agent_id,
            "event_type": event.type,
            "reason": rule.reason if getattr(rule, "reason", None) else None,
            "event_data": event.data,
        }
        self._escalations.append(record)

        if self.on_escalate:
            self.on_escalate(agent_id, event, rule)

        # Pause the experiment so a human can inspect and decide next action.
        self._stop_event.set()

    def _save_metadata(self, result: ExperimentResult | None = None) -> None:
        """Save experiment metadata.

        Called twice: once during setup() for initial state, and again after
        run() completes to capture task, timing, and agent stats.
        """
        metadata: dict[str, Any] = {
            "experiment_id": self.experiment_id,
            "experiment_name": self.config.name,
            "pattern": "hub-and-spoke" if self.config.is_hub_and_spoke() else "peer-network",
            "agents": [
                {"id": a.id, "role": a.role.value if a.role else None}
                for a in self.config.agents
            ],
            "limits": {
                "max_duration": self.config.limits.max_duration,
                "max_turns_per_agent": self.config.limits.max_turns_per_agent,
                "max_budget_usd": self.config.limits.max_budget_usd,
            },
            "created_at": datetime.now().isoformat(),
        }

        if self._task is not None:
            metadata["task"] = self._task

        if result is not None:
            metadata["run"] = {
                "success": result.success,
                "start_time": result.start_time.isoformat(),
                "end_time": result.end_time.isoformat(),
                "duration_seconds": (result.end_time - result.start_time).total_seconds(),
                "error": result.error,
                "agent_stats": result.agent_stats,
                "escalations": self._escalations,
                "stream_errors": self._stream_errors,
            }

        with open(self.experiment_dir / "metadata.json", "w") as f:
            json.dump(metadata, f, indent=2)

    def _build_result(
        self,
        success: bool,
        error: str | None = None,
    ) -> ExperimentResult:
        """Build the experiment result."""
        agent_stats = {}
        if self._orchestrator:
            for agent in self.config.agents:
                agent_stats[agent.id] = {
                    "turns": self._orchestrator.get_agent_turn_count(agent.id),
                }

        transcript_path = None
        if self._collector:
            transcript_path = self.experiment_dir / "transcripts" / "full.json"

        return ExperimentResult(
            experiment_id=self.experiment_id,
            experiment_name=self.config.name,
            success=success,
            start_time=self._start_time or datetime.now(),
            end_time=self._end_time or datetime.now(),
            transcript_path=transcript_path,
            error=error,
            agent_stats=agent_stats,
        )


async def run_experiment(
    config_path: Path,
    task: str,
    sdk_binary_path: Path,
    experiments_dir: Path,
    on_escalate: Callable[[str, SDKEvent, Any], None] | None = None,
    on_turn_limit: Callable[[str, int, int], tuple[str, int | None]] | None = None,
) -> ExperimentResult:
    """Run an experiment from a config file."""
    config = ExperimentConfig.from_yaml(config_path)

    experiment = Experiment(
        config=config,
        sdk_binary_path=sdk_binary_path,
        experiments_dir=experiments_dir,
        on_escalate=on_escalate,
        on_turn_limit=on_turn_limit,
    )

    try:
        await experiment.setup()
        result = await experiment.run(task)
        return result
    finally:
        await experiment.teardown()
