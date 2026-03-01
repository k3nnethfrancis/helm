# Run Data Contract (`run_data.json`)

Helm writes a versioned run artifact at:

```
experiments/<experiment-id>/run_data.json
```

Current schema version: `helm.run_data.v1`

## Purpose

`run_data.json` is the stable handoff format for:

- Batch experiment analysis
- Hill-climbing orchestration policies
- Building SFT / preference / RL datasets

## Top-level shape

```json
{
  "schema_version": "helm.run_data.v1",
  "generated_at": "ISO-8601 timestamp",
  "experiment": { "...": "..." },
  "provenance": { "...benchmark provenance..." },
  "config": { "...resolved config metadata..." },
  "run": { "...": "..." },
  "agents": [ "...agent metadata..." ],
  "limits": { "...": "..." },
  "transcript": { "...summary..." },
  "evals": {
    "orchestration": { "...deterministic metrics..." },
    "judge": { "...optional LLM judge scores..." }
  },
  "artifacts": { "...relative paths..." }
}
```

## Deterministic orchestration evals

These are computed automatically from transcript + metadata:

1. `parallelism_efficiency`
   - `value`: `1 - critical_path_ratio` (higher means more parallel execution)
   - `critical_path_ratio`: `wall_clock_seconds / assistant_active_seconds`
   - `avg_parallel_agents`: `assistant_active_seconds / wall_clock_seconds`

2. `coordination_overhead`
   - `coordination_messages`
   - `messages_per_assistant_step`
   - `messages_per_workspace_artifact`
   - `coordination_to_output_ratio`

3. `escalation_precision_recall`
   - `permission_requests`
   - `risky_permission_requests`
   - `escalations`
   - `escalations_on_risky_actions`
   - `precision`
   - `recall`

4. `intervention_profile`
   - `total_interventions`
   - `by_action` (approve/reject/escalate/log/nudge buckets)
   - `by_event_type`
   - `by_agent`

Notes:

- Risky actions are inferred from `limits.blocked_commands` plus common network command heuristics.
- Some metrics can be `null` when denominator events are absent (for example no escalations or no risky requests).
- `run.interventions` is copied directly from runtime-guard logs and is intended as
  a training-label trace for orchestration policy learning.
- `run.orchestration_policy_trace` provides a canonical event stream for
  orchestration learning with:
  - `events`: normalized intervention/escalation events
  - `summary.by_action`, `summary.by_action_family`, `summary.by_source`,
    `summary.by_agent`
- Optional task verifier outputs are normalized into `run.task_verification`
  and referenced from `artifacts.task_verification`.
- Benchmark provenance (`benchmark`, `example`, `seed`) is normalized into
  both `provenance.benchmark` and `experiment.benchmark` for training/export
  pipelines.
- Run-level benchmark selection metadata is available under `run.benchmark`
  for sampled benchmark batches.
- Benchmark verifier mode (for example `completion` or `command`) is stored
  in benchmark provenance where available.

## Benchmark metadata fields

When a run comes from `helm benchmark run`, the contract includes:

- `config.benchmark` — benchmark block resolved from pattern config.
- `experiment.benchmark` — normalized benchmark provenance for the run.
- `provenance.benchmark` — same normalized provenance for downstream exporters.
- `run.benchmark` — run-time benchmark selection details (including selected example).
- `run.task_verification` — normalized verification result generated during
  benchmark execution.
  - `completion` mode: verification mirrors run completion success/failure.
  - `command` mode: verification comes from external scorer command output/exit code.
