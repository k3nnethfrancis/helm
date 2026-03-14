#!/usr/bin/env python3
"""Run a generated Helm experiment matrix wave and analyze the results."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from helm.matrix import (
    DEFAULT_EXPERIMENTS_DIR,
    REPO_ROOT,
    analyze_matrix_summaries,
    generate_matrix_patterns,
    load_matrix_json,
    load_matrix_manifest,
    record_condition_execution,
)

SUMMARY_PATH_RE = re.compile(r"Summary JSON:\s*(?P<path>.+)$", re.MULTILINE)


def _load_or_generate_matrix(
    manifest_path: Path,
    wave: str | None,
    output_root: Path | None,
) -> tuple[dict[str, Any], Path]:
    generated = generate_matrix_patterns(
        manifest_path,
        output_root=output_root,
        wave=wave,
    )
    matrix_json = Path(str(generated["matrix_json"]))
    return load_matrix_json(matrix_json), matrix_json


def _filter_conditions(matrix_payload: dict[str, Any], wave: str | None) -> list[dict[str, Any]]:
    conditions = matrix_payload.get("conditions", [])
    if not isinstance(conditions, list):
        return []
    filtered: list[dict[str, Any]] = []
    for condition in conditions:
        if not isinstance(condition, dict):
            continue
        if wave is not None and condition.get("wave") != wave:
            continue
        filtered.append(condition)
    return filtered


def _parse_summary_path(stdout: str) -> Path | None:
    match = SUMMARY_PATH_RE.search(stdout)
    if match is None:
        return None
    return Path(match.group("path").strip())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path, help="Path to matrix manifest YAML")
    parser.add_argument("--wave", type=str, default="wave0", help="Wave to execute")
    parser.add_argument(
        "--output-root",
        type=Path,
        default=None,
        help="Optional output directory for generated patterns",
    )
    parser.add_argument(
        "--experiments-dir",
        type=Path,
        default=DEFAULT_EXPERIMENTS_DIR,
        help="Experiment directory root",
    )
    parser.add_argument(
        "--continue-on-error",
        action="store_true",
        help="Continue remaining conditions after a failure",
    )
    parser.add_argument(
        "--no-analyze",
        action="store_true",
        help="Skip matrix analysis after execution",
    )
    args = parser.parse_args()

    manifest = load_matrix_manifest(args.manifest.resolve())
    matrix_payload, matrix_json = _load_or_generate_matrix(
        args.manifest.resolve(),
        args.wave,
        args.output_root.resolve() if args.output_root else None,
    )
    conditions = _filter_conditions(matrix_payload, args.wave)
    if not conditions:
        raise SystemExit(f"No conditions found for wave `{args.wave}`.")

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    analysis_dir = (
        args.experiments_dir.resolve()
        / "analyses"
        / f"{manifest.matrix_id}-{args.wave}-{timestamp}"
    )
    logs_dir = analysis_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    run_record: dict[str, Any] = {
        "matrix_id": manifest.matrix_id,
        "wave": args.wave,
        "manifest_path": str(args.manifest.resolve()),
        "matrix_json": str(matrix_json),
        "started_at": datetime.now().isoformat(),
        "conditions": [],
    }

    summary_paths: list[Path] = []
    run_record_path = analysis_dir / "run-record.json"

    def _write_run_record() -> None:
        with open(run_record_path, "w") as f:
            json.dump(run_record, f, indent=2)

    _write_run_record()

    for condition in conditions:
        condition_id = str(condition.get("condition_id"))
        pattern_path = Path(str(condition.get("pattern_path"))).resolve()
        example_ids = condition.get("example_ids", [])
        sample_size = len(example_ids) if isinstance(example_ids, list) and example_ids else 1

        print(
            f"[matrix] running {condition_id} "
            f"({condition.get('architecture_family')} size={condition.get('swarm_size')}, "
            f"examples={sample_size})"
        )

        command = [
            "uv",
            "run",
            "helm",
            "benchmark",
            "run",
            str(pattern_path),
            "--sample-size",
            str(sample_size),
            "--experiments-dir",
            str(args.experiments_dir.resolve()),
            "--on-turn-limit",
            manifest.defaults.on_turn_limit,
        ]
        if manifest.defaults.direct_cli:
            command.append("--direct-cli")

        proc = subprocess.run(
            command,
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )

        stdout_log = logs_dir / f"{condition_id}.stdout.log"
        stderr_log = logs_dir / f"{condition_id}.stderr.log"
        stdout_log.write_text(proc.stdout)
        stderr_log.write_text(proc.stderr)

        summary_path = _parse_summary_path(proc.stdout)
        status = "completed" if proc.returncode == 0 and summary_path is not None else "failed"

        condition_result = {
            "condition_id": condition_id,
            "pattern_path": str(pattern_path),
            "command": command,
            "returncode": proc.returncode,
            "status": status,
            "stdout_log": str(stdout_log),
            "stderr_log": str(stderr_log),
            "summary_path": str(summary_path) if summary_path is not None else None,
        }
        condition_result.update(
            {
                field: condition.get(field)
                for field in (
                    "architecture_family",
                    "swarm_size",
                    "task_pack",
                    "task_structure",
                    "prompt_family",
                    "coordination_family",
                    "runtime_pattern",
                    "wave",
                )
            }
        )
        run_record["conditions"].append(condition_result)

        record_condition_execution(
            matrix_payload,
            condition_id,
            {
                "summary_path": str(summary_path) if summary_path is not None else None,
                "status": status,
                "returncode": proc.returncode,
                "stdout_log": str(stdout_log),
                "stderr_log": str(stderr_log),
            },
        )

        if summary_path is not None:
            summary_paths.append(summary_path.resolve())

        print(
            f"[matrix] finished {condition_id} -> {status}"
            + (f" ({summary_path})" if summary_path is not None else "")
        )
        _write_run_record()

        if proc.returncode != 0 and not args.continue_on_error:
            break

    with open(matrix_json, "w") as f:
        json.dump(matrix_payload, f, indent=2)

    analysis_payload = None
    if summary_paths and not args.no_analyze:
        analysis_payload = analyze_matrix_summaries(
            summary_paths,
            experiments_dir=args.experiments_dir.resolve(),
            output_dir=analysis_dir,
        )

    run_record["finished_at"] = datetime.now().isoformat()
    run_record["analysis_dir"] = str(analysis_dir)
    if analysis_payload is not None:
        run_record["matrix_summary_path"] = analysis_payload.get("summary_path")
        run_record["matrix_report_path"] = analysis_payload.get("report_path")

    _write_run_record()

    print(json.dumps(run_record, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
