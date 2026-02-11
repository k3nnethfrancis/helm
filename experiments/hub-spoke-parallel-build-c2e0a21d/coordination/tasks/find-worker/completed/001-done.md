# Task 001 — Build `filekit find` subcommand: COMPLETE

## What was built

Implemented `workspace/src/filekit/commands/find.py` — the file search subcommand for filekit.

## Interface

- `register(subparsers)` — registers the `find` subcommand with argparse
- `run(args)` — executes the find command

## Arguments implemented

| Argument | Type | Description |
|---|---|---|
| `directory` | positional | Root directory to search |
| `--name PATTERN` | optional | Glob pattern for filename matching |
| `--contains TEXT` | optional | Substring match on file contents |
| `--min-size BYTES` | optional (int) | Minimum file size filter |
| `--max-size BYTES` | optional (int) | Maximum file size filter |
| `--no-recursive` | flag | Disable recursive directory traversal |

## Output format

- Default: one file path per line
- With `--contains`: `path:line_number:matching_line` for each matching line

## Shared utilities used

- `walk_files(root, pattern, recursive)` from `filekit.utils` — used for all directory traversal
- `human_readable_size` imported (available if needed by downstream consumers)

## Key design decisions

- Replaced the pre-existing scaffold which had a different interface (`root` positional, `-p/--pattern`, `-c/--content` with regex, `-r/--regex`, `--newer/--older`, `-v/--verbose`, `handler` function name). Rewrote to match the task spec exactly.
- `--contains` uses simple substring match (not regex) as specified.
- `--min-size` and `--max-size` accept integer bytes directly (not human-readable strings).
- Size filters are applied via `path.stat().st_size` with graceful handling of `OSError`/`PermissionError`.
- Content search reads files line-by-line to produce `path:line_number:matching_line` output, using `errors="replace"` for binary-safe reading.
- Errors (non-existent directory, not a directory) print to stderr and exit with code 1.
