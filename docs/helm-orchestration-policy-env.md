# Helm Orchestration Policy Environment

**Status**: Stepping stone. This environment validates Prime RL pipeline plumbing. It is not the main training path.

## What This Is

`helm_orchestration_policy` is a single-turn verifiers environment that trains a model to emit orchestration policy decisions as XML tags. It proves we can define custom reward functions, publish to Prime Hub, and run hosted RL training.

**What it is NOT**: This does not train agents to coordinate better in multi-agent systems. It trains a model to label orchestration decisions. It is one downstream optimization experiment, not the main research loop.

## How It Works

Reward is deterministic and tied to Helm-derived policy labels:

1. `format_reward_func` — Required tag coverage (are all 7 tags present?)
2. `policy_match_reward_func` — Exact tag match vs target policy
3. `gate_consistency_reward_func` — Escalation-route/gating consistency

## Quick Start

### Terminal auth

```bash
./scripts/prime_terminal_preflight.sh
```

If needed:
```bash
prime config set-api-key <YOUR_PRIME_API_KEY>
prime config set-team-id cmlj2267a00ie5q1j6claku9l
```

### Generate training data from Helm experiments

```bash
uv run helm benchmark export experiments/benchmark-runs/<summary>.json \
  --output experiments/exports/<name>.train.jsonl

uv run helm benchmark export-orchestration \
  experiments/exports/<name>.train.jsonl \
  --output experiments/exports/<name>.train.orchestration.jsonl
```

### Install and eval locally

```bash
prime env install ./environments/helm_orchestration_policy
prime eval run helm_orchestration_policy -m openai/gpt-4.1-mini -n 5
```

With custom dataset:
```bash
prime eval run helm_orchestration_policy \
  -m openai/gpt-4.1-mini -n 20 \
  -a '{"dataset_path":"experiments/exports/<name>.train.orchestration.jsonl","max_examples":20}'
```

### Hosted RL smoke

```bash
prime rl run configs/prime/rl.helm-orchestration-smoke.toml
prime rl logs <run-id> -f
```

## Current Status

- Published: `local0ptimist/helm-orchestration-policy`
- Version: 0.3.0 (few-shot examples added to fix flat reward)
- First hosted run: `vqkgzi286branqmhkq1myu0g` (completed, reward flat at 0.0)
- Root cause: model outputs generic XML, not the required 7 policy tags
- Fix applied: added allowed values list + 3 few-shot examples to system prompt
- **Needs**: republish v0.3.0 and retest

## Do Not Repeat

1. Do not launch hosted RL with local env ID. Use Hub slug `local0ptimist/helm-orchestration-policy`.
2. Do not use short model names (`gpt-4.1-mini`). Use `openai/gpt-4.1-mini`.
3. Flat reward is output schema mismatch, not infrastructure failure.

## Input Formats

Accepts two row formats:
- Helm policy-export rows (`question`, `answer`)
- Raw Helm benchmark-export rows (`messages`, trace/orchestration/task_verification fields)

## Relationship to Helm Research Program

This env validates that:
- We can define custom reward functions for orchestration behavior
- Prime RL infrastructure works end-to-end with Helm-derived data
- Small models can learn to produce structured orchestration outputs

It does NOT:
- Train agents to coordinate in multi-agent systems
- Use multi-turn traces or tool use
- Produce models that behave differently when deployed as agents

Any serious optimization path for Helm will require evidence that the target signal is valid plus multi-turn training on richer traces than this environment uses today.
