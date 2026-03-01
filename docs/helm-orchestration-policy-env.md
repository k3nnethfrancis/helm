# Helm Orchestration Policy Environment

This guide covers the Helm-native environment path for Prime eval/RL on
orchestration behavior.

## What This Is

`helm_orchestration_policy` is a single-turn verifiers environment that trains a
model to emit explicit orchestration policy decisions as XML tags.

Reward is deterministic and tied to Helm-derived policy labels:

1. Required tag coverage (`format_reward_func`)
2. Exact tag match vs target policy (`policy_match_reward_func`)
3. Escalation-route/gating consistency (`gate_consistency_reward_func`)

## 0) Confirm terminal-only Prime auth

```bash
./scripts/prime_terminal_preflight.sh
```

If this fails and browser access is unavailable, use:

```bash
prime config set-api-key <YOUR_PRIME_API_KEY>
prime config set-team-id cmlj2267a00ie5q1j6claku9l
```

## 1) Export Helm benchmark runs

```bash
uv run helm benchmark export experiments/benchmark-runs/<summary>.json \
  --output experiments/exports/<name>.train.jsonl
```

## 2) Convert to orchestration-policy dataset

```bash
uv run helm benchmark export-orchestration \
  experiments/exports/<name>.train.jsonl \
  --output experiments/exports/<name>.train.orchestration.jsonl
```

## 3) Install environment locally

```bash
prime env install ./environments/helm_orchestration_policy
```

## 4) Run a smoke eval

```bash
prime eval run helm_orchestration_policy -m openai/gpt-4.1-mini -n 5
```

Use your exported dataset:

```bash
prime eval run helm_orchestration_policy \
  -m openai/gpt-4.1-mini \
  -n 20 \
  -a '{"dataset_path":"experiments/exports/<name>.train.orchestration.jsonl","max_examples":20}'
```

## 5) Run a smoke RL training loop

```bash
prime rl run configs/prime/rl.helm-orchestration-smoke.toml
prime rl logs <run-id> -f
```

Current published slug:

- `local0ptimist/helm-orchestration-policy`

First hosted smoke run:

- `vqkgzi286branqmhkq1myu0g` (completed, reward currently flat at `0.0`)

## Notes

- This environment intentionally avoids external LLM-judge dependencies.
- Local install ID uses underscore (`helm_orchestration_policy`). After pushing
  to Hub, use your slug form (`<owner>/helm-orchestration-policy`).
- It accepts two input row formats:
  - Helm policy-export rows (`question`, `answer`)
  - Raw Helm benchmark-export rows (`messages`, trace/orchestration/task_verification fields)
- For hosted training at scale, push this environment to the Prime Hub and use
  the Hub slug in `[[env]].id`.

## Do Not Repeat

1. Do not launch hosted RL with local env ID (`helm_orchestration_policy`).
   It fails in remote workers with module import errors.
2. Do not use `gpt-4.1-mini` short model name in `prime eval run`.
   Use full provider-prefixed model IDs like `openai/gpt-4.1-mini`.
3. Current flat reward is due to output schema mismatch.
   Model outputs generic orchestration XML, but rubric expects specific policy
   tags (`escalation_route`, `dominant_intervention`, etc.).
