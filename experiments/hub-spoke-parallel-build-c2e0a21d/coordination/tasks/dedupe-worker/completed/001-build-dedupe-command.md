# Task: Build `filekit dedupe` subcommand

## What to Build

Create `workspace/src/filekit/commands/dedupe.py` — find and remove duplicate files.

## Interface Contract

Your module MUST expose a `register(subparsers)` function:

```python
from pathlib import Path

def register(subparsers):
    parser = subparsers.add_parser("dedupe", help="Find and remove duplicate files")
    # add your arguments here
    parser.set_defaults(func=run)

def run(args):
    # your implementation
    ...
```

## Required Features

`filekit dedupe <directory>` with these options:

- `directory` (positional) — root directory to scan
- `--dry-run` — show duplicates without deleting (default behavior)
- `--delete` — actually delete duplicates (keep the first occurrence)
- `--min-size BYTES` — only check files above this size (skip tiny files)
- `--algorithm {md5,sha256}` — hash algorithm (default: sha256)
- `--no-recursive` — don't recurse into subdirectories

Output in dry-run mode: group duplicates, show hash + file paths + sizes.
Output in delete mode: show what was deleted.

## Shared Utilities Available

Import from `filekit.utils`:
- `hash_file(path, algorithm="sha256")` → str hash digest
- `walk_files(root, pattern=None, recursive=True)` → list[Path]
- `human_readable_size(size_bytes)` → str like "4.2 MB"
- `format_table(headers, rows)` → formatted table string

Use `hash_file` for hashing and `walk_files` for traversal — do NOT reimplement these.

## Algorithm

1. Use `walk_files` to get all files
2. Group by file size first (fast pre-filter — files of different sizes can't be dupes)
3. For size groups with >1 file, compute hash via `hash_file`
4. Group by hash — groups with >1 file are duplicates
5. Report or delete

## Example Usage

```bash
filekit dedupe .                          # dry-run, show dupes
filekit dedupe . --delete                 # delete duplicates
filekit dedupe . --min-size 1024          # only check files > 1KB
filekit dedupe /photos --algorithm md5    # use md5 for speed
```
