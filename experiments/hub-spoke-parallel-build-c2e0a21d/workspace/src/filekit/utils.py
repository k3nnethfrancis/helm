"""Shared utilities for filekit commands."""

import hashlib
import sys
from pathlib import Path


def hash_file(path: Path, algorithm: str = "sha256", chunk_size: int = 8192) -> str:
    """Compute hash of a file's contents."""
    h = hashlib.new(algorithm)
    with open(path, "rb") as f:
        while chunk := f.read(chunk_size):
            h.update(chunk)
    return h.hexdigest()


def human_readable_size(size_bytes: int) -> str:
    """Convert bytes to human-readable string."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}" if unit != "B" else f"{size_bytes} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} PB"


def walk_files(
    root: Path,
    pattern: str | None = None,
    recursive: bool = True,
) -> list[Path]:
    """Walk directory and yield file paths, optionally filtering by glob pattern."""
    root = root.resolve()
    if not root.is_dir():
        print(f"Error: '{root}' is not a directory.", file=sys.stderr)
        sys.exit(1)

    if recursive:
        if pattern:
            return sorted(root.rglob(pattern))
        return sorted(p for p in root.rglob("*") if p.is_file())
    else:
        if pattern:
            return sorted(root.glob(pattern))
        return sorted(p for p in root.iterdir() if p.is_file())


def format_table(headers: list[str], rows: list[list[str]]) -> str:
    """Format data as an aligned text table."""
    if not rows:
        return "(no results)"

    col_widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            col_widths[i] = max(col_widths[i], len(str(cell)))

    header_line = "  ".join(h.ljust(col_widths[i]) for i, h in enumerate(headers))
    separator = "  ".join("-" * w for w in col_widths)
    data_lines = []
    for row in rows:
        data_lines.append("  ".join(str(cell).ljust(col_widths[i]) for i, cell in enumerate(row)))

    return "\n".join([header_line, separator] + data_lines)


# ── ANSI styling helpers ──────────────────────────────────────────

RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"


def style(text: str, *codes: str) -> str:
    """Wrap text in ANSI escape codes with automatic reset."""
    return "".join(codes) + str(text) + RESET
