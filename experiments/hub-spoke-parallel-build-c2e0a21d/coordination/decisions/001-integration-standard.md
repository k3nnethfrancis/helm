# Decision 001: Integration Standard

## Context
Workers have produced outputs with inconsistent APIs. find-worker used typer, rename-worker created a separate output.py module, and the scaffold uses argparse with a register(subparsers) pattern.

## Decision
All subcommands MUST conform to this interface:

1. Live at `workspace/src/filekit/commands/{name}.py`
2. Export a `register(subparsers)` function that adds a subparser and sets `args.func`
3. Use `argparse` (not typer) — no external dependencies
4. Import shared utilities from `filekit.utils` (FileInfo, walk_files, file_hash, human_readable_size, format_table)
5. Return `int` (0 for success, non-zero for error) from the command function

## Shared Utilities (filekit.utils)
- `FileInfo` dataclass — path, size, modified, is_symlink
- `walk_files(root, pattern, include_hidden, follow_symlinks)` — returns list[FileInfo]
- `file_hash(path, algorithm)` — returns hex digest
- `human_readable_size(size_bytes)` — returns formatted string
- `format_table(headers, rows)` — returns aligned text table

## Impact
- find.py will be adapted from typer to argparse
- rename.py will be adapted to use filekit.utils instead of output.py
- output.py ANSI styling will be merged into utils.py as needed
- dedupe-worker and stats-worker should follow this standard from the start
