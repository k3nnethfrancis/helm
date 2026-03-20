#!/usr/bin/env python3
"""Audit Helm judge reproducibility and observability on saved experiments."""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass
class ExperimentAudit:
    experiment_id: str
    strategy: str | None
    backend: str | None
    model: str | None
    score_dimensions: list[str]
    metadata_complete: bool
    rubric_hashes_present: bool
    artifact_references_resolve: bool
    exact_judge_inputs_present: bool
    deterministic_preprocessing: bool | None
    nondeterministic_backend: bool | None
    missing_fields: list[str]
    missing_artifacts: list[str]
    missing_inputs: list[str]
    score_file_sha256: str
    scores_path: str


def _parse_args() -> argparse.Namespace:
    repo_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "experiment_dirs",
        nargs="+",
        type=Path,
        help="Absolute experiment directories to audit",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Directory to write audit artifacts",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=repo_root,
        help="Helm repo root (default: inferred from script path)",
    )
    return parser.parse_args()


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _flatten_artifact_paths(payload: Any) -> list[str]:
    paths: list[str] = []
    if isinstance(payload, str):
        paths.append(payload)
    elif isinstance(payload, dict):
        for value in payload.values():
            paths.extend(_flatten_artifact_paths(value))
    elif isinstance(payload, list):
        for value in payload:
            paths.extend(_flatten_artifact_paths(value))
    return paths


def _audit_experiment(experiment_dir: Path) -> tuple[ExperimentAudit, dict[str, Any]]:
    scores_path = experiment_dir / "scores.json"
    scores = _load_json(scores_path)
    audit = scores.get("audit", {})
    artifacts = scores.get("artifacts", {})

    required_fields = [
        "judge_backend",
        "judge_model",
        "strategy",
        "created_at",
        "input_view_type",
        "input_preparation",
        "scores",
        "artifacts",
    ]
    missing_fields = [field for field in required_fields if field not in scores]

    referenced_artifacts = sorted(set(_flatten_artifact_paths(artifacts)))
    missing_artifacts = [
        rel_path
        for rel_path in referenced_artifacts
        if not (experiment_dir / rel_path).exists()
    ]

    expected_inputs: list[str] = []
    strategy = scores.get("strategy")
    if strategy == "single":
        expected_inputs = ["judge_artifacts/single_input.md"]
    elif strategy == "hierarchical":
        expected_inputs = ["judge_artifacts/communication_input.md"]
        expected_inputs.extend(
            sorted(_flatten_artifact_paths((artifacts or {}).get("per_agent_inputs", {})))
        )
        expected_inputs.extend(
            sorted(_flatten_artifact_paths((artifacts or {}).get("synthesis_inputs", {})))
        )
    missing_inputs = [
        rel_path
        for rel_path in expected_inputs
        if not (experiment_dir / rel_path).exists()
    ]

    rubric_hashes = audit.get("rubrics") if isinstance(audit, dict) else None
    if not isinstance(rubric_hashes, dict):
        rubric_hashes = {}

    score_dimensions = [
        str(entry.get("dimension"))
        for entry in scores.get("scores", [])
        if isinstance(entry, dict) and isinstance(entry.get("dimension"), str)
    ]

    experiment_audit = ExperimentAudit(
        experiment_id=experiment_dir.name,
        strategy=scores.get("strategy"),
        backend=scores.get("judge_backend"),
        model=scores.get("judge_model"),
        score_dimensions=score_dimensions,
        metadata_complete=not missing_fields,
        rubric_hashes_present=all(dimension in rubric_hashes for dimension in score_dimensions),
        artifact_references_resolve=not missing_artifacts,
        exact_judge_inputs_present=not missing_inputs,
        deterministic_preprocessing=(
            audit.get("deterministic_preprocessing") if isinstance(audit, dict) else None
        ),
        nondeterministic_backend=(
            audit.get("nondeterministic_backend") if isinstance(audit, dict) else None
        ),
        missing_fields=missing_fields,
        missing_artifacts=missing_artifacts,
        missing_inputs=missing_inputs,
        score_file_sha256=_sha256(scores_path),
        scores_path=str(scores_path),
    )

    return experiment_audit, scores


def _render_report(experiments: list[ExperimentAudit]) -> str:
    lines = [
        "# Judge Reproducibility Audit",
        "",
        "This audit checks whether saved judge outputs are inspectable and comparable enough",
        "for future reruns and report use.",
        "",
        "## Criteria",
        "",
        "- metadata complete: backend/model/strategy/input metadata persisted",
        "- rubric hashes present: scored dimensions record rubric fingerprints",
        "- artifact references resolve: saved artifact paths exist on disk",
        "- exact judge inputs present: the actual evidence bundles used for scoring are persisted",
        "- deterministic preprocessing: evidence preparation is rule-based",
        "- nondeterministic backend: final scoring can vary across model reruns",
        "",
    ]

    for audit in experiments:
        lines.extend(
            [
                f"## {audit.experiment_id}",
                "",
                f"- Strategy: `{audit.strategy}`",
                f"- Backend: `{audit.backend}`",
                f"- Model: `{audit.model}`",
                f"- Dimensions: {', '.join(f'`{d}`' for d in audit.score_dimensions) or '`none`'}",
                f"- Metadata complete: `{audit.metadata_complete}`",
                f"- Rubric hashes present: `{audit.rubric_hashes_present}`",
                f"- Artifact references resolve: `{audit.artifact_references_resolve}`",
                f"- Exact judge inputs present: `{audit.exact_judge_inputs_present}`",
                f"- Deterministic preprocessing: `{audit.deterministic_preprocessing}`",
                f"- Nondeterministic backend: `{audit.nondeterministic_backend}`",
                f"- `scores.json` SHA256: `{audit.score_file_sha256}`",
                "",
            ]
        )
        if audit.missing_fields:
            lines.append(f"- Missing fields: `{', '.join(audit.missing_fields)}`")
        if audit.missing_artifacts:
            lines.append(f"- Missing artifacts: `{', '.join(audit.missing_artifacts)}`")
        if audit.missing_inputs:
            lines.append(f"- Missing exact judge inputs: `{', '.join(audit.missing_inputs)}`")
        if audit.missing_fields or audit.missing_artifacts or audit.missing_inputs:
            lines.append("")

    return "\n".join(lines).strip() + "\n"


def main() -> int:
    args = _parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    audits: list[ExperimentAudit] = []
    raw_scores: dict[str, Any] = {}

    for experiment_dir in args.experiment_dirs:
        experiment_audit, scores = _audit_experiment(experiment_dir)
        audits.append(experiment_audit)
        raw_scores[experiment_dir.name] = scores

    summary = {
        "experiments": [asdict(audit) for audit in audits],
    }
    (args.output_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    (args.output_dir / "report.md").write_text(_render_report(audits))
    (args.output_dir / "raw-scores.json").write_text(json.dumps(raw_scores, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
