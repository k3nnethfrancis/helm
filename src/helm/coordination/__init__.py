"""Pluggable coordination backends for Helm experiments.

The coordination package abstracts inter-agent communication so that
different mechanisms can be swapped via pattern YAML config. This lets
experiments compare coordination strategies (filesystem, database,
webhooks, etc.) as an independent variable.

Usage:
    from helm.coordination import create_backend, CoordinationBackend

    backend = create_backend("filesystem", poll_interval=3.0)
    await backend.setup(experiment_dir, agent_ids, config)
    await backend.start_watching(sdk, sessions, on_message=callback)
"""

from helm.coordination.base import (
    CoordinationBackend,
    CoordinationMessage,
    MessageType,
    OnMessageCallback,
)
from helm.coordination.factory import create_backend, register_backend

__all__ = [
    "CoordinationBackend",
    "CoordinationMessage",
    "MessageType",
    "OnMessageCallback",
    "create_backend",
    "register_backend",
]
