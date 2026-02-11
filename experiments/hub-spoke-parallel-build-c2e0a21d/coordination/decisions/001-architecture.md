# Decision 001: filekit Architecture

## Package Structure

```
workspace/src/filekit/
├── __init__.py        # Package init
├── cli.py             # Entry point: argparse with subparsers
├── utils.py           # Shared utilities (see below)
└── commands/
    ├── __init__.py
    ├── find.py        # find-worker
    ├── dedupe.py      # dedupe-worker
    ├── rename.py      # rename-worker
    └── stats.py       # stats-worker
```

## Subcommand Interface Contract

Every command module MUST expose a `register(subparsers)` function that:
1. Adds a subparser via `subparsers.add_parser(name, help=...)`
2. Adds arguments to the subparser
3. Sets `parser.set_defaults(func=run)` where `run(args)` executes the command

Example skeleton:
```python
def register(subparsers):
    parser = subparsers.add_parser("example", help="Does a thing")
    parser.add_argument("path", type=Path)
    parser.set_defaults(func=run)

def run(args):
    # implementation
    ...
```

## Shared Utilities (filekit.utils)

Available to all commands — import via `from filekit.utils import ...`:

- `hash_file(path, algorithm="sha256")` → str hash
- `human_readable_size(size_bytes)` → str like "4.2 MB"
- `walk_files(root, pattern=None, recursive=True)` → list[Path]
- `format_table(headers, rows)` → str formatted table

## Cross-cutting Dependencies

- **find** and **dedupe** both need `walk_files` and `hash_file`
- **stats** and **find** both need `walk_files` and `human_readable_size`
- **dedupe** and **stats** both need `hash_file`
- All commands should use `format_table` for structured output

## No External Dependencies

stdlib only. No click, typer, rich, etc. Keep it simple.
