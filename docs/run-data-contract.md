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

Notes:

- Risky actions are inferred from `limits.blocked_commands` plus common network command heuristics.
- Some metrics can be `null` when denominator events are absent (for example no escalations or no risky requests).
