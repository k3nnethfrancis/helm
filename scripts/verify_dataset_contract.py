#!/usr/bin/env python3
"""Verify a benchmark example using dataset-embedded assertion fields.

Supported row fields:
- expected_files: ["workspace/out.txt", ...]
- must_contain: {"workspace/out.txt": "needle"} or list of needles
- must_not_contain: {"workspace/out.txt": "forbidden"} or list of strings

Exit codes:
- 0: pass
- 2: fail
- 3: unknown/no checks
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _load_row(dataset_path: Path, id_field: str, example_id: str) -> dict[str, Any]:
    with open(dataset_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                continue
            value = row.get(id_field)
            if isinstance(value, str) and value == example_id:
                return row
    raise ValueError(
        f"Example id '{example_id}' not found using field '{id_field}' in {dataset_path}"
    )


def _to_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            if isinstance(item, str):
                out.append(item)
            else:
                out.append(str(item))
        return out
    return []


def _resolve_path(experiment_dir: Path, raw_path: str) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        return path
    return experiment_dir / path


def verify_row(row: dict[str, Any], experiment_dir: Path) -> dict[str, Any]:
    checks_total = 0
    checks_passed = 0
    failures: list[str] = []

    expected_files = _to_list(row.get("expected_files"))
    for rel_path in expected_files:
        checks_total += 1
        path = _resolve_path(experiment_dir, rel_path)
        if path.exists():
            checks_passed += 1
        else:
            failures.append(f"Missing expected file: {rel_path}")

    must_contain = row.get("must_contain", {})
    if isinstance(must_contain, dict):
        for rel_path, needles in must_contain.items():
            if not isinstance(rel_path, str):
                continue
            path = _resolve_path(experiment_dir, rel_path)
            checks_total += 1
            if not path.exists():
                failures.append(f"File not found for must_contain check: {rel_path}")
                continue
            text = path.read_text(errors="replace")
            needle_list = _to_list(needles)
            missing = [needle for needle in needle_list if needle not in text]
            if missing:
                failures.append(f"{rel_path} missing required substrings: {missing}")
            else:
                checks_passed += 1

    must_not_contain = row.get("must_not_contain", {})
    if isinstance(must_not_contain, dict):
        for rel_path, needles in must_not_contain.items():
            if not isinstance(rel_path, str):
                continue
            path = _resolve_path(experiment_dir, rel_path)
            checks_total += 1
            if not path.exists():
                failures.append(f"File not found for must_not_contain check: {rel_path}")
                continue
            text = path.read_text(errors="replace")
            needle_list = _to_list(needles)
            present = [needle for needle in needle_list if needle in text]
            if present:
                failures.append(f"{rel_path} contains forbidden substrings: {present}")
            else:
                checks_passed += 1

    if checks_total == 0:
        return {
            "status": "unknown",
            "score": None,
            "reason": "No dataset checks found (expected_files/must_contain/must_not_contain).",
            "details": {"checks_total": 0, "checks_passed": 0, "failures": []},
        }

    score = checks_passed / checks_total
    status = "pass" if checks_passed == checks_total else "fail"
    reason = (
        "All dataset checks passed."
        if status == "pass"
        else f"{checks_total - checks_passed} of {checks_total} checks failed."
    )
    return {
        "status": status,
        "score": score,
        "reason": reason,
        "details": {
            "checks_total": checks_total,
            "checks_passed": checks_passed,
            "failures": failures,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset-path", required=True, type=Path)
    parser.add_argument("--example-id", required=True)
    parser.add_argument("--experiment-dir", required=True, type=Path)
    parser.add_argument("--id-field", default="instance_id")
    args = parser.parse_args()

    try:
        row = _load_row(args.dataset_path, args.id_field, args.example_id)
        result = verify_row(row, args.experiment_dir)
    except Exception as e:
        payload = {
            "status": "unknown",
            "score": None,
            "reason": f"Verifier error: {e}",
            "details": {},
        }
        print(json.dumps(payload))
        return 3

    print(json.dumps(result))
    if result["status"] == "pass":
        return 0
    if result["status"] == "fail":
        return 2
    return 3


if __name__ == "__main__":
    raise SystemExit(main())

