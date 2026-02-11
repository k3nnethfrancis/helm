"""filekit stats — file statistics, directory breakdown, and duplicate detection."""

import json
import sys
from collections import defaultdict
from pathlib import Path

from filekit.utils import format_table, hash_file, human_readable_size, walk_files


def register(subparsers) -> None:
    """Register the stats subcommand."""
    parser = subparsers.add_parser(
        "stats",
        help="Show file statistics for a directory",
        description=(
            "Counts files by type, reports sizes, shows directory breakdown, "
            "and detects duplicate files."
        ),
    )
    parser.add_argument(
        "directory",
        nargs="?",
        default=".",
        help="Root directory to analyze (default: current directory)",
    )
    parser.add_argument(
        "--json",
        dest="json_output",
        action="store_true",
        help="Output in JSON format",
    )
    parser.set_defaults(func=run)


def _collect_file_info(root: Path) -> tuple[list[dict], list[str]]:
    """Walk directory and collect metadata for each file.

    Returns (files, skipped) where skipped is a list of warning messages.
    """
    files = []
    skipped = []
    for path in walk_files(root):
        try:
            stat = path.stat()
        except (PermissionError, OSError) as e:
            skipped.append(f"{path}: {e}")
            continue
        files.append({
            "path": path,
            "size": stat.st_size,
            "ext": path.suffix.lower() if path.suffix else "(no extension)",
        })
    return files, skipped


def _size_stats(files: list[dict]) -> dict:
    """Compute aggregate size statistics."""
    if not files:
        return {"total": 0, "average": 0.0, "count": 0, "largest": [], "smallest": []}

    sorted_by_size = sorted(files, key=lambda f: f["size"], reverse=True)
    total = sum(f["size"] for f in files)

    return {
        "count": len(files),
        "total": total,
        "average": total / len(files),
        "largest": sorted_by_size[:10],
        "smallest": sorted_by_size[-10:],
    }


def _type_stats(files: list[dict]) -> dict[str, dict]:
    """Count files and total size per extension."""
    by_ext: dict[str, dict] = defaultdict(lambda: {"count": 0, "total_size": 0})
    for f in files:
        entry = by_ext[f["ext"]]
        entry["count"] += 1
        entry["total_size"] += f["size"]
    return dict(sorted(by_ext.items(), key=lambda x: x[1]["count"], reverse=True))


def _dir_stats(files: list[dict], root: Path) -> dict[str, dict]:
    """Compute per-directory size breakdown."""
    by_dir: dict[str, dict] = defaultdict(lambda: {"count": 0, "total_size": 0})
    for f in files:
        try:
            rel = f["path"].relative_to(root)
        except ValueError:
            continue
        top = rel.parts[0] if len(rel.parts) > 1 else "."
        entry = by_dir[top]
        entry["count"] += 1
        entry["total_size"] += f["size"]
    return dict(sorted(by_dir.items(), key=lambda x: x[1]["total_size"], reverse=True))


def _find_duplicates(files: list[dict]) -> list[dict]:
    """Detect duplicate files: group by size, then hash same-size files.

    Returns list of {hash, size, paths} dicts.
    """
    by_size: dict[int, list[dict]] = defaultdict(list)
    for f in files:
        if f["size"] > 0:
            by_size[f["size"]].append(f)

    duplicates = []
    for size, group in by_size.items():
        if len(group) < 2:
            continue
        by_hash: dict[str, list[str]] = defaultdict(list)
        for f in group:
            try:
                h = hash_file(f["path"])
            except (PermissionError, OSError):
                continue
            by_hash[h].append(str(f["path"]))
        for h, paths in by_hash.items():
            if len(paths) >= 2:
                duplicates.append({"hash": h, "size": size, "paths": sorted(paths)})

    return duplicates


