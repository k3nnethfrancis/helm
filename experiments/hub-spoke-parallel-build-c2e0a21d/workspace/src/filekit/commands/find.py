"""filekit find — find files by name, pattern, or content."""

from __future__ import annotations

import sys
from pathlib import Path

from filekit.utils import walk_files, human_readable_size


def register(subparsers) -> None:
    """Register the find subcommand."""
    parser = subparsers.add_parser(
        "find",
        help="Find files by name, pattern, or content",
    )
    parser.add_argument(
        "directory",
        help="Root directory to search.",
    )
    parser.add_argument(
        "--name",
        default=None,
        metavar="PATTERN",
        help="Glob pattern for filename matching (e.g., '*.py').",
    )
    parser.add_argument(
        "--contains",
        default=None,
        metavar="TEXT",
        help="Search file contents for text (simple substring match).",
    )
    parser.add_argument(
        "--min-size",
        default=None,
        type=int,
        metavar="BYTES",
        help="Minimum file size in bytes.",
    )
    parser.add_argument(
        "--max-size",
        default=None,
        type=int,
        metavar="BYTES",
        help="Maximum file size in bytes.",
    )
    parser.add_argument(
        "--no-recursive",
        action="store_true",
        default=False,
        help="Don't recurse into subdirectories (default: recursive).",
    )
    parser.set_defaults(func=run)


def run(args) -> None:
    """Execute the find command."""
    root = Path(args.directory)
    if not root.exists():
        print(f"Error: directory does not exist: {args.directory}", file=sys.stderr)
        sys.exit(1)
    if not root.is_dir():
        print(f"Error: not a directory: {args.directory}", file=sys.stderr)
        sys.exit(1)

    recursive = not args.no_recursive
    files = walk_files(root, pattern=args.name, recursive=recursive)

    for path in files:
        if not path.is_file():
            continue

        # Size filters
        try:
            size = path.stat().st_size
        except (OSError, PermissionError):
            continue

        if args.min_size is not None and size < args.min_size:
            continue
        if args.max_size is not None and size > args.max_size:
            continue

        # Content search — substring match, show path:line_number:matching_line
        if args.contains is not None:
            try:
                with open(path, "r", errors="replace") as f:
                    for line_number, line in enumerate(f, start=1):
                        if args.contains in line:
                            print(f"{path}:{line_number}:{line.rstrip()}")
            except (OSError, UnicodeDecodeError):
                continue
        else:
            print(path)
