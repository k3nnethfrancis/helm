"""Helm messaging broker — lightweight HTTP server for inter-agent messaging.

Runs as an asyncio task inside the experiment runner. Manages per-agent
message queues, enforces topology rules when configured, and forwards
all messages to a callback for transcript capture.

Uses only stdlib (asyncio + http.server) — no external dependencies.
Binds to 127.0.0.1 on a random available port.
"""

from __future__ import annotations

import asyncio
import json
import socket
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
from typing import Any, Callable


@dataclass
class Message:
    """A single inter-agent message."""

    id: int
    from_id: str
    to_id: str
    content: str
    timestamp: float
    delivered: bool = False


@dataclass
class BrokerState:
    """In-memory broker state. Lives and dies with the experiment."""

    agents: dict[str, dict[str, Any]] = field(default_factory=dict)
    messages: list[Message] = field(default_factory=list)
    next_id: int = 1
    topology_rules: dict[str, list[str]] = field(default_factory=dict)
    enforce_topology: bool = False

    def add_message(
        self, from_id: str, to_id: str, content: str
    ) -> Message:
        msg = Message(
            id=self.next_id,
            from_id=from_id,
            to_id=to_id,
            content=content,
            timestamp=time.time(),
        )
        self.next_id += 1
        self.messages.append(msg)
        return msg

    def get_messages_for(
        self, agent_id: str, after_id: int = 0
    ) -> list[Message]:
        return [
            m
            for m in self.messages
            if m.to_id == agent_id and m.id > after_id
        ]

    def can_message(self, from_id: str, to_id: str) -> tuple[bool, str]:
        """Check topology rules. Returns (allowed, reason)."""
        if not self.enforce_topology:
            return True, ""
        allowed = self.topology_rules.get(from_id)
        if allowed is None:
            return False, f"No topology rules registered for {from_id}"
        if to_id in allowed:
            return True, ""
        return (
            False,
            f"Topology violation: {from_id} cannot message {to_id}. "
            f"Allowed: {allowed}",
        )

    def update_topology_rule(
        self, agent_id: str, allowed_recipients: list[str]
    ) -> None:
        """Replace one sender's allowed-recipient list."""
        self.topology_rules[agent_id] = list(allowed_recipients)

    def peers_for(self, agent_id: str) -> list[dict[str, Any]]:
        """Return the peer view for an agent."""
        if self.enforce_topology:
            peer_ids = self.topology_rules.get(agent_id, [])
        else:
            peer_ids = [
                other_id for other_id in self.agents
                if other_id != agent_id
            ]

        peers: list[dict[str, Any]] = []
        for peer_id in peer_ids:
            peer = self.agents.get(peer_id, {})
            peers.append(
                {
                    "id": peer_id,
                    "role": peer.get("role", "peer"),
                }
            )
        return peers


OnBrokerMessage = Callable[[Message], None]


