"""Experiment lifecycle management.

Orchestrates the complete experiment flow:
1. Setup - create directories, start daemon, create sessions
2. Run - send tasks, stream events, apply orchestrator rules
3. Teardown - terminate sessions, stop daemon, save artifacts
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

from helm.benchmarks import get_adapter
from helm.benchmarks.swebench_workspace import canonical_workspace_repo, stage_repo_in_workspace
from helm.collector import EventCollector
from helm.config import AgentConfig, ExperimentConfig
from helm.coordination import CoordinationBackend, CoordinationMessage, create_backend
from helm.runtime_guard import RuntimeGuard
from helm.run_data import save_run_data
from helm.sdk import (
    HeadlessCLIClient, SDKClient, SDKConfig, SDKEvent, SessionConfig,
    _HARNESS_ADAPTERS,
)
from helm.topologies import COORDINATION_FAMILY_LABELS


@dataclass
class ExperimentResult:
    """Result of an experiment run."""

    experiment_id: str
    experiment_name: str
    success: bool
    outcome: str
    termination_reason: str
    system_failure: bool
    start_time: datetime
    end_time: datetime
    transcript_path: Path | None = None
    message: str | None = None
    error: str | None = None
    agent_stats: dict[str, dict[str, Any]] = field(default_factory=dict)


@dataclass(frozen=True)
class ExperimentOutcome:
    """Structured outcome for the end of a run."""

    success: bool
    outcome: str
    termination_reason: str
    system_failure: bool
    message: str | None = None
    error: str | None = None


class Experiment:
    """Manages the lifecycle of a multi-agent experiment."""

    def __init__(
        self,
        config: ExperimentConfig,
        sdk_binary_path: Path,
        experiments_dir: Path,
        on_escalate: Callable[[str, SDKEvent, Any], None] | None = None,
        on_turn_limit: Callable[[str, int, int], tuple[str, int | None]] | None = None,
        use_direct_cli: bool | None = None,
    ):
        self.config = config
        self.sdk_binary_path = sdk_binary_path
        self.experiments_dir = experiments_dir
        self.on_escalate = on_escalate
        self.on_turn_limit = on_turn_limit
        self._use_direct_cli = use_direct_cli

        self.experiment_id = f"{config.name}-{uuid.uuid4().hex[:8]}"
        self.experiment_dir = experiments_dir / self.experiment_id

        self._sdk: SDKClient | HeadlessCLIClient | None = None
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
        self._benchmark_workdir: Path | None = None

        # Per-agent turn limits (None = no limit / run indefinitely)
        self._agent_turn_limits: dict[str, int | None] = {
            a.id: config.limits.max_turns_per_agent
            for a in config.agents
        }

    # Known harness label → SDK agent ID mappings.
    # Unknown labels pass through as-is; the SDK validates them.
    HARNESS_ALIASES: dict[str, str] = {
        # Anthropic
        "claude": "claude",
        "claude-code": "claude",
        # OpenAI
        "codex": "codex",
        "openai-codex": "codex",
        "codex-cli": "codex",
        # Open-source / third-party
        "opencode": "opencode",
        "amp": "amp",
        "aider": "aider",
    }

    def _resolve_session_agent(self, harness: str) -> str:
        """Resolve pattern `harness` into the SDK `agent` identifier.

        Helm keeps `harness` labels human-friendly (`claude-code`, etc.) while the
        SDK expects concrete agent IDs (for example `claude`).

        Known aliases are mapped via HARNESS_ALIASES. Unknown labels are passed
        through as-is — the SDK validates whether the agent ID is supported.
        """
        normalized = harness.strip().lower()
        if not normalized:
            return "claude"

        if normalized in self.HARNESS_ALIASES:
            return self.HARNESS_ALIASES[normalized]

        # Fallback: treat "*-code" as "<name>" for generic bring-your-own labels.
        if normalized.endswith("-code"):
            candidate = normalized[:-5]
            if candidate:
                return self.HARNESS_ALIASES.get(candidate, candidate)

        # Pass through as-is and let SDK validate/accept it.
        return normalized

    def _should_use_direct_cli(self) -> bool:
        """Decide whether to use HeadlessCLIClient instead of the SDK daemon.

        Auto-selects HeadlessCLIClient when all agents have a registered
        harness adapter (claude, codex, etc.).  Falls back to the SDK
        daemon only for unknown harnesses.
        Can be overridden via the ``use_direct_cli`` constructor parameter.
        """
        if self._use_direct_cli is not None:
            return self._use_direct_cli
        return all(
            self._resolve_session_agent(a.harness) in _HARNESS_ADAPTERS
            for a in self.config.agents
        )

    async def setup(self) -> None:
        """Set up the experiment environment."""
        # Create experiment-owned directories
        self.experiment_dir.mkdir(parents=True, exist_ok=True)
        (self.experiment_dir / "workspace").mkdir(exist_ok=True)
        (self.experiment_dir / "transcripts").mkdir(exist_ok=True)

        # Stage workspace files from config
        await self._stage_workspace_files()
        await self._prepare_benchmark_workspace()

        # Initialize coordination backend (owns coordination/ directories)
        agent_ids = [a.id for a in self.config.agents]
        coord_config = self.config.coordination
        mechanism_str = (
            coord_config.mechanism.value
            if hasattr(coord_config.mechanism, "value")
            else str(coord_config.mechanism)
        )
        self._backend = create_backend(
            mechanism_str, **coord_config.backend_settings
        )
        coord_backend_config = coord_config.model_dump()
        coord_backend_config["agent_roles"] = {
            a.id: a.role.value if a.role else "peer"
            for a in self.config.agents
        }
        hub = self.config.get_hub_agent()
        coord_backend_config["hub_agent_id"] = hub.id if hub else None
        coord_backend_config["experiment_id"] = self.experiment_id
        coord_backend_config["architecture_family"] = self._architecture_family()
        coord_backend_config["coordination_family"] = self._coordination_family_label()
        coord_backend_config["agent_policies"] = self._build_agent_policies()
        await self._backend.setup(self.experiment_dir, agent_ids, coord_backend_config)

        # Write topology enforcement config for helm-agent CLI
        self._write_helm_config()

        # Select agent backend
        if self._should_use_direct_cli():
            self._sdk = HeadlessCLIClient()
        else:
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
        session_agent = self._resolve_session_agent(agent.harness)
        # Get MCP config path from broker backend if available
        mcp_path = None
        if hasattr(self._backend, "get_mcp_config_path"):
            mcp_path = self._backend.get_mcp_config_path(agent.id)

        session_config = SessionConfig(
            agent=session_agent,
            permission_mode="bypass",
            model=agent.model,
            cwd=str(self._session_working_directory()),
            disallowed_tools=agent.disallowed_tools,
            mcp_config_path=mcp_path,
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

    async def _prepare_benchmark_workspace(self) -> None:
        """Stage benchmark-specific workspace state before agents start."""
        benchmark = self.config.benchmark
        if benchmark is None or benchmark.adapter != "swebench":
            self._benchmark_workdir = None
            return

        row = self._resolve_benchmark_example_metadata()
        repo = row.get("repo")
        base_commit = row.get("base_commit")
        if not isinstance(repo, str) or not repo.strip():
            raise ValueError("SWE-bench benchmark example metadata missing repo")
        if not isinstance(base_commit, str) or not base_commit.strip():
            raise ValueError("SWE-bench benchmark example metadata missing base_commit")

        self._benchmark_workdir = stage_repo_in_workspace(
            repo.strip(),
            base_commit.strip(),
            self.experiment_dir,
        )

    def _resolve_benchmark_example_metadata(self) -> dict[str, Any]:
        """Load benchmark example metadata for the selected run."""
        benchmark = self.config.benchmark
        if benchmark is None:
            return {}
        if benchmark.example_metadata:
            return dict(benchmark.example_metadata)

        adapter = get_adapter(benchmark.adapter)
        examples = adapter.load_examples(benchmark, limit=1)
        if not examples:
            raise ValueError(
                f"No benchmark example found for adapter={benchmark.adapter} "
                f"and ids={benchmark.selected_example_ids()}"
            )
        metadata = dict(examples[0].metadata)
        benchmark.example_metadata = metadata
        return metadata

    def _architecture_family(self) -> str:
        """Infer the architecture family for policy/config generation."""
        matrix = self.config.metadata.matrix
        if matrix and matrix.architecture_family:
            return matrix.architecture_family

        normalized = self.config.name.lower()
        for family in (
            "single",
            "independent",
            "centralized",
            "decentralized",
            "hybrid",
            "delegating",
        ):
            if family in normalized:
                return family
        return "unknown"

    def _coordination_family_label(self) -> str:
        """Return the coordination-family label used in metadata exports."""
        matrix = self.config.metadata.matrix
        if matrix and matrix.coordination_family:
            return matrix.coordination_family

        family = self._architecture_family()
        return COORDINATION_FAMILY_LABELS.get(family, "unknown")

    def _build_agent_policies(self) -> dict[str, dict[str, Any]]:
        """Build the canonical per-agent coordination policy for this run."""
        family = self._architecture_family()
        hub = self.config.get_hub_agent()
        hub_id = hub.id if hub else None
        agent_ids = [agent.id for agent in self.config.agents]
        worker_ids = [agent_id for agent_id in agent_ids if agent_id != hub_id]

        policies: dict[str, dict[str, Any]] = {}
        for agent in self.config.agents:
            role = agent.role.value if agent.role else "peer"
            if agent.can_message is not None:
                can_message = list(agent.can_message)
            elif family in ("centralized", "independent", "delegating") and hub_id:
                can_message = worker_ids if agent.id == hub_id else [hub_id]
            elif family in ("decentralized", "hybrid"):
                can_message = [peer_id for peer_id in agent_ids if peer_id != agent.id]
            else:
                can_message = []

            policies[agent.id] = {
                "role": role,
                "can_spawn": family == "delegating" and agent.id == hub_id,
                "can_signal_done": agent.id == hub_id or hub_id is None,
                "can_message": can_message,
            }

        return policies

    def _write_helm_config(self) -> None:
        """Write .helm-config.json for the helm-agent CLI to read."""
        coord_dir = self.experiment_dir / "coordination"
        coord_dir.mkdir(parents=True, exist_ok=True)
        family = self._architecture_family()
        agents_config = self._build_agent_policies()

        config_data = {
            "family": family,
            "experiment_id": self.experiment_id,
            "harness": self.config.agents[0].harness if self.config.agents else "claude-code",
            "agents": agents_config,
            "disallowed_tools_base": ["Agent", "TeamCreate", "SendMessage"],
            "max_spawn_depth": 1,
        }

        config_path = coord_dir / ".helm-config.json"
        with open(config_path, "w") as f:
            json.dump(config_data, f, indent=2)

    def _session_working_directory(self) -> Path:
        """Return the working directory that agent sessions should start in."""
        return self._benchmark_workdir or self.experiment_dir

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
                        "You are now active.",
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
            outcome = self._determine_run_outcome()
            result = self._build_result(
                success=outcome.success,
                outcome=outcome.outcome,
                termination_reason=outcome.termination_reason,
                system_failure=outcome.system_failure,
                message=outcome.message,
                error=outcome.error,
            )
            self._save_metadata(result)
            return result

        except asyncio.TimeoutError:
            self._end_time = datetime.now()
            result = self._build_result(
                success=False,
                outcome="incomplete",
                termination_reason="timeout",
                system_failure=False,
                message="Timeout reached before completion signals were observed.",
            )
            self._save_metadata(result)
            return result
        except Exception as e:
            self._end_time = datetime.now()
            result = self._build_result(
                success=False,
                outcome="failed",
                termination_reason="exception",
                system_failure=True,
                message="Experiment failed with an unexpected exception.",
                error=str(e),
            )
            self._save_metadata(result)
            return result

    async def _run_agent(
        self,
        agent: AgentConfig,
        task: str,
        timeout: float,
    ) -> None:
        """Run a single agent with the given task.

        Prompt assembly order:
        1. shared_context (from experiment config — all agents get this)
        2. agent context (per-agent role/instructions)
        3. agent private_context (hidden, e.g. adversarial objectives)
        4. ## Environment (framework-injected: paths, agent ID)
        5. ## Agents (framework-injected: peer list)
        6. ## Task (the actual work)
        """
        if self._sdk is None:
            raise RuntimeError("SDK not initialized")

        session_id = self._agent_sessions[agent.id]
        working_dir = self._session_working_directory()

        sections: list[str] = []

        # 1. Shared context (all agents get the same text)
        if self.config.shared_context:
            sections.append(self.config.shared_context.strip())

        # 2. Agent-specific context (role, instructions)
        agent_context = agent.effective_context()
        if agent_context:
            sections.append(agent_context.strip())

        # 3. Private context (hidden from other agents)
        if agent.private_context:
            sections.append(agent.private_context.strip())

        # 4. Environment (framework-injected)
        env_lines = [
            "## Environment",
            f"Working directory: {working_dir}",
            f"Your agent ID: {agent.id}",
        ]
        if self._benchmark_workdir is not None:
            env_lines.append(
                f"Repository: {self._benchmark_workdir}"
            )
        sections.append("\n".join(env_lines))

        # 5. Agents (framework-injected peer list)
        peers: list[str] = []
        for a in self.config.agents:
            if a.id == agent.id:
                continue
            role_label = a.role.value if a.role else "peer"
            peers.append(f"- {a.id} ({role_label})")
        if peers:
            sections.append("## Agents\n" + "\n".join(peers))

        # 6. Task
        sections.append(f"## Task\n{task}")

        message = "\n\n".join(sections)

        await self._sdk.post_message(session_id, message)
        asyncio.create_task(self._stream_agent_events(agent.id, session_id))

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
            for agent_id, session_id in self._agent_sessions.items():
                try:
                    await self._sdk.terminate_session(session_id)
                except Exception as e:
                    logger.debug(
                        "Session termination failed for agent %s (session %s): %s",
                        agent_id,
                        session_id,
                        e,
                    )

            await self._sdk.dispose()

        # Save transcript
        if self._collector:
            transcript_path = self.experiment_dir / "transcripts" / "full.json"
            self._collector.save(transcript_path)

            markdown_path = self.experiment_dir / "transcripts" / "full.md"
            self._collector.save_markdown(markdown_path)

        # Save a versioned run-data contract for downstream analysis/training.
        try:
            save_run_data(self.experiment_dir)
        except Exception as e:
            print(f"Warning: failed to save run_data.json: {e}")

    def stop(self) -> None:
        """Signal the experiment to stop."""
        self._stop_event.set()

    def _determine_run_outcome(self) -> ExperimentOutcome:
        """Determine structured run outcome and whether it is a system failure."""
        if self._stream_errors:
            details = "; ".join(
                f"{agent}: {error}" for agent, error in sorted(self._stream_errors.items())
            )
            return ExperimentOutcome(
                success=False,
                outcome="failed",
                termination_reason="stream_error",
                system_failure=True,
                message=f"Event stream failed: {details}",
                error=f"Event stream failed: {details}",
            )

        if self._escalations:
            escalation = self._escalations[0]
            reason = escalation.get("reason") or "human input required"
            return ExperimentOutcome(
                success=False,
                outcome="paused",
                termination_reason="human_escalation",
                system_failure=False,
                message=(
                    "Escalation required human input and execution was paused. "
                    f"First escalation: {reason}"
                ),
            )

        if self._ended_by_turn_limit:
            return ExperimentOutcome(
                success=False,
                outcome="incomplete",
                termination_reason="turn_limit",
                system_failure=False,
                message="Turn limit reached before completion signals were observed.",
            )

        if not self._all_agents_done():
            if self._stop_event.is_set():
                return ExperimentOutcome(
                    success=False,
                    outcome="incomplete",
                    termination_reason="stopped",
                    system_failure=False,
                    message="Experiment stopped before completion signals were observed.",
                )
            return ExperimentOutcome(
                success=False,
                outcome="incomplete",
                termination_reason="missing_completion_signal",
                system_failure=False,
                message="Experiment ended before completion signals were observed.",
            )

        return ExperimentOutcome(
            success=True,
            outcome="completed",
            termination_reason="completion_signal",
            system_failure=False,
            message="Run reached completion signals.",
        )

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
            "pattern": self.config.topology_label(),
            "matrix": self.config.matrix_metadata(),
            "paired_evaluation": self.config.paired_evaluation_metadata(),
            "agents": [
                {
                    "id": a.id,
                    "role": a.role.value if a.role else None,
                    "harness": a.harness,
                    "model": a.model,
                }
                for a in self.config.agents
            ],
            "evaluation": {
                "dimensions": self.config.evaluation.dimensions,
                "judge": self.config.evaluation.judge.model_dump(),
            },
            "orchestrator": {
                "role": self.config.orchestrator.role,
                "rules": [
                    rule.model_dump(by_alias=True)
                    for rule in self.config.orchestrator.rules
                ],
            },
            "coordination": self.config.coordination.model_dump(),
            "limits": {
                "max_duration": self.config.limits.max_duration,
                "max_turns_per_agent": self.config.limits.max_turns_per_agent,
                "max_budget_usd": self.config.limits.max_budget_usd,
                "blocked_commands": self.config.limits.blocked_commands,
                "workspace_files": self.config.limits.workspace_files,
            },
            "created_at": datetime.now().isoformat(),
        }

        if self.config.benchmark is not None:
            selected_example_ids = self.config.benchmark.selected_example_ids()
            metadata["benchmark"] = {
                "adapter": self.config.benchmark.adapter,
                "id": self.config.benchmark.benchmark_id,
                "dataset_path": self.config.benchmark.dataset_path,
                "split": self.config.benchmark.split,
                "seed": self.config.benchmark.seed,
                "example_id": self.config.benchmark.example_id,
                "example_ids": selected_example_ids,
                "max_examples": self.config.benchmark.max_examples,
                "example_metadata": self.config.benchmark.example_metadata,
                "verifier": self.config.benchmark.verifier,
                "workspace_repo": (
                    str(canonical_workspace_repo(self.experiment_dir))
                    if self._benchmark_workdir is not None
                    else None
                ),
            }

        if self._task is not None:
            metadata["task"] = self._task

        if result is not None:
            benchmark_run = None
            if self.config.benchmark is not None:
                selected_example_ids = self.config.benchmark.selected_example_ids()
                benchmark_run = {
                    "adapter": self.config.benchmark.adapter,
                    "benchmark_id": self.config.benchmark.benchmark_id,
                    "split": self.config.benchmark.split,
                    "seed": self.config.benchmark.seed,
                    "verifier_mode": self.config.benchmark.verifier_mode(),
                    "selected_example_id": (
                        selected_example_ids[0]
                        if len(selected_example_ids) == 1
                        else None
                    ),
                    "configured_example_ids": selected_example_ids,
                }

            metadata["run"] = {
                "success": result.success,
                "outcome": result.outcome,
                "termination_reason": result.termination_reason,
                "system_failure": result.system_failure,
                "start_time": result.start_time.isoformat(),
                "end_time": result.end_time.isoformat(),
                "duration_seconds": (result.end_time - result.start_time).total_seconds(),
                "message": result.message,
                "error": result.error,
                "benchmark": benchmark_run,
                "agent_stats": result.agent_stats,
                "escalations": self._escalations,
                "interventions": (
                    self._orchestrator.get_interventions_payload()
                    if self._orchestrator is not None
                    else []
                ),
                "stream_errors": self._stream_errors,
            }

        with open(self.experiment_dir / "metadata.json", "w") as f:
            json.dump(metadata, f, indent=2)

    def _build_result(
        self,
        success: bool,
        outcome: str,
        termination_reason: str,
        system_failure: bool,
        message: str | None = None,
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
            outcome=outcome,
            termination_reason=termination_reason,
            system_failure=system_failure,
            start_time=self._start_time or datetime.now(),
            end_time=self._end_time or datetime.now(),
            transcript_path=transcript_path,
            message=message,
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
    use_direct_cli: bool | None = None,
) -> ExperimentResult:
    """Run an experiment from a config file."""
    config = ExperimentConfig.from_yaml(config_path)

    return await run_experiment_with_config(
        config=config,
        task=task,
        sdk_binary_path=sdk_binary_path,
        experiments_dir=experiments_dir,
        on_escalate=on_escalate,
        on_turn_limit=on_turn_limit,
        use_direct_cli=use_direct_cli,
    )


async def run_experiment_with_config(
    config: ExperimentConfig,
    task: str,
    sdk_binary_path: Path,
    experiments_dir: Path,
    on_escalate: Callable[[str, SDKEvent, Any], None] | None = None,
    on_turn_limit: Callable[[str, int, int], tuple[str, int | None]] | None = None,
    use_direct_cli: bool | None = None,
) -> ExperimentResult:
    """Run an experiment from an in-memory config object."""

    experiment = Experiment(
        config=config,
        sdk_binary_path=sdk_binary_path,
        experiments_dir=experiments_dir,
        on_escalate=on_escalate,
        on_turn_limit=on_turn_limit,
        use_direct_cli=use_direct_cli,
    )

    try:
        await experiment.setup()
        result = await experiment.run(task)
        return result
    finally:
        try:
            await experiment.teardown()
        except Exception as e:
            logger.warning("Experiment teardown failed: %s", e)
