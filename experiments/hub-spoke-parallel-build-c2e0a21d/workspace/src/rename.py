"""filekit rename — batch file renamer with preview, execute, and undo."""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
from pathlib import Path

from output import format_table, format_summary, style, GREEN, RED, YELLOW, BOLD, DIM

HISTORY_FILE = ".filekit_rename_history.json"


# ── Helpers ──────────────────────────────────────────────────────────

def _resolve_history_path(directory: str) -> Path:
    return Path(directory) / HISTORY_FILE


def _load_history(directory: str) -> list[dict]:
    path = _resolve_history_path(directory)
    if path.exists():
        return json.loads(path.read_text())
    return []


def _save_history(directory: str, history: list[dict]) -> None:
    path = _resolve_history_path(directory)
    path.write_text(json.dumps(history, indent=2) + "\n")


def _collect_files(pattern: str) -> list[Path]:
    """Expand a glob pattern and return only files (not dirs), sorted."""
    matches = sorted(glob.glob(pattern, recursive=True))
    return [Path(m) for m in matches if os.path.isfile(m)]


# ── Rename logic ─────────────────────────────────────────────────────

def compute_renames(
    files: list[Path],
    *,
    pattern: str | None = None,
    replacement: str | None = None,
    prefix: str | None = None,
    suffix: str | None = None,
    number: bool = False,
    start: int = 1,
    padding: int = 3,
) -> list[tuple[Path, Path]]:
    """Compute (old, new) path pairs without touching the filesystem.

    Operations are applied in order: regex → prefix → suffix → number.
    """
    renames: list[tuple[Path, Path]] = []

    counter = start
    for f in files:
        parent = f.parent
        stem = f.stem
        ext = f.suffix  # includes the dot

        new_name = stem

        # 1. Regex replace on the stem
        if pattern is not None and replacement is not None:
            new_name = re.sub(pattern, replacement, new_name)

        # 2. Prefix
        if prefix:
            new_name = prefix + new_name

        # 3. Suffix (before extension)
        if suffix:
            new_name = new_name + suffix

        # 4. Sequential numbering (replaces the stem entirely)
        if number:
            new_name = str(counter).zfill(padding)
            counter += 1

        new_path = parent / (new_name + ext)
        if new_path != f:
            renames.append((f, new_path))

    return renames


def check_collisions(renames: list[tuple[Path, Path]]) -> list[str]:
    """Return error messages for any destination collisions."""
    errors: list[str] = []
    seen: dict[Path, Path] = {}
    for old, new in renames:
        # Collision with an existing file not being renamed
        if new.exists() and new not in {o for o, _ in renames}:
            errors.append(f"Would overwrite existing file: {new}")
        # Collision between two renames targeting the same destination
        if new in seen:
            errors.append(
                f"Duplicate target {new} from both {seen[new]} and {old}"
            )
        seen[new] = old
    return errors


def preview(renames: list[tuple[Path, Path]]) -> str:
    """Return a formatted preview table of the planned renames."""
    if not renames:
        return style("No files matched or no changes needed.", YELLOW)

    rows = [[str(old.name), "→", str(new.name)] for old, new in renames]
    header = ["Old Name", "", "New Name"]
    table = format_table(rows, headers=header)

    summary = format_summary({
        "Files to rename": len(renames),
        "Directory": str(renames[0][0].parent),
    })

    return f"\n{table}\n\n{summary}\n"


def execute_renames(
    renames: list[tuple[Path, Path]], *, directory: str
) -> None:
    """Rename files on disk and record the operation for undo."""
    record = {
        "mappings": [[str(old), str(new)] for old, new in renames],
    }

    for old, new in renames:
        old.rename(new)
        print(f"  {style('renamed', GREEN)}  {old.name} → {new.name}")

    history = _load_history(directory)
    history.append(record)
    _save_history(directory, history)

    print(
        f"\n  {style('Done.', BOLD)} "
        f"Renamed {len(renames)} file(s). Undo available."
    )


