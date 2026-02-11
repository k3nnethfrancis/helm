# Task: Build `filekit rename` subcommand

## What to Build

Create `workspace/src/filekit/commands/rename.py` — batch rename files using patterns.

## Interface Contract

Your module MUST expose a `register(subparsers)` function:

```python
from pathlib import Path

def register(subparsers):
    parser = subparsers.add_parser("rename", help="Batch rename files using patterns")
    # add your arguments here
    parser.set_defaults(func=run)

def run(args):
    # your implementation
    ...
```

## Required Features

`filekit rename <directory>` with these options:

- `directory` (positional) — directory containing files to rename
- `--pattern REGEX` — regex pattern to match in filenames
- `--replace TEMPLATE` — replacement string (supports regex groups: `\1`, `\2`)
- `--prefix PREFIX` — add prefix to all filenames
- `--suffix SUFFIX` — add suffix before extension (e.g., `photo.jpg` → `photo_backup.jpg`)
- `--dry-run` — show renames without executing (default behavior)
- `--execute` — actually perform the renames
- `--no-recursive` — only rename in top-level directory (default: recursive)

Output: show `old_name → new_name` for each file affected.

## Shared Utilities Available

Import from `filekit.utils`:
- `walk_files(root, pattern=None, recursive=True)` → list[Path]

Use `walk_files` for directory traversal — do NOT reimplement it.

## Important

- NEVER overwrite existing files. If a rename would collide, skip it and warn.
- Use `--dry-run` as default. Require explicit `--execute` to make changes.
- Use Python's `re` module for pattern/replace.

## Example Usage

```bash
filekit rename . --pattern "IMG_(\d+)" --replace "photo_\1"    # dry-run
filekit rename . --prefix "2026-" --execute                     # add prefix
filekit rename . --suffix "_backup" --dry-run                   # preview suffix addition
filekit rename /docs --pattern "\.txt$" --replace ".md" --execute
```
