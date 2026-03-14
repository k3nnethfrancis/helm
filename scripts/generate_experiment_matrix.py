#!/usr/bin/env python3
"""Generate factorized Helm experiment patterns from a matrix manifest."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from helm.matrix import generate_matrix_patterns


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path, help="Path to matrix manifest YAML")
    parser.add_argument("--wave", type=str, default=None, help="Optional wave to generate")
    parser.add_argument(
        "--output-root",
        type=Path,
        default=None,
        help="Optional output directory for generated patterns",
    )
    args = parser.parse_args()

    payload = generate_matrix_patterns(
        args.manifest,
        output_root=args.output_root,
        wave=args.wave,
    )
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
