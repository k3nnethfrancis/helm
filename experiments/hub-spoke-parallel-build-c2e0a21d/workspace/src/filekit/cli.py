"""filekit CLI entry point."""

import argparse
import sys


def main():
    parser = argparse.ArgumentParser(
        prog="filekit",
        description="A CLI toolkit for file operations.",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Import and register each subcommand
    from filekit.commands import find, dedupe, rename, stats

    find.register(subparsers)
    dedupe.register(subparsers)
    rename.register(subparsers)
    stats.register(subparsers)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    # Each subcommand sets a 'func' attribute on args
    args.func(args)


if __name__ == "__main__":
    main()
