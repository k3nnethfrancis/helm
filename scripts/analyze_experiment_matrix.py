#!/usr/bin/env python3
"""Analyze matrix-produced Helm benchmark summaries."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from helm.matrix import analyze_matrix_summaries, load_matrix_json


def _summary_paths_from_matrix(matrix_json: Path, wave: str | None) -> list[Path]:
    payload = load_matrix_json(matrix_json)
    summary_paths: list[Path] = []
    for condition in payload.get("conditions", []):
        if not isinstance(condition, dict):
            continue
        if wave is not None and condition.get("wave") != wave:
            continue
        summary_path = condition.get("summary_path")
        if isinstance(summary_path, str) and summary_path:
            summary_paths.append(Path(summary_path))
    return summary_paths


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--matrix-json",
        type=Path,
        default=None,
        help="Matrix JSON with recorded summary paths",
    )
    parser.add_argument(
        "--summary",
        type=Path,
        action="append",
        default=[],
        help="Explicit summary JSON path (repeatable)",
    )
    parser.add_argument("--wave", type=str, default=None, help="Optional wave filter")
    parser.add_argument(
        "--experiments-dir",
        type=Path,
        default=None,
        help="Experiment directory root (defaults to repo experiments/)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Directory for matrix-summary.json and matrix-report.md",
    )
    args = parser.parse_args()

    summary_paths = [path.resolve() for path in args.summary]
    if args.matrix_json is not None:
        summary_paths.extend(_summary_paths_from_matrix(args.matrix_json.resolve(), args.wave))
    summary_paths = list(dict.fromkeys(summary_paths))
    if not summary_paths:
        raise SystemExit("No summary files provided.")

    payload = analyze_matrix_summaries(
        summary_paths,
        experiments_dir=args.experiments_dir.resolve() if args.experiments_dir else None,
        output_dir=args.output_dir.resolve() if args.output_dir else None,
    )
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
