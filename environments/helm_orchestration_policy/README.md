# helm-orchestration-policy

Environment for training/evaluating orchestration policy outputs derived from
Helm benchmark runs.

### Overview
- **Environment ID (local install)**: `helm_orchestration_policy`
- **Environment ID (after Hub publish)**: `<owner>/helm-orchestration-policy`
- **Short description**: Single-turn orchestration policy prediction using deterministic XML-tag rewards.
- **Tags**: helm, orchestration, multi-agent, train, eval

### Datasets
- **Primary dataset(s)**: JSONL rows from Helm benchmark exports.
- **Source links**: local Helm artifacts (for example `experiments/exports/*.jsonl`).
- **Split sizes**: user-defined.

### Task
- **Type**: single-turn
- **Output format expectations**: XML tags only
- **Rubric overview**:
  - tag-format coverage (all required tags present)
  - exact policy-tag match against target labels
  - escalation-route/human-gate consistency check

### Quickstart

Install:

```bash
prime env install ./environments/helm_orchestration_policy
```

Run a smoke eval:

```bash
prime eval run helm_orchestration_policy -m openai/gpt-4.1-mini -n 5
```

Use a custom dataset:

```bash
prime eval run helm_orchestration_policy \
  -m openai/gpt-4.1-mini \
  -n 20 \
  -a '{"dataset_path":"experiments/exports/benchmark-smoke.train.orchestration.jsonl","max_examples":20}'
```

### Environment Arguments

| Arg | Type | Default | Description |
| --- | ---- | ------- | ----------- |
| `dataset_path` | str | `"data/sample.jsonl"` | Local JSONL path, local directory, or HF dataset id |
| `dataset_split` | str | `"train"` | Split name when loading HF dataset or split-file directory |
| `max_examples` | int | `-1` | Cap loaded examples (`-1` means all) |
| `system_prompt` | str | built-in | Override system prompt |

### Metrics

| Metric | Meaning |
| ------ | ------- |
| `reward` | Weighted composite (format + policy match + consistency) |
| `format_reward_func` | Fraction of required tags emitted |
| `policy_match_reward_func` | Fraction of target tags matched exactly |
| `gate_consistency_reward_func` | Whether gate requirement matches escalation route |