def undo_last(directory: str) -> None:
    """Reverse the most recent rename operation."""
    history = _load_history(directory)
    if not history:
        print(style("Nothing to undo.", YELLOW))
        return

    last = history.pop()
    mappings = last["mappings"]

    errors: list[str] = []
    for old_str, new_str in mappings:
        new_path = Path(new_str)
        old_path = Path(old_str)
        if not new_path.exists():
            errors.append(f"Cannot undo: {new_path} no longer exists")
        if old_path.exists():
            errors.append(f"Cannot undo: {old_path} already exists")

    if errors:
        for e in errors:
            print(style(f"  ERROR: {e}", RED))
        return

    for old_str, new_str in mappings:
        Path(new_str).rename(Path(old_str))
        print(
            f"  {style('restored', GREEN)}  "
            f"{Path(new_str).name} → {Path(old_str).name}"
        )

    _save_history(directory, history)
    print(f"\n  {style('Undo complete.', BOLD)} Restored {len(mappings)} file(s).")


# ── CLI ──────────────────────────────────────────────────────────────

def build_parser(subparsers=None) -> argparse.ArgumentParser:
    """Create the argument parser for `filekit rename`.

    If *subparsers* is provided, register as a subcommand; otherwise
    return a standalone parser (useful for testing).
    """
    kwargs = dict(
        description="Batch rename files with preview and undo.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    if subparsers is not None:
        parser = subparsers.add_parser("rename", **kwargs)
    else:
        parser = argparse.ArgumentParser(prog="filekit rename", **kwargs)

    parser.add_argument(
        "files",
        help="Glob pattern selecting files to rename (e.g. '*.txt').",
    )
    parser.add_argument(
        "--pattern",
        help="Regex pattern to match in filenames.",
    )
    parser.add_argument(
        "--replacement",
        help="Replacement string for --pattern matches.",
    )
    parser.add_argument(
        "--prefix",
        help="String to prepend to each filename.",
    )
    parser.add_argument(
        "--suffix",
        help="String to append to each filename (before extension).",
    )
    parser.add_argument(
        "--number",
        action="store_true",
        help="Replace names with sequential numbers.",
    )
    parser.add_argument(
        "--start",
        type=int,
        default=1,
        help="Starting number for --number (default: 1).",
    )
    parser.add_argument(
        "--padding",
        type=int,
        default=3,
        help="Zero-padding width for --number (default: 3).",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually rename files (preview-only by default).",
    )
    parser.add_argument(
        "--undo",
        action="store_true",
        help="Reverse the last rename operation.",
    )

    return parser


def run(args: argparse.Namespace) -> int:
    """Entry point called by the top-level filekit CLI."""
    # ── Undo mode ────────────────────────────────────────────────
    if args.undo:
        # Determine directory from the glob pattern
        files = _collect_files(args.files)
        directory = str(files[0].parent) if files else "."
        undo_last(directory)
        return 0

    # ── Normal rename flow ───────────────────────────────────────
    files = _collect_files(args.files)
    if not files:
        print(style("No files matched the pattern.", YELLOW))
        return 1

    has_operation = any([
        args.pattern is not None,
        args.prefix is not None,
        args.suffix is not None,
        args.number,
    ])
    if not has_operation:
        print(style("No rename operation specified. Use --pattern, --prefix, --suffix, or --number.", RED))
        return 1

    renames = compute_renames(
        files,
        pattern=args.pattern,
        replacement=args.replacement,
        prefix=args.prefix,
        suffix=args.suffix,
        number=args.number,
        start=args.start,
        padding=args.padding,
    )

    # Always show preview
    print(preview(renames))

    if not renames:
        return 0

    # Check for collisions before proceeding
    errors = check_collisions(renames)
    if errors:
        for e in errors:
            print(style(f"  ERROR: {e}", RED))
        return 1

    if args.execute:
        directory = str(files[0].parent)
        execute_renames(renames, directory=directory)
    else:
        print(style("  Preview only. Add --execute to rename files.", DIM))

    return 0


def main() -> None:
    """Standalone entry point for `python rename.py`."""
    parser = build_parser()
    args = parser.parse_args()
    sys.exit(run(args))


if __name__ == "__main__":
    main()