def _make_handler(state: BrokerState, on_message: OnBrokerMessage | None):
    """Create an HTTP request handler class with access to broker state."""

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            pass  # Suppress default logging

        def _json_response(
            self, data: dict, status: int = 200
        ) -> None:
            body = json.dumps(data).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _read_body(self) -> dict:
            length = int(self.headers.get("Content-Length", 0))
            if length == 0:
                return {}
            return json.loads(self.rfile.read(length))

        def do_GET(self) -> None:
            path = self.path.split("?")[0]
            query = ""
            if "?" in self.path:
                query = self.path.split("?", 1)[1]

            if path == "/health":
                self._json_response({
                    "status": "ok",
                    "agents": len(state.agents),
                    "messages": len(state.messages),
                })
            elif path.startswith("/poll/"):
                agent_id = path.split("/poll/", 1)[1]
                after_id = 0
                for param in query.split("&"):
                    if param.startswith("after_id="):
                        after_id = int(param.split("=", 1)[1])
                messages = state.get_messages_for(agent_id, after_id)
                for m in messages:
                    m.delivered = True
                self._json_response({
                    "messages": [
                        {
                            "id": m.id,
                            "from_id": m.from_id,
                            "content": m.content,
                            "timestamp": m.timestamp,
                        }
                        for m in messages
                    ]
                })
            elif path == "/agents":
                self._json_response({
                    "agents": list(state.agents.values())
                })
            elif path.startswith("/peers/"):
                agent_id = path.split("/peers/", 1)[1]
                self._json_response({"peers": state.peers_for(agent_id)})
            else:
                self._json_response(
                    {"error": "Not found"}, status=404
                )

        def do_POST(self) -> None:
            path = self.path.split("?")[0]
            body = self._read_body()

            if path == "/register":
                agent_id = body.get("agent_id", "")
                if not agent_id:
                    self._json_response(
                        {"error": "agent_id required"}, status=400
                    )
                    return
                state.agents[agent_id] = {
                    "agent_id": agent_id,
                    "experiment_id": body.get(
                        "experiment_id", ""
                    ),
                    "role": body.get("role", "peer"),
                    "registered_at": time.time(),
                }
                self._json_response(
                    {"ok": True, "agent_id": agent_id}
                )

            elif path == "/send":
                from_id = body.get("from_id", "")
                to_id = body.get("to_id", "")
                content = body.get("content", "")
                if not from_id or not to_id or not content:
                    self._json_response(
                        {
                            "error": "from_id, to_id, and content required"
                        },
                        status=400,
                    )
                    return
                allowed, reason = state.can_message(from_id, to_id)
                if not allowed:
                    self._json_response(
                        {
                            "error": reason,
                            "topology_violation": True,
                        },
                        status=403,
                    )
                    return
                msg = state.add_message(from_id, to_id, content)
                if on_message:
                    on_message(msg)
                self._json_response(
                    {"ok": True, "message_id": msg.id}
                )
            elif path == "/update_topology":
                agent_id = body.get("agent_id", "")
                allowed = body.get("allowed_recipients")
                if not agent_id or not isinstance(allowed, list):
                    self._json_response(
                        {
                            "error": "agent_id and allowed_recipients list required"
                        },
                        status=400,
                    )
                    return
                normalized = [
                    recipient
                    for recipient in allowed
                    if isinstance(recipient, str) and recipient
                ]
                state.update_topology_rule(agent_id, normalized)
                self._json_response(
                    {"ok": True, "agent_id": agent_id, "allowed_recipients": normalized}
                )

            else:
                self._json_response(
                    {"error": "Not found"}, status=404
                )

    return Handler


class HelmBroker:
    """HTTP messaging broker for Helm experiments.

    Runs in a background thread so it doesn't block the asyncio event loop.
    """

    def __init__(
        self, on_message: OnBrokerMessage | None = None
    ):
        self._state = BrokerState()
        self._on_message = on_message
        self._server: HTTPServer | None = None
        self._thread: Thread | None = None
        self._port: int = 0

    @property
    def port(self) -> int:
        return self._port

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self._port}"

    @property
    def state(self) -> BrokerState:
        return self._state

    def configure_topology(
        self,
        rules: dict[str, list[str]],
        enforce: bool = False,
    ) -> None:
        """Set topology rules."""
        self._state.topology_rules = rules
        self._state.enforce_topology = enforce

    async def start(self) -> int:
        """Start the broker in a background thread. Returns the port."""
        # Find a free port
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", 0))
        self._port = sock.getsockname()[1]
        sock.close()

        handler_cls = _make_handler(
            self._state, self._on_message
        )
        self._server = HTTPServer(
            ("127.0.0.1", self._port), handler_cls
        )
        self._thread = Thread(
            target=self._server.serve_forever,
            daemon=True,
        )
        self._thread.start()
        return self._port

    async def stop(self) -> None:
        """Stop the broker."""
        if self._server:
            self._server.shutdown()
            self._server = None
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None
