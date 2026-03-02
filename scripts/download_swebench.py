#!/usr/bin/env python3
"""Download SWE-bench dataset from HuggingFace into data/ as JSONL.

Usage:
    python scripts/download_swebench.py                                       # Verified (default)
    python scripts/download_swebench.py --dataset SWE-bench/SWE-bench_Lite    # Lite
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

DEFAULT_DATASET = "princeton-nlp/SWE-bench_Verified"
DEFAULT_SPLIT = "test"
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data"


def download(dataset: str, split: str, output: Path) -> None:
    try:
        from datasets import load_dataset  # type: ignore[import-untyped]
    except ImportError:
        raise SystemExit(
            "Install the datasets library first:  uv pip install datasets"
        )

    print(f"Downloading {dataset} (split={split}) ...")
    ds = load_dataset(dataset, split=split)

    output.parent.mkdir(parents=True, exist_ok=True)
    with open(output, "w") as f:
        for row in ds:
            f.write(json.dumps(row, default=str))
            f.write("\n")

    print(f"Wrote {len(ds)} rows to {output}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Download SWE-bench dataset")
    parser.add_argument(
        "--dataset",
        default=DEFAULT_DATASET,
        help=f"HuggingFace dataset ID (default: {DEFAULT_DATASET})",
    )
    parser.add_argument(
        "--split",
        default=DEFAULT_SPLIT,
        help=f"Dataset split (default: {DEFAULT_SPLIT})",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output path (default: data/swebench_verified.jsonl)",
    )
    args = parser.parse_args()

    if args.output is None:
        # Derive filename from dataset name
        slug = args.dataset.split("/")[-1].lower().replace("-", "_")
        args.output = OUTPUT_DIR / f"{slug}.jsonl"

    download(args.dataset, args.split, args.output)


if __name__ == "__main__":
    main()
