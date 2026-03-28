"""Broker-based coordination backend.

Manages the lifecycle of the Helm messaging broker and generates
per-agent MCP server configs. Messages flow through the broker
HTTP API; agents communicate via MCP tools provided by the
per-agent MCP server (helm.coordination.mcp_server).

This backend replaces the filesystem-based coordination for
experiments that use `mechanism: messaging` with broker delivery.
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from helm.coordination.base import (
    CoordinationMessage,
    DeliveryStatus,
    MessageType,
    OnMessageCallback,
)
from helm.coordination.broker import HelmBroker, Message
from helm.sdk import SDKClient


class BrokerBackend:
    """Coordination backend using the Helm messaging broker.

    Agents communicate via MCP tools (helm_send_message, helm_check_inbox)
    provided by per-agent MCP servers that connect to the broker.
    """

    def __init__(self, poll_interval: float = 2.0, **kwargs: Any):
        self._poll_interval = poll_interval
        self._broker: HelmBroker | None = None
        self._experiment_dir: Path | None = None
        self._agents: list[str] = []
        self._config: dict[str, Any] = {}
        self._on_message: OnMessageCallback | None = None
        self._poll_task: asyncio.Task | None = None
        self._running = False
        self._seen_message_ids: set[int] = set()

    async def setup(
        self,
        experiment_dir: Any,
        agents: list[str],
        config: dict[str, Any],
    ) -> None:
        """Start the broker and generate per-agent MCP configs."""
        self._experiment_dir = Path(experiment_dir).resolve()
        self._agents = agents
        self._config = config

        # Create coordination directories (still needed for signals/done)
        coord_dir = self._experiment_dir / "coordination"
        (coord_dir / "signals").mkdir(parents=True, exist_ok=True)
        (coord_dir / "messages").mkdir(parents=True, exist_ok=True)

        # Build topology rules from agent config
        agent_configs = config.get("agent_roles", {})
        topology_rules: dict[str, list[str]] = {}
        raw_agents = config.get("_raw_agents", {})
        for aid in agents:
            if isinstance(raw_agents, dict) and aid in raw_agents:
                can_message = raw_agents[aid].get("can_message", [])
                if can_message:
                    topology_rules[aid] = can_message

        # Start broker
        enforcement = config.get("enforcement", "prompt-only")
        self._broker = HelmBroker(on_message=self._on_broker_message)
        self._broker.configure_topology(
            topology_rules,
            enforce=(enforcement == "mechanical"),
        )
        port = await self._broker.start()

        # Write .helm-config.json (for backward compat with agent_cli)
        helm_config = self._build_helm_config(config, agents)
        (coord_dir / ".helm-config.json").write_text(
            json.dumps(helm_config, indent=2)
        )

        # Generate per-agent MCP config files
        mcp_dir = self._experiment_dir / "mcp-configs"
        mcp_dir.mkdir(parents=True, exist_ok=True)

        peers_by_agent = self._build_peers_map(config, agents)

        for agent_id in agents:
            mcp_config = {
                "mcpServers": {
                    "helm-messaging": {
                        "command": sys.executable,
                        "args": [
                            "-m",
                            "helm.coordination.mcp_server",
                        ],
                        "env": {
                            "HELM_AGENT_ID": agent_id,
                            "HELM_BROKER_URL": f"http://127.0.0.1:{port}",
                            "HELM_EXPERIMENT_DIR": str(
                                self._experiment_dir.resolve()
                            ),
                            "HELM_EXPERIMENT_ID": config.get(
                                "experiment_id", ""
                            ),
                            "HELM_PEERS": json.dumps(
                                peers_by_agent.get(agent_id, [])
                            ),
                        },
                    }
                }
            }
            config_path = mcp_dir / f"{agent_id}.json"
            config_path.write_text(json.dumps(mcp_config, indent=2))

    def get_mcp_config_path(self, agent_id: str) -> str | None:
        """Return the absolute path to this agent's MCP config file."""
        if self._experiment_dir is None:
            return None
        path = (self._experiment_dir / "mcp-configs" / f"{agent_id}.json").resolve()
        return str(path) if path.exists() else None

    def get_prompt_instructions(self, agent_id: str) -> str:
        """Return MCP-tool-based coordination instructions."""
        delivery = self._config.get("delivery", "poll")
        if delivery == "push":
            return (
                "## Coordination\n\n"
                "Use the `helm_send_message` tool to send messages to other agents.\n"
                "Messages from other agents will appear in your conversation automatically.\n"
                "You can also use `helm_check_inbox` to explicitly check for new messages.\n"
                "Use `helm_list_peers` to see who else is in the experiment.\n"
            )
        return (
            "## Coordination\n\n"
            "Use the `helm_send_message` tool to send messages to other agents.\n"
            "Use `helm_check_inbox` to check for new messages from other agents.\n"
            "Use `helm_list_peers` to see who else is in the experiment.\n"
            "Check your inbox after doing meaningful work — don't poll on every turn.\n"
        )

    async def start_watching(
        self,
        sdk: SDKClient,
        agent_sessions: dict[str, str],
        on_message: OnMessageCallback,
    ) -> None:
        """Start monitoring broker for transcript capture."""
        self._on_message = on_message
        self._running = True
        # Also monitor filesystem for signals/done (backward compat)
        self._poll_task = asyncio.create_task(self._poll_signals())

    async def stop_watching(self) -> None:
        """Stop monitoring."""
        self._running = False
        if self._poll_task and not self._poll_task.done():
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass

    def is_complete(self, agents: list[str]) -> bool:
        """Check if done signal exists."""
        if self._experiment_dir is None:
            return False
        signals_dir = self._experiment_dir / "coordination" / "signals"
        return (signals_dir / "done").exists()

    async def teardown(self) -> None:
        """Stop watching and shut down broker."""
        await self.stop_watching()
        if self._broker:
            await self._broker.stop()
            self._broker = None

    # ── Internal ──

    def _on_broker_message(self, msg: Message) -> None:
        """Forward broker messages to the transcript collector."""
        if msg.id in self._seen_message_ids:
            return
        self._seen_message_ids.add(msg.id)

        if self._on_message:
            coord_msg = CoordinationMessage(
                timestamp=datetime.fromtimestamp(msg.timestamp),
                sender=msg.from_id,
                recipient=msg.to_id,
                message_type=MessageType.PEER_MESSAGE,
                content=msg.content,
                channel_medium="broker",
                channel_persistence="ephemeral",
                channel_scope="targeted",
                delivered=msg.delivered,
                delivery_status=(
                    DeliveryStatus.DELIVERED
                    if msg.delivered
                    else DeliveryStatus.NOT_ATTEMPTED
                ),
                observed_via="broker",
            )
            self._on_message(coord_msg)

    async def _poll_signals(self) -> None:
        """Poll for filesystem signals (done, verification-summary)."""
        if self._experiment_dir is None:
            return
        signals_dir = self._experiment_dir / "coordination" / "signals"
        known: set[str] = set()

        while self._running:
            if signals_dir.exists():
                for path in signals_dir.iterdir():
                    if path.name in known:
                        continue
                    known.add(path.name)
                    content = path.read_text(errors="replace")

                    if self._on_message:
                        msg_type = MessageType.COMPLETION_SIGNAL
                        sender = None
                        if path.name == "verification-summary.md":
                            sender = "verification-summary"

                        self._on_message(
                            CoordinationMessage(
                                timestamp=datetime.now(),
                                sender=sender,
                                recipient="__all__",
                                message_type=msg_type,
                                content=content,
                                source_path=str(
                                    path.relative_to(self._experiment_dir)
                                ),
                                observed_via="filesystem_poll",
                            )
                        )

            await asyncio.sleep(self._poll_interval)

    def _build_helm_config(
        self,
        config: dict[str, Any],
        agents: list[str],
    ) -> dict[str, Any]:
        """Build .helm-config.json for backward compatibility."""
        agent_roles = config.get("agent_roles", {})
        hub_id = config.get("hub_agent_id")

        agent_defs: dict[str, Any] = {}
        for aid in agents:
            role = agent_roles.get(aid, "peer")
            can_message: list[str] = []
            # Hub can message all workers, workers can message hub
            if hub_id:
                if aid == hub_id:
                    can_message = [a for a in agents if a != aid]
                else:
                    can_message = [hub_id]
            agent_defs[aid] = {
                "role": role,
                "can_spawn": False,
                "can_message": can_message,
            }

        return {
            "family": config.get("coordination_family", "unknown"),
            "experiment_id": config.get("experiment_id", ""),
            "harness": "claude-code",
            "agents": agent_defs,
        }

    def _build_peers_map(
        self,
        config: dict[str, Any],
        agents: list[str],
    ) -> dict[str, list[dict[str, str]]]:
        """Build per-agent peer lists for MCP server config."""
        agent_roles = config.get("agent_roles", {})
        peers_map: dict[str, list[dict[str, str]]] = {}
        for aid in agents:
            peers = []
            for other in agents:
                if other == aid:
                    continue
                peers.append({
                    "id": other,
                    "role": agent_roles.get(other, "peer"),
                })
            peers_map[aid] = peers
        return peers_map
