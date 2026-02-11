"""Backend registry and factory.

Maps mechanism names from pattern YAML to concrete backend classes.
Custom backends can be registered at runtime.
"""

from __future__ import annotations

from typing import Any

from helm.coordination.base import CoordinationBackend
from helm.coordination.filesystem_nudge import FilesystemNudgeBackend

# Registry: mechanism name -> backend constructor
_REGISTRY: dict[str, type] = {
    "filesystem": FilesystemNudgeBackend,
    "filesystem_nudge": FilesystemNudgeBackend,
}


def create_backend(mechanism: str, **kwargs: Any) -> CoordinationBackend:
    """Create a coordination backend by mechanism name.

    Args:
        mechanism: Name from the pattern YAML's coordination.mechanism field.
        **kwargs: Passed to the backend constructor (e.g., poll_interval).

    Returns:
        An instance satisfying the CoordinationBackend protocol.

    Raises:
        ValueError: If the mechanism name is not registered.
    """
    cls = _REGISTRY.get(mechanism)
    if cls is None:
        available = ", ".join(sorted(_REGISTRY.keys()))
        raise ValueError(
            f"Unknown coordination mechanism: {mechanism!r}. Available: {available}"
        )
    return cls(**kwargs)


def register_backend(name: str, cls: type) -> None:
    """Register a custom coordination backend.

    Args:
        name: Mechanism name to use in YAML configs.
        cls: Backend class that satisfies the CoordinationBackend protocol.
    """
    _REGISTRY[name] = cls
