"""Helpers for generating, running, and analyzing factorized experiment matrices."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from statistics import mean
from typing import Any

import yaml
from pydantic import BaseModel, Field, model_validator

from helm.config import ExperimentConfig
from helm.matrix_families import (
    COORDINATION_FAMILY_LABELS,
    FAMILY_LAYOUTS,
    SUPPORTED_FAMILY_SIZES,
    RoleSpec,
    build_coordination,
    build_orchestrator,
    build_prompt,
    get_disallowed_tools,
    pattern_runtime_label,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_GENERATED_ROOT = REPO_ROOT / "runs" / "generated"
DEFAULT_EXPERIMENTS_DIR = REPO_ROOT / "runs"
ACTIVE_DIMENSIONS = [
    "escalation-calibration",
    "goal-drift",
    "failure-suppression",
    "context-degradation",
    "resource-waste",
    "human-model-accuracy",
]
MATRIX_METADATA_FIELDS = [
    "matrix_id",
    "condition_id",
    "base_condition_id",
    "harness",
    "architecture_family",
    "swarm_size",
    "task_pack",
    "task_structure",
    "prompt_family",
    "coordination_family",
    "replication_index",
    "replication_count",
    "turn_limit_variant",
]

class MatrixExampleSpec(BaseModel):
    example_id: str
    rationale: str


class MatrixTaskPack(BaseModel):
    task_structure: str
    rationale: str
    primary_examples: list[MatrixExampleSpec] = Field(default_factory=list)
    backup_examples: list[MatrixExampleSpec] = Field(default_factory=list)


class MatrixDefaults(BaseModel):
    harness: str = "claude-code"
    model: str | None = None
    prompt_family: str
    dimensions: list[str] = Field(default_factory=lambda: ACTIVE_DIMENSIONS.copy())
    judge_backend: str = "claude-headless"
    judge_model: str | None = None
    benchmark: dict[str, Any]
    single_limits: dict[str, Any] = Field(default_factory=dict)
    multi_agent_limits: dict[str, Any] = Field(default_factory=dict)
    direct_cli: bool = True
    on_turn_limit: str = "end"


class MatrixWave(BaseModel):
    families: list[str]
    sizes: list[int]
    anchor_pack: str | None = None
    anchor_example_id: str | None = None
    pack_examples: dict[str, int | str] = Field(default_factory=dict)
    replications: int = 1
    turn_limits: list[int] = Field(default_factory=list)
    notes: str | None = None


class MatrixManifest(BaseModel):
    matrix_id: str
    description: str = ""
    output_root: str | None = None
    defaults: MatrixDefaults
    task_packs: dict[str, MatrixTaskPack]
    waves: dict[str, MatrixWave]

    @model_validator(mode="after")
    def validate_manifest(self) -> "MatrixManifest":
        for wave_name, wave in self.waves.items():
            for family in wave.families:
                if family not in SUPPORTED_FAMILY_SIZES:
                    raise ValueError(f"Unknown architecture family `{family}` in {wave_name}")
            if wave.anchor_example_id and not wave.anchor_pack:
                raise ValueError(f"{wave_name} defines anchor_example_id without anchor_pack")
            if wave.anchor_pack and wave.anchor_pack not in self.task_packs:
                raise ValueError(f"{wave_name} references unknown anchor_pack `{wave.anchor_pack}`")
            for pack_name in wave.pack_examples:
                if pack_name not in self.task_packs:
                    raise ValueError(f"{wave_name} references unknown task pack `{pack_name}`")
        return self


@dataclass(frozen=True)
class GeneratedCondition:
    wave: str
    condition_id: str
    base_condition_id: str
    harness: str
    architecture_family: str
    swarm_size: int
    task_pack: str
    task_structure: str
    example_ids: list[str]
    prompt_family: str
    coordination_family: str
    runtime_pattern: str
    replication_index: int
    replication_count: int
    turn_limit_variant: int | None
    name: str
    description: str
    pattern_path: Path

    def matrix_metadata(self, matrix_id: str) -> dict[str, Any]:
        return {
            "matrix_id": matrix_id,
            "condition_id": self.condition_id,
            "base_condition_id": self.base_condition_id,
            "harness": self.harness,
            "architecture_family": self.architecture_family,
            "swarm_size": self.swarm_size,
            "task_pack": self.task_pack,
            "task_structure": self.task_structure,
            "prompt_family": self.prompt_family,
            "coordination_family": self.coordination_family,
            "replication_index": self.replication_index,
            "replication_count": self.replication_count,
            "turn_limit_variant": self.turn_limit_variant,
        }


class _LiteralDumper(yaml.SafeDumper):
    pass


def _repr_multiline_str(dumper: yaml.SafeDumper, value: str) -> yaml.nodes.ScalarNode:
    style = "|" if "\n" in value else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", value, style=style)


_LiteralDumper.add_representer(str, _repr_multiline_str)


def load_matrix_manifest(path: Path) -> MatrixManifest:
    with open(path) as f:
        raw = yaml.safe_load(f)
    if not isinstance(raw, dict):
        raise ValueError(f"Matrix manifest must decode to a mapping: {path}")
    return MatrixManifest.model_validate(raw)


def _normalize_output_root(manifest: MatrixManifest, output_root: Path | None = None) -> Path:
    if output_root is not None:
        return output_root
    configured = manifest.output_root or f"patterns/generated/{manifest.matrix_id}"
    root = Path(configured)
    if root.is_absolute():
        return root
    return REPO_ROOT / root


def _build_agents(defaults: MatrixDefaults, family: str, size: int) -> list[dict[str, Any]]:
    layout = FAMILY_LAYOUTS[family][size]
    agents: list[dict[str, Any]] = []
    for role in layout:
        payload: dict[str, Any] = {
            "id": role.agent_id,
            "harness": defaults.harness,
            "system_prompt": build_prompt(family, layout, role),
        }
        if defaults.model:
            payload["model"] = defaults.model
        if role.runtime_role:
            payload["role"] = role.runtime_role
        disallowed = get_disallowed_tools(family, role.runtime_role or "worker")
        if disallowed:
            payload["disallowed_tools"] = disallowed
        agents.append(payload)
    return agents

def _build_limits(defaults: MatrixDefaults, swarm_size: int) -> dict[str, Any]:
    base = defaults.single_limits if swarm_size == 1 else defaults.multi_agent_limits
    return dict(base)


def _build_evaluation(defaults: MatrixDefaults) -> dict[str, Any]:
    judge: dict[str, Any] = {"backend": defaults.judge_backend}
    if defaults.judge_model:
        judge["model"] = defaults.judge_model
    return {
        "dimensions": defaults.dimensions,
        "judge": judge,
    }


def _build_benchmark(defaults: MatrixDefaults, example_ids: list[str]) -> dict[str, Any]:
    benchmark = dict(defaults.benchmark)
    benchmark["example_ids"] = example_ids
    benchmark["max_examples"] = len(example_ids)
    return benchmark


def _condition_name(matrix_id: str, wave: str, family: str, size: int, task_pack: str) -> str:
    return f"{matrix_id}-{wave}-{family}-{size}-{task_pack}".replace("_", "-")


def _condition_description(
    family: str,
    size: int,
    task_pack: str,
    task_structure: str,
    example_ids: list[str],
) -> str:
    return (
        f"{family} architecture, swarm size {size}, task pack {task_pack} "
        f"({task_structure}), examples: {', '.join(example_ids)}"
    )


def _select_examples_for_wave(
    manifest: MatrixManifest,
    wave_name: str,
    wave: MatrixWave,
) -> list[tuple[str, str, list[str], str]]:
    if wave.anchor_example_id and wave.anchor_pack:
        pack = manifest.task_packs[wave.anchor_pack]
        return [
            (
                wave.anchor_pack,
                pack.task_structure,
                [wave.anchor_example_id],
                "anchor",
            )
        ]

    selected: list[tuple[str, str, list[str], str]] = []
    for pack_name, requested in wave.pack_examples.items():
        pack = manifest.task_packs[pack_name]
        example_ids = [example.example_id for example in pack.primary_examples]
        if requested == "all":
            chosen = example_ids
            label = "all"
        else:
            count = int(requested)
            chosen = example_ids[:count]
            label = str(count)
        if not chosen:
            continue
        selected.append((pack_name, pack.task_structure, chosen, label))
    return selected


def _build_condition(
    manifest: MatrixManifest,
    wave_name: str,
    family: str,
    size: int,
    task_pack: str,
    task_structure: str,
    example_ids: list[str],
    selection_label: str,
    output_root: Path,
    replication_index: int = 1,
    replication_count: int = 1,
    turn_limit_variant: int | None = None,
) -> GeneratedCondition:
    base_condition_id = f"{wave_name}-{family}-{size}-{task_pack}-{selection_label}"
    condition_id = base_condition_id
    if turn_limit_variant is not None:
        condition_id = f"{condition_id}-t{turn_limit_variant}"
    if replication_count > 1:
        condition_id = f"{condition_id}-r{replication_index}"

    name = _condition_name(manifest.matrix_id, wave_name, family, size, task_pack)
    if turn_limit_variant is not None:
        name = f"{name}-t{turn_limit_variant}"
    if replication_count > 1:
        name = f"{name}-r{replication_index}"
    description = _condition_description(
        family=family,
        size=size,
        task_pack=task_pack,
        task_structure=task_structure,
        example_ids=example_ids,
    )
    if turn_limit_variant is not None:
        description += f", turn limit {turn_limit_variant}"
    if replication_count > 1:
        description += f", replication {replication_index}/{replication_count}"
    pattern_path = output_root / f"{name}.yaml"
    return GeneratedCondition(
        wave=wave_name,
        condition_id=condition_id,
        base_condition_id=base_condition_id,
        harness=manifest.defaults.harness,
        architecture_family=family,
        swarm_size=size,
        task_pack=task_pack,
        task_structure=task_structure,
        example_ids=example_ids,
        prompt_family=manifest.defaults.prompt_family,
        coordination_family=COORDINATION_FAMILY_LABELS[family],
        runtime_pattern=pattern_runtime_label(family),
        replication_index=replication_index,
        replication_count=replication_count,
        turn_limit_variant=turn_limit_variant,
        name=name,
        description=description,
        pattern_path=pattern_path,
    )


def _write_pattern(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        yaml.dump(payload, f, Dumper=_LiteralDumper, sort_keys=False, width=100)


def _render_condition_payload(
    manifest: MatrixManifest,
    condition: GeneratedCondition,
) -> dict[str, Any]:
    agents = _build_agents(
        defaults=manifest.defaults,
        family=condition.architecture_family,
        size=condition.swarm_size,
    )
    limits = _build_limits(manifest.defaults, condition.swarm_size)
    if condition.turn_limit_variant is not None:
        limits["max_turns_per_agent"] = condition.turn_limit_variant

    payload = {
        "name": condition.name,
        "description": condition.description,
        "agents": agents,
        "orchestrator": build_orchestrator(condition.architecture_family),
        "coordination": build_coordination(condition.architecture_family),
        "benchmark": _build_benchmark(manifest.defaults, condition.example_ids),
        "evaluation": _build_evaluation(manifest.defaults),
        "limits": limits,
        "metadata": {
            "created": date.today().isoformat(),
            "version": 1,
            "matrix": condition.matrix_metadata(manifest.matrix_id),
        },
    }
    config = ExperimentConfig.model_validate(payload)
    return config.model_dump(mode="json", by_alias=True, exclude_none=True)


def generate_matrix_patterns(
    manifest_path: Path,
    *,
    output_root: Path | None = None,
    wave: str | None = None,
) -> dict[str, Any]:
    manifest = load_matrix_manifest(manifest_path)
    resolved_output_root = _normalize_output_root(manifest, output_root)
    resolved_output_root.mkdir(parents=True, exist_ok=True)

    selected_waves = (
        {wave: manifest.waves[wave]}
        if wave is not None
        else manifest.waves
    )

    conditions: list[GeneratedCondition] = []
    for wave_name, wave_config in selected_waves.items():
        if wave_name not in manifest.waves:
            raise ValueError(f"Unknown wave `{wave_name}`")
        pack_entries = _select_examples_for_wave(manifest, wave_name, wave_config)
        for family in wave_config.families:
            for size in wave_config.sizes:
                if size not in SUPPORTED_FAMILY_SIZES[family]:
                    continue
                for task_pack, task_structure, example_ids, selection_label in pack_entries:
                    turn_limit_variants = wave_config.turn_limits or [None]
                    for turn_limit_variant in turn_limit_variants:
                        for replication_index in range(1, wave_config.replications + 1):
                            conditions.append(
                                _build_condition(
                                    manifest=manifest,
                                    wave_name=wave_name,
                                    family=family,
                                    size=size,
                                    task_pack=task_pack,
                                    task_structure=task_structure,
                                    example_ids=example_ids,
                                    selection_label=selection_label,
                                    output_root=resolved_output_root,
                                    replication_index=replication_index,
                                    replication_count=wave_config.replications,
                                    turn_limit_variant=turn_limit_variant,
                                )
                            )

    written_conditions: list[dict[str, Any]] = []
    for condition in conditions:
        payload = _render_condition_payload(manifest, condition)
        _write_pattern(condition.pattern_path, payload)
        written_conditions.append(
            {
                "wave": condition.wave,
                "condition_id": condition.condition_id,
                "pattern_path": str(condition.pattern_path),
                "name": condition.name,
                "description": condition.description,
                "runtime_pattern": condition.runtime_pattern,
                "example_ids": condition.example_ids,
                **condition.matrix_metadata(manifest.matrix_id),
            }
        )

    matrix_payload = {
        "matrix_id": manifest.matrix_id,
        "description": manifest.description,
        "manifest_path": str(manifest_path),
        "output_root": str(resolved_output_root),
        "generated_at": datetime.now().isoformat(),
        "defaults": {
            "prompt_family": manifest.defaults.prompt_family,
            "direct_cli": manifest.defaults.direct_cli,
            "on_turn_limit": manifest.defaults.on_turn_limit,
            "dimensions": manifest.defaults.dimensions,
        },
        "conditions": written_conditions,
    }
    matrix_json = resolved_output_root / "matrix.json"
    with open(matrix_json, "w") as f:
        json.dump(matrix_payload, f, indent=2)

    return {
        "matrix_id": manifest.matrix_id,
        "manifest_path": str(manifest_path),
        "output_root": str(resolved_output_root),
        "matrix_json": str(matrix_json),
        "conditions": written_conditions,
    }


def load_matrix_json(path: Path) -> dict[str, Any]:
    with open(path) as f:
        payload = json.load(f)
    if not isinstance(payload, dict):
        raise ValueError(f"Matrix JSON must decode to an object: {path}")
    return payload


def record_condition_execution(
    matrix_payload: dict[str, Any],
    condition_id: str,
    execution_fields: dict[str, Any],
) -> dict[str, Any]:
    """Update one condition entry in-place without dropping pending conditions."""
    conditions = matrix_payload.get("conditions", [])
    if not isinstance(conditions, list):
        raise ValueError("matrix payload missing conditions list")

    for condition in conditions:
        if not isinstance(condition, dict):
            continue
        if condition.get("condition_id") != condition_id:
            continue
        condition.update(execution_fields)
        return condition

    raise KeyError(f"Unknown condition_id `{condition_id}`")


def _load_run_data(experiments_dir: Path, experiment_id: str) -> dict[str, Any]:
    run_data_path = experiments_dir / experiment_id / "run_data.json"
    if not run_data_path.exists():
        return {}
    with open(run_data_path) as f:
        payload = json.load(f)
    return payload if isinstance(payload, dict) else {}


def _load_transcript_usage(experiments_dir: Path, experiment_id: str) -> dict[str, int]:
    transcript_path = experiments_dir / experiment_id / "transcripts" / "full.json"
    if not transcript_path.exists():
        return {"input_tokens": 0, "output_tokens": 0}
    with open(transcript_path) as f:
        payload = json.load(f)
    if not isinstance(payload, dict):
        return {"input_tokens": 0, "output_tokens": 0}

    input_tokens = 0
    output_tokens = 0
    agents = payload.get("agents", {})
    if not isinstance(agents, dict):
        return {"input_tokens": 0, "output_tokens": 0}

    for agent_data in agents.values():
        if not isinstance(agent_data, dict):
            continue
        items = agent_data.get("items", [])
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            data = item.get("data", {})
            if not isinstance(data, dict):
                continue
            usage = data.get("usage")
            if not isinstance(usage, dict):
                raw = data.get("raw", {})
                if isinstance(raw, dict):
                    usage = raw.get("usage")
            if not isinstance(usage, dict):
                continue
            input_value = usage.get("input_tokens")
            output_value = usage.get("output_tokens")
            if isinstance(input_value, int):
                input_tokens += input_value
            if isinstance(output_value, int):
                output_tokens += output_value
    return {"input_tokens": input_tokens, "output_tokens": output_tokens}


def _flatten_matrix(matrix: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(matrix, dict):
        return {field: None for field in MATRIX_METADATA_FIELDS}
    return {field: matrix.get(field) for field in MATRIX_METADATA_FIELDS}


def _mode(values: list[str]) -> str | None:
    filtered = [value for value in values if value]
    if not filtered:
        return None
    return Counter(filtered).most_common(1)[0][0]


def analyze_matrix_summaries(
    summary_paths: list[Path],
    *,
    experiments_dir: Path | None = None,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    if not summary_paths:
        raise ValueError("Provide at least one summary path.")

    resolved_experiments_dir = experiments_dir or DEFAULT_EXPERIMENTS_DIR
    rows: list[dict[str, Any]] = []
    matrix_id: str | None = None

    for summary_path in summary_paths:
        with open(summary_path) as f:
            payload = json.load(f)
        if not isinstance(payload, dict):
            continue

        top_matrix = payload.get("matrix")
        if isinstance(top_matrix, dict) and matrix_id is None:
            matrix_id = str(top_matrix.get("matrix_id") or "")

        results = payload.get("results", [])
        if not isinstance(results, list):
            continue

        for result in results:
            if not isinstance(result, dict):
                continue
            experiment_id = result.get("experiment_id")
            if not isinstance(experiment_id, str):
                continue

            run_data = _load_run_data(resolved_experiments_dir, experiment_id)
            experiment = run_data.get("experiment", {})
            if not isinstance(experiment, dict):
                experiment = {}
            run = run_data.get("run", {})
            if not isinstance(run, dict):
                run = {}
            evals = run_data.get("evals", {})
            if not isinstance(evals, dict):
                evals = {}
            orchestration = evals.get("orchestration", {})
            if not isinstance(orchestration, dict):
                orchestration = {}
            judge = evals.get("judge", {})
            if not isinstance(judge, dict):
                judge = {}
            judge_scores = judge.get("scores", {})
            if not isinstance(judge_scores, dict):
                judge_scores = {}
            summary_judge_scores = result.get("judge_scores")
            if not isinstance(summary_judge_scores, dict):
                summary_judge_scores = {}

            matrix = experiment.get("matrix")
            if not isinstance(matrix, dict):
                candidate_matrix = result.get("matrix")
                matrix = candidate_matrix if isinstance(candidate_matrix, dict) else None
            if matrix_id is None and isinstance(matrix, dict):
                matrix_id = str(matrix.get("matrix_id") or "")

            task_verification = run.get("task_verification", {})
            if not isinstance(task_verification, dict):
                task_verification = {}
            usage = _load_transcript_usage(resolved_experiments_dir, experiment_id)
            flattened_matrix = _flatten_matrix(matrix)

            row: dict[str, Any] = {
                "summary_path": str(summary_path),
                "experiment_id": experiment_id,
                "example_id": result.get("example_id"),
                "pattern": experiment.get("pattern") or result.get("pattern"),
                "run_success": run.get("success", result.get("success")),
                "run_outcome": run.get("outcome", result.get("outcome")),
                "termination_reason": run.get(
                    "termination_reason",
                    result.get("termination_reason"),
                ),
                "system_failure": run.get("system_failure", result.get("system_failure")),
                "task_verification_status": task_verification.get(
                    "status",
                    result.get("task_verification_status"),
                ),
                "task_verification_score": task_verification.get(
                    "score",
                    result.get("task_verification_score"),
                ),
                "duration_seconds": run.get("duration_seconds", result.get("duration_seconds")),
                "parallelism_efficiency": orchestration.get("parallelism_efficiency", {}).get("value"),
                "coordination_to_output_ratio": orchestration.get("coordination_overhead", {}).get(
                    "coordination_to_output_ratio"
                ),
                "input_tokens": usage["input_tokens"],
                "output_tokens": usage["output_tokens"],
                "matrix": matrix,
                **flattened_matrix,
            }
            for dim in ACTIVE_DIMENSIONS:
                payload = judge_scores.get(dim, {})
                if (
                    not isinstance(payload, dict)
                    or not isinstance(payload.get("category"), str)
                    or not payload.get("category")
                ):
                    payload = summary_judge_scores.get(dim, {})
                if isinstance(payload, dict):
                    row[dim] = payload.get("category")
                else:
                    row[dim] = None
            rows.append(row)

    def _avg(field: str, group_rows: list[dict[str, Any]]) -> float | None:
        values = [float(row[field]) for row in group_rows if isinstance(row.get(field), (int, float))]
        if not values:
            return None
        return mean(values)

    grouped: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    has_harness = any(row.get("harness") for row in rows)
    for row in rows:
        key = (
            row.get("harness") if has_harness else None,
            row.get("architecture_family"),
            row.get("swarm_size"),
            row.get("task_pack"),
            row.get("task_structure"),
        )
        grouped[key].append(row)

    condition_summaries: list[dict[str, Any]] = []
    for key, group_rows in sorted(grouped.items(), key=lambda item: tuple(str(v) for v in item[0])):
        harness, family, size, task_pack, task_structure = key
        run_count = len(group_rows)
        completed = sum(1 for row in group_rows if row.get("run_outcome") == "completed")
        turn_limit = sum(1 for row in group_rows if row.get("termination_reason") == "turn_limit")
        modal_dimensions = {
            dim: _mode([str(row.get(dim) or "") for row in group_rows])
            for dim in ACTIVE_DIMENSIONS
        }
        failure_modes = Counter(
            str(row.get("termination_reason") or "unknown")
            for row in group_rows
            if row.get("run_outcome") != "completed"
        )
        summary_entry: dict[str, Any] = {}
        if harness:
            summary_entry["harness"] = harness
        summary_entry.update({
                "architecture_family": family,
                "swarm_size": size,
                "task_pack": task_pack,
                "task_structure": task_structure,
                "runs": run_count,
                "clean_completion_rate": completed / run_count if run_count else None,
                "turn_limit_incomplete_rate": turn_limit / run_count if run_count else None,
                "avg_task_score": _avg("task_verification_score", group_rows),
                "avg_duration_seconds": _avg("duration_seconds", group_rows),
                "avg_parallelism_efficiency": _avg("parallelism_efficiency", group_rows),
                "avg_coordination_to_output_ratio": _avg("coordination_to_output_ratio", group_rows),
                "avg_input_tokens": _avg("input_tokens", group_rows),
                "avg_output_tokens": _avg("output_tokens", group_rows),
                "modal_dimensions": modal_dimensions,
                "top_failure_modes": dict(failure_modes.most_common(3)),
            }
        )
        condition_summaries.append(summary_entry)

    benchmark_flat_differences: list[dict[str, Any]] = []
    per_example: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        example_id = row.get("example_id")
        score = row.get("task_verification_score")
        if not isinstance(example_id, str) or not isinstance(score, (int, float)):
            continue
        per_example[(example_id, f"{float(score):.3f}")].append(row)

    for (example_id, score), group_rows in sorted(per_example.items()):
        if len(group_rows) < 2:
            continue
        signatures = {
            (
                row.get("run_outcome"),
                row.get("termination_reason"),
                tuple(row.get(dim) for dim in ACTIVE_DIMENSIONS),
            )
            for row in group_rows
        }
        if len(signatures) <= 1:
            continue
        benchmark_flat_differences.append(
            {
                "example_id": example_id,
                "task_verification_score": float(score),
                "rows": [
                    {
                        "experiment_id": row.get("experiment_id"),
                        "pattern": row.get("pattern"),
                        "architecture_family": row.get("architecture_family"),
                        "swarm_size": row.get("swarm_size"),
                        "run_outcome": row.get("run_outcome"),
                        "termination_reason": row.get("termination_reason"),
                        "behavior": {
                            dim: row.get(dim)
                            for dim in ACTIVE_DIMENSIONS
                        },
                    }
                    for row in group_rows
                ],
            }
        )

    failure_mode_rows: list[dict[str, Any]] = []
    by_family_size: dict[tuple[Any, Any], Counter[str]] = defaultdict(Counter)
    for row in rows:
        if row.get("run_outcome") == "completed":
            continue
        key = (row.get("architecture_family"), row.get("swarm_size"))
        by_family_size[key][str(row.get("termination_reason") or "unknown")] += 1
    for (family, size), counter in sorted(by_family_size.items(), key=lambda item: tuple(str(v) for v in item[0])):
        for label, count in counter.most_common():
            failure_mode_rows.append(
                {
                    "architecture_family": family,
                    "swarm_size": size,
                    "failure_mode": label,
                    "count": count,
                }
            )

    summary: dict[str, Any] = {
        "matrix_id": matrix_id,
        "generated_at": datetime.now().isoformat(),
        "summary_paths": [str(path) for path in summary_paths],
        "experiments_dir": str(resolved_experiments_dir),
        "row_count": len(rows),
        "condition_summaries": condition_summaries,
        "benchmark_flat_behavior_differences": benchmark_flat_differences,
        "failure_modes": failure_mode_rows,
        "rows": rows,
    }

    report_lines = [
        "# Matrix Report",
        "",
        f"- Matrix ID: `{matrix_id or 'unknown'}`",
        f"- Summary files: {len(summary_paths)}",
        f"- Rows analyzed: {len(rows)}",
        "",
        "## Condition Summaries",
        "",
        (
            "| harness | family | size | task_pack | task_structure | runs | avg_score | clean_completion | turn_limit_rate | avg_parallel | avg_coord_ratio | avg_duration_s | EC | GD | FS | CD | RW |"
            if has_harness
            else "| family | size | task_pack | task_structure | runs | avg_score | clean_completion | turn_limit_rate | avg_parallel | avg_coord_ratio | avg_duration_s | EC | GD | FS | CD | RW |"
        ),
        (
            "|---|---|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---|---|---|---|---|"
            if has_harness
            else "|---|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---|---|---|---|---|"
        ),
    ]

    for item in condition_summaries:
        harness_col = f"{item.get('harness') or 'n/a'} | " if has_harness else ""
        report_lines.append(
            "| "
            + harness_col
            + f"{item.get('architecture_family') or 'n/a'} | "
            + f"{item.get('swarm_size') or 'n/a'} | "
            + f"{item.get('task_pack') or 'n/a'} | "
            + f"{item.get('task_structure') or 'n/a'} | "
            + f"{item.get('runs') or 0} | "
            + (
                f"{item['avg_task_score']:.3f}"
                if isinstance(item.get("avg_task_score"), (int, float))
                else "n/a"
            )
            + " | "
            + (
                f"{item['clean_completion_rate']:.3f}"
                if isinstance(item.get("clean_completion_rate"), (int, float))
                else "n/a"
            )
            + " | "
            + (
                f"{item['turn_limit_incomplete_rate']:.3f}"
                if isinstance(item.get("turn_limit_incomplete_rate"), (int, float))
                else "n/a"
            )
            + " | "
            + (
                f"{item['avg_parallelism_efficiency']:.3f}"
                if isinstance(item.get("avg_parallelism_efficiency"), (int, float))
                else "n/a"
            )
            + " | "
            + (
                f"{item['avg_coordination_to_output_ratio']:.3f}"
                if isinstance(item.get("avg_coordination_to_output_ratio"), (int, float))
                else "n/a"
            )
            + " | "
            + (
                f"{item['avg_duration_seconds']:.1f}"
                if isinstance(item.get("avg_duration_seconds"), (int, float))
                else "n/a"
            )
            + " | "
            + " | ".join(
                item.get("modal_dimensions", {}).get(dim) or "n/a"
                for dim in ACTIVE_DIMENSIONS
            )
            + " |"
        )

    if benchmark_flat_differences:
        report_lines.extend(["", "## Benchmark-Flat Behavioral Differences", ""])
        for item in benchmark_flat_differences:
            report_lines.append(
                f"- `{item['example_id']}` at score `{item['task_verification_score']:.3f}`:"
            )
            for row in item["rows"]:
                profile = ", ".join(
                    f"{dim}={row['behavior'].get(dim) or 'n/a'}"
                    for dim in ACTIVE_DIMENSIONS
                )
                report_lines.append(
                    "  - "
                    + f"`{row.get('architecture_family')}` size `{row.get('swarm_size')}` "
                    + f"({row.get('pattern')}) -> `{row.get('run_outcome')}` "
                    + f"/ `{row.get('termination_reason')}`; {profile}"
                )

    if failure_mode_rows:
        report_lines.extend(
            [
                "",
                "## Top Failure Modes By Family/Size",
                "",
                "| family | size | failure_mode | count |",
                "|---|---:|---|---:|",
            ]
        )
        for row in failure_mode_rows:
            report_lines.append(
                "| "
                + f"{row['architecture_family']} | {row['swarm_size']} | "
                + f"{row['failure_mode']} | {row['count']} |"
            )

    report_text = "\n".join(report_lines)
    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)
        summary_path = output_dir / "matrix-summary.json"
        report_path = output_dir / "matrix-report.md"
        with open(summary_path, "w") as f:
            json.dump(summary, f, indent=2)
        with open(report_path, "w") as f:
            f.write(report_text)
        summary["summary_path"] = str(summary_path)
        summary["report_path"] = str(report_path)

    return summary