def _print_text_report(
    root: Path, size: dict, types: dict, dirs: dict, dupes: list, skipped: list
) -> None:
    """Print a formatted text report to stdout."""
    print(f"File Statistics: {root}")
    print("=" * 60)

    # Size summary
    print("\n=== Size Summary ===")
    if size["count"] == 0:
        print("  No files found.")
    else:
        print(f"  Total files : {size['count']:,}")
        print(f"  Total size  : {human_readable_size(size['total'])}")
        print(f"  Average size: {human_readable_size(int(size['average']))}")
        if size["largest"]:
            lg = size["largest"][0]
            print(f"  Largest     : {human_readable_size(lg['size'])}  {lg['path'].name}")
        if size["smallest"]:
            sm = size["smallest"][-1]
            print(f"  Smallest    : {human_readable_size(sm['size'])}  {sm['path'].name}")

    # Largest files
    if size.get("largest"):
        print(f"\n=== Largest Files (top {len(size['largest'])}) ===")
        rows = [
            [str(f["path"].relative_to(root)), human_readable_size(f["size"])]
            for f in size["largest"]
        ]
        print(format_table(["File", "Size"], rows))

    # Smallest files
    non_zero = [f for f in size.get("smallest", []) if f["size"] > 0]
    if non_zero:
        print(f"\n=== Smallest Files (non-zero, bottom {len(non_zero)}) ===")
        rows = [
            [str(f["path"].relative_to(root)), human_readable_size(f["size"])]
            for f in reversed(non_zero)
        ]
        print(format_table(["File", "Size"], rows))

    # File types
    print("\n=== File Types ===")
    type_rows = [
        [ext, str(info["count"]), human_readable_size(info["total_size"])]
        for ext, info in types.items()
    ]
    print(format_table(["Extension", "Count", "Total Size"], type_rows))

    # Directory breakdown
    print("\n=== Directory Breakdown ===")
    dir_rows = [
        [name, str(info["count"]), human_readable_size(info["total_size"])]
        for name, info in dirs.items()
    ]
    print(format_table(["Directory", "Files", "Size"], dir_rows))

    # Duplicates
    print("\n=== Duplicates ===")
    if not dupes:
        print("  No duplicates found.")
    else:
        print(f"  {len(dupes)} duplicate group(s) found:\n")
        for i, group in enumerate(dupes, 1):
            print(f"  Group {i} [{human_readable_size(group['size'])}]:")
            for p in group["paths"]:
                print(f"    {p}")

    # Warnings
    if skipped:
        print(f"\n=== Warnings ({len(skipped)} files skipped) ===")
        for msg in skipped[:20]:
            print(f"  ! {msg}")
        if len(skipped) > 20:
            print(f"  ... and {len(skipped) - 20} more")

    print()


def _build_json_report(
    root: Path, size: dict, types: dict, dirs: dict, dupes: list, skipped: list
) -> str:
    """Build JSON output."""
    def _path_str(f):
        try:
            return str(f["path"].relative_to(root))
        except ValueError:
            return str(f["path"])

    return json.dumps({
        "root": str(root),
        "size_summary": {
            "total_files": size["count"],
            "total_size_bytes": size["total"],
            "average_size_bytes": round(size["average"], 2),
            "largest_files": [
                {"path": _path_str(f), "size_bytes": f["size"]}
                for f in size.get("largest", [])
            ],
            "smallest_files": [
                {"path": _path_str(f), "size_bytes": f["size"]}
                for f in size.get("smallest", [])
            ],
        },
        "file_types": {
            ext: {"count": info["count"], "total_size_bytes": info["total_size"]}
            for ext, info in types.items()
        },
        "directory_breakdown": {
            name: {"count": info["count"], "total_size_bytes": info["total_size"]}
            for name, info in dirs.items()
        },
        "duplicates": dupes,
        "skipped": skipped,
    }, indent=2, default=str)


def run(args) -> int:
    """Execute the stats command."""
    root = Path(args.directory).resolve()
    if not root.is_dir():
        print(f"Error: '{root}' is not a directory.", file=sys.stderr)
        return 1

    files, skipped = _collect_file_info(root)
    size = _size_stats(files)
    types = _type_stats(files)
    dirs = _dir_stats(files, root)
    dupes = _find_duplicates(files)

    if args.json_output:
        print(_build_json_report(root, size, types, dirs, dupes, skipped))
    else:
        _print_text_report(root, size, types, dirs, dupes, skipped)

    return 0
