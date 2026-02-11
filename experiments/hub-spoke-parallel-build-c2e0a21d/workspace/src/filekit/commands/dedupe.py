"""filekit dedupe — find and remove duplicate files by content hash.

Uses a two-pass approach: first group files by size (files with unique
sizes cannot be duplicates), then hash only the candidates.
"""

from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

from filekit.utils import format_table, hash_file, human_readable_size, walk_files


def _parse_size(value: str) -> int:
    """Parse a human-readable size string like '1MB' or '500KB' into bytes."""
    value = value.strip().upper()
    multipliers = {
        "B": 1,
        "KB": 1024,
        "MB": 1024 ** 2,
        "GB": 1024 ** 3,
        "TB": 1024 ** 4,
    }
    for suffix, mult in sorted(multipliers.items(), key=lambda x: -len(x[0])):
        if value.endswith(suffix):
            num = value[: -len(suffix)].strip()
            return int(float(num) * mult)
    return int(value)


def register(subparsers) -> None:
    """Register the dedupe subcommand with the CLI argument parser."""
    parser = subparsers.add_parser(
        "dedupe",
        help="Find and remove duplicate files",
    )
    parser.add_argument(
        "path",
        nargs="?",
        default=".",
        help="Directory to scan (default: current directory)",
    )
    parser.add_argument(
        "--delete",
        action="store_true",
        help="Delete duplicate files (keeps the first found in each group)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be deleted without actually deleting",
    )
    parser.add_argument(
        "--min-size",
        default="0",
        metavar="SIZE",
        help="Minimum file size to consider, e.g. 1MB, 500KB (default: 0)",
    )
    parser.add_argument(
        "--algorithm",
        default="sha256",
        choices=["md5", "sha1", "sha256"],
        help="Hash algorithm to use (default: sha256)",
    )
    parser.add_argument(
        "--no-recurse",
        action="store_true",
        help="Don't descend into subdirectories",
    )
    parser.set_defaults(func=run)


def run(args) -> None:
    """Execute the dedupe subcommand."""
    root = Path(args.path).resolve()
    if not root.is_dir():
        print(f"error: {root} is not a directory", file=sys.stderr)
        sys.exit(1)

    min_size = _parse_size(args.min_size)
    algorithm = args.algorithm
    recursive = not args.no_recurse
    delete = args.delete

    # --- Pass 1: collect files and group by size ---
    files = walk_files(root, recursive=recursive)
    sized: list[tuple[Path, int]] = []
    skipped = 0

    for fpath in files:
        try:
            st = fpath.stat()
        except (PermissionError, OSError) as e:
            print(f"warning: cannot stat {fpath}: {e}", file=sys.stderr)
            skipped += 1
            continue
        if st.st_size < min_size:
            continue
        sized.append((fpath, st.st_size))

    if not sized:
        print("No files to scan.")
        return

    size_groups: dict[int, list[Path]] = defaultdict(list)
    for fpath, fsize in sized:
        size_groups[fsize].append(fpath)

    # Only keep groups with 2+ files — unique sizes can't be duplicates
    candidates = {s: paths for s, paths in size_groups.items() if len(paths) > 1}
    candidate_count = sum(len(p) for p in candidates.values())

    print(
        f"Scanned {len(sized)} files, {candidate_count} candidates "
        f"in {len(candidates)} size groups"
    )
    if skipped:
        print(f"  ({skipped} files skipped due to errors)")

    if not candidates:
        print("No duplicate files found.")
        return

    # --- Pass 2: hash candidates and group by content ---
    hash_groups: dict[str, list[Path]] = defaultdict(list)
    hashed = 0

    for _file_size, paths in candidates.items():
        for fpath in paths:
            hashed += 1
            if hashed % 500 == 0:
                print(f"  hashed {hashed}/{candidate_count} files...", file=sys.stderr)
            try:
                digest = hash_file(fpath, algorithm=algorithm)
            except (PermissionError, OSError) as e:
                print(f"warning: cannot read {fpath}: {e}", file=sys.stderr)
                continue
            hash_groups[digest].append(fpath)

    duplicates = {h: paths for h, paths in hash_groups.items() if len(paths) > 1}

    if not duplicates:
        print("No duplicate files found.")
        return

    # --- Report ---
    total_waste = 0
    total_dupes = 0
    group_num = 0

    for digest, paths in sorted(duplicates.items()):
        group_num += 1
        file_size = paths[0].stat().st_size
        waste = file_size * (len(paths) - 1)
        total_waste += waste
        total_dupes += len(paths) - 1

        print(f"\nDuplicate group {group_num} ({algorithm}: {digest[:12]}...):")
        rows = []
        for p in paths:
            rows.append([str(p), human_readable_size(file_size)])
        print(format_table(["PATH", "SIZE"], rows))

        if delete:
            for dup in paths[1:]:
                try:
                    dup.unlink()
                    print(f"  deleted: {dup}")
                except OSError as e:
                    print(f"  error deleting {dup}: {e}", file=sys.stderr)

    print(
        f"\nFound {len(duplicates)} duplicate group(s) "
        f"({total_dupes} files, {human_readable_size(total_waste)} reclaimable)"
    )
    if delete:
        print("Duplicates deleted (kept first of each group).")
