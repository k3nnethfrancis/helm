# Task: Build `filekit find` subcommand

## What to Build

Create `workspace/src/filekit/commands/find.py` — a file search command.

## Interface Contract

Your module MUST expose a `register(subparsers)` function:

```python
from pathlib import Path

def register(subparsers):
    parser = subparsers.add_parser("find", help="Find files by name, pattern, or content")
    # add your arguments here
    parser.set_defaults(func=run)

def run(args):
    # your implementation
    ...
```

## Required Features

`filekit find <directory>` with these options:

- `directory` (positional) — root directory to search
- `--name PATTERN` — glob pattern for filename matching (e.g., `*.py`)
- `--contains TEXT` — search file contents for text (simple substring match)
- `--min-size BYTES` — minimum file size filter
- `--max-size BYTES` — maximum file size filter
- `--no-recursive` — don't recurse into subdirectories (default: recursive)

Output: one file path per line. If `--contains` is used, show `path:line_number:matching_line`.

## Shared Utilities Available

Import from `filekit.utils`:
- `walk_files(root, pattern=None, recursive=True)` → list[Path]
- `human_readable_size(size_bytes)` → str

Use `walk_files` for directory traversal — do NOT reimplement it.

## Example Usage

```bash
filekit find . --name "*.py"
filekit find /tmp --contains "TODO" --name "*.py"
filekit find . --min-size 1024 --max-size 1048576
```
