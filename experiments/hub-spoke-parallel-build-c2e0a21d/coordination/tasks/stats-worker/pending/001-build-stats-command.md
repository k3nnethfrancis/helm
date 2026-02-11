# Task: Build `filekit stats` subcommand

## What to Build

Create `workspace/src/filekit/commands/stats.py` — show statistics about files in a directory.

## Interface Contract

Your module MUST expose a `register(subparsers)` function:

```python
from pathlib import Path

def register(subparsers):
    parser = subparsers.add_parser("stats", help="Show file statistics for a directory")
    # add your arguments here
    parser.set_defaults(func=run)

def run(args):
    # your implementation
    ...
```

## Required Features

`filekit stats <directory>` with these options:

- `directory` (positional) — directory to analyze
- `--by-extension` — break down stats by file extension
- `--top N` — show top N largest files (default: 10)
- `--no-recursive` — only look at top-level directory

Default output should show:
- Total files count
- Total size (human-readable)
- Average file size
- Largest file (name + size)
- Smallest file (name + size)

With `--by-extension`: table of extension, count, total size, average size.

## Shared Utilities Available

Import from `filekit.utils`:
- `walk_files(root, pattern=None, recursive=True)` → list[Path]
- `human_readable_size(size_bytes)` → str like "4.2 MB"
- `format_table(headers, rows)` → formatted table string

Use these — do NOT reimplement them.

## Example Usage

```bash
filekit stats .                        # summary stats
filekit stats . --by-extension         # breakdown by extension
filekit stats /var/log --top 5         # top 5 largest files
filekit stats . --no-recursive         # top-level only
```
