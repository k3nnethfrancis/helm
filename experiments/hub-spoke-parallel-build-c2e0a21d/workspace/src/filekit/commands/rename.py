"""filekit rename — batch file renamer with preview, undo, and multiple modes."""

import argparse
import json
import os
import re
import sys
from pathlib import Path

from filekit.utils import format_table, walk_files

HISTORY_FILE = ".filekit_rename_history.json"


def register(subparsers: argparse._SubParsersAction) -> None:
    """Register the rename subcommand."""
    p = subparsers.add_parser(
        "rename",
        help="Batch rename files using patterns, prefixes, suffixes, or numbering.",
        description=(
            "Rename files matching a glob pattern. Always previews changes "
            "first — pass --execute to apply. Supports regex replacement, "
            "prefix/suffix addition, and sequential numbering."
        ),
    )

    # File selection
    p.add_argument(
        "glob",
        help="Glob pattern to select files (e.g. '*.txt', 'img_*').",
    )
    p.add_argument(
        "-d", "--directory",
        type=Path,
        default=Path("."),
        help="Directory to search in (default: current directory).",
    )
    p.add_argument(
        "-r", "--recursive",
        action="store_true",
        default=False,
        help="Search directories recursively.",
    )

    # Rename modes (mutually exclusive groups combined freely)
    regex_group = p.add_argument_group("regex replacement")
    regex_group.add_argument(
        "--pattern",
        help="Regex pattern to match in filenames.",
    )
    regex_group.add_argument(
        "--replacement",
        help="Replacement string (supports \\1, \\2 backreferences).",
    )

    affix_group = p.add_argument_group("prefix / suffix")
    affix_group.add_argument(
        "--prefix",
        help="String to prepend to each filename.",
    )
    affix_group.add_argument(
        "--suffix",
        help="String to append before the file extension.",
    )

    number_group = p.add_argument_group("sequential numbering")
    number_group.add_argument(
        "--number",
        action="store_true",
        default=False,
        help="Rename files with sequential numbers.",
    )
    number_group.add_argument(
        "--start",
        type=int,
        default=1,
        help="Starting number for --number (default: 1).",
    )
    number_group.add_argument(
        "--padding",
        type=int,
        default=0,
        help="Zero-pad numbers to this width (0 = auto-detect).",
    )

    # Execution control
    p.add_argument(
        "--execute",
        action="store_true",
        default=False,
        help="Actually perform the rename (default: preview only).",
    )
    p.add_argument(
        "--undo",
        action="store_true",
        default=False,
        help="Reverse the last rename operation.",
    )

    p.set_defaults(func=_run)


def _compute_new_name(
    name: str,
    ext: str,
    args: argparse.Namespace,
    index: int,
    total: int,
) -> str:
    """Compute the new filename (stem only, no extension) for one file.

    Transformations are applied in order: regex -> prefix -> suffix -> number.
    """
    stem = name

    # 1. Regex replacement
    if args.pattern is not None and args.replacement is not None:
        stem = re.sub(args.pattern, args.replacement, stem)

    # 2. Prefix
    if args.prefix:
        stem = args.prefix + stem

    # 3. Suffix (appended to stem, before extension)
    if args.suffix:
        stem = stem + args.suffix

    # 4. Sequential numbering replaces the stem entirely
    if args.number:
        pad = args.padding if args.padding > 0 else len(str(total + args.start - 1))
        stem = str(index).zfill(pad)

    return stem + ext


def _build_rename_plan(files: list[Path], args: argparse.Namespace) -> list[tuple[Path, Path]]:
    """Return list of (old_path, new_path) tuples."""
    plan: list[tuple[Path, Path]] = []
    total = len(files)

    for i, fpath in enumerate(files):
        old_stem = fpath.stem
        ext = fpath.suffix  # includes the dot
        new_stem_ext = _compute_new_name(old_stem, ext, args, i + args.start, total)
        new_path = fpath.parent / new_stem_ext

        if new_path != fpath:
            plan.append((fpath, new_path))

    return plan


