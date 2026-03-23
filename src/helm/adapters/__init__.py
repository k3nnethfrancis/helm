"""Helm adapters subpackage -- SDK client, DirectCLI client, and harness adapters."""

from helm.adapters.base import (
    API_PREFIX,
    DIRECTCLI_STREAM_READER_LIMIT,
    FollowUpMessageUnsupportedError,
    HarnessAdapter,
    SDKConfig,
    SDKEvent,
    SessionConfig,
    _CLAUDE_SESSION_VARS,
)
from helm.adapters.claude import ClaudeAdapter
from helm.adapters.codex import CodexAdapter
from helm.adapters.direct_cli import DirectCLIClient, get_harness_adapter
from helm.adapters.opencode import OpenCodeAdapter
from helm.adapters.sdk_client import SDKClient, sdk_client

_HARNESS_ADAPTERS: dict[str, type[HarnessAdapter]] = {
    "claude": ClaudeAdapter,
    "codex": CodexAdapter,
    "opencode": OpenCodeAdapter,
}

__all__ = [
    "API_PREFIX",
    "ClaudeAdapter",
    "CodexAdapter",
    "DIRECTCLI_STREAM_READER_LIMIT",
    "DirectCLIClient",
    "FollowUpMessageUnsupportedError",
    "HarnessAdapter",
    "OpenCodeAdapter",
    "SDKClient",
    "SDKConfig",
    "SDKEvent",
    "SessionConfig",
    "_CLAUDE_SESSION_VARS",
    "_HARNESS_ADAPTERS",
    "get_harness_adapter",
    "sdk_client",
]
