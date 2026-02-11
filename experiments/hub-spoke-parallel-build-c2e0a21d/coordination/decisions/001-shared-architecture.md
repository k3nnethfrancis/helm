# Decision 001: Shared Architecture

## Date
2026-02-10

## Context
Four workers each build one subcommand. They share common needs:
file walking, hashing, human-readable sizes, table formatting.

## Decision
- **Shared utils** in `src/filekit/utils.py` provide: `FileInfo`, `walk_files()`, `file_hash()`, `human_readable_size()`, `format_table()`
- **CLI entry point** in `src/filekit/cli.py` uses argparse with subparsers
- Each command module lives in `src/filekit/commands/{name}.py`
- Each module must export a `register(subparsers)` function that adds its subparser and sets `args.func`
- No external dependencies — stdlib only
- Output goes to stdout as text; use `format_table()` for tabular data

## Cross-cutting Dependencies Identified
- `find` and `stats` both need `walk_files()` — shared via utils
- `dedupe` needs both `walk_files()` and `file_hash()` — shared via utils
- `rename` needs `walk_files()` for batch operations — shared via utils
- `stats` and `dedupe` both need `human_readable_size()` — shared via utils

## Module Contract
Each `commands/{name}.py` must:
1. Define `register(subparsers)` that calls `subparsers.add_parser(...)` and sets `args.func`
2. Return `int` (0 for success, 1 for error) from the handler function
3. Print output to stdout
4. Print errors to stderr