def _check_collisions(plan: list[tuple[Path, Path]]) -> list[str]:
    """Return error messages for any collisions in the plan."""
    errors: list[str] = []
    new_names: dict[Path, Path] = {}
    old_paths = {o for o, _ in plan}

    for old, new in plan:
        # Collision with existing file that isn't being renamed away
        if new.exists() and new not in old_paths:
            errors.append(f"Collision: '{new.name}' already exists on disk.")

        # Collision within the plan itself
        if new in new_names:
            errors.append(
                f"Collision: both '{new_names[new].name}' and '{old.name}' "
                f"would become '{new.name}'."
            )
        new_names[new] = old

    return errors


def _save_history(plan: list[tuple[Path, Path]], directory: Path) -> None:
    """Save rename plan to history file for undo."""
    history_path = directory / HISTORY_FILE
    record = {
        "operations": [
            {"old": str(old), "new": str(new)}
            for old, new in plan
        ]
    }
    history_path.write_text(json.dumps(record, indent=2) + "\n")


def _load_history(directory: Path) -> list[tuple[Path, Path]] | None:
    """Load last rename plan from history file. Returns None if missing."""
    history_path = directory / HISTORY_FILE
    if not history_path.exists():
        return None
    data = json.loads(history_path.read_text())
    return [
        (Path(op["new"]), Path(op["old"]))  # reversed for undo
        for op in data["operations"]
    ]


def _execute_renames(plan: list[tuple[Path, Path]]) -> int:
    """Perform the renames. Returns 0 on success, 1 on error."""
    for old, new in plan:
        try:
            os.rename(old, new)
        except OSError as e:
            print(f"Error renaming '{old.name}': {e}", file=sys.stderr)
            return 1
    return 0


def _run(args: argparse.Namespace) -> int:
    directory = args.directory.resolve()

    # ── Undo mode ────────────────────────────────────────────────
    if args.undo:
        plan = _load_history(directory)
        if plan is None:
            print("No rename history found. Nothing to undo.", file=sys.stderr)
            return 1

        print(format_table(
            ["Current Name", "→", "Restored Name"],
            [[old.name, "→", new.name] for old, new in plan],
        ))
        print(f"\n{len(plan)} file(s) will be restored.")

        if not args.execute:
            print("\nThis is a preview. Pass --execute to apply the undo.")
            return 0

        result = _execute_renames(plan)
        if result == 0:
            # Remove history file after successful undo
            history_path = directory / HISTORY_FILE
            if history_path.exists():
                history_path.unlink()
            print("Undo complete.")
        return result

    # ── Validate arguments ───────────────────────────────────────
    if args.pattern and args.replacement is None:
        print("Error: --pattern requires --replacement.", file=sys.stderr)
        return 1
    if args.replacement and args.pattern is None:
        print("Error: --replacement requires --pattern.", file=sys.stderr)
        return 1

    has_operation = any([
        args.pattern is not None,
        args.prefix is not None,
        args.suffix is not None,
        args.number,
    ])
    if not has_operation:
        print(
            "Error: specify at least one rename operation "
            "(--pattern/--replacement, --prefix, --suffix, or --number).",
            file=sys.stderr,
        )
        return 1

    # ── Collect files ────────────────────────────────────────────
    files = walk_files(directory, pattern=args.glob, recursive=args.recursive)
    files = [f for f in files if f.is_file()]

    if not files:
        print("No files matched the glob pattern.")
        return 0

    # ── Build and validate plan ──────────────────────────────────
    plan = _build_rename_plan(files, args)

    if not plan:
        print("All files already match the target names. Nothing to do.")
        return 0

    errors = _check_collisions(plan)
    if errors:
        for err in errors:
            print(f"Error: {err}", file=sys.stderr)
        return 1

    # ── Preview ──────────────────────────────────────────────────
    rows = [[old.name, "→", new.name] for old, new in plan]
    print(format_table(["Old Name", "", "New Name"], rows))
    print(f"\n{len(plan)} file(s) to rename.")

    if not args.execute:
        print("\nThis is a preview. Pass --execute to apply changes.")
        return 0

    # ── Execute ──────────────────────────────────────────────────
    _save_history(plan, directory)
    result = _execute_renames(plan)
    if result == 0:
        print("Rename complete. Use --undo --execute to reverse.")
    return result
