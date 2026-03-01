# Agent Handoff (Terminal-First)

Last updated: 2026-02-22

This file is the continuation guide for a new terminal-only agent (tmux/Codex).

## 0) Terminal-Only Auth Bootstrap (No Browser)

Run this first:

```bash
cd /Users/kenneth/Desktop/lab/projects/helm
./scripts/prime_terminal_preflight.sh
```

If preflight fails, recover fully from terminal:

```bash
prime config set-api-key <YOUR_PRIME_API_KEY>
prime config set-team-id cmlj2267a00ie5q1j6claku9l
prime whoami
COLUMNS=200 prime teams list
prime env info local0ptimist/helm-orchestration-policy@latest
```

No browser login is required when you already have an API key.
Prime auth state is local machine state (`~/.prime/config.json`) and is not
stored in this repo.

## 1) What Is Already Done

1. Prime team metadata fixed and publish path unblocked.
2. Helm-native environment published:
   - `local0ptimist/helm-orchestration-policy@0.1.0`
3. Hosted RL run with Helm-native env completed:
   - `vqkgzi286branqmhkq1myu0g`
4. New Helm export path added:
   - `helm benchmark export-orchestration`
5. New verifiers environment added:
   - `/Users/kenneth/Desktop/lab/projects/helm/environments/helm_orchestration_policy`

## 2) Current Blocking Problem

Hosted training executes end-to-end, but reward is flat (`0.0`).

Root cause:
- Model outputs generic XML like `<orchestration><action>...`
- Rubric expects specific policy tags:
  - `escalation_route`
  - `dominant_intervention`
  - `intervention_intensity`
  - `parallelism_target`
  - `coordination_style`
  - `verification_gate`
  - `human_gate_required`

Evidence:
- `prime rl rollouts vqkgzi286branqmhkq1myu0g -s 0 -n 2`
- `metrics.format_reward_func = 0.0`, `policy_match_reward_func = 0.0`

## 3) What Not To Repeat

1. Do not run hosted RL with local env id `helm_orchestration_policy`.
   - Remote workers cannot import local-only env modules.
   - Failure example: `ee852kb6mbo9c43g659fk1vn`
2. Do not use short eval model names like `gpt-4.1-mini`.
   - Use provider-prefixed ids, for example `openai/gpt-4.1-mini`.
3. Do not diagnose this as Prime auth/CLI failure.
   - Hosted RL plumbing is working.
   - This is now a prompt/output-contract issue.
4. Do not treat `prime eval run` `402 insufficient_funds` as env-code failure.
   - That error is inference billing/quota.

## 4) Files You Must Read First

1. `/Users/kenneth/Desktop/lab/projects/helm/docs/prime-rl-runbook.md`
2. `/Users/kenneth/Desktop/lab/projects/helm/docs/helm-orchestration-policy-env.md`
3. `/Users/kenneth/Desktop/lab/projects/helm/scripts/prime_terminal_preflight.sh`
4. `/Users/kenneth/Desktop/lab/projects/helm/src/helm/benchmarks/orchestration_dataset.py`
5. `/Users/kenneth/Desktop/lab/projects/helm/src/helm/cli.py`
6. `/Users/kenneth/Desktop/lab/projects/helm/environments/helm_orchestration_policy/helm_orchestration_policy.py`
7. `/Users/kenneth/Desktop/lab/projects/helm/configs/prime/rl.helm-orchestration-smoke.toml`
8. `/Users/kenneth/Desktop/lab/projects/helm/plan.md`

## 5) Run History (Useful IDs)

SWE compatibility probes:
- `hkqbn5ury6zy19vifpx532dx` (mini-swe-agent-plus, empty batches)
- `yke8geqnbpihb82mm17rpux3` (mini-swe-agent-plus, empty batches)
- `ie7cfe8numa6mkjv8ci7pbez` (mini-swe-agent-plus, empty batches)
- `u4bclx8mhbvsi7iym6z561ys` (deepswe import mismatch)
- `osjuyzm8mt3ii6blvihoggtb` (swe-grep-env missing `OPENAI_API_KEY`)
- `rdbccmbvnno33wgi3bw37b8n` (mini-swe-agent-bench missing `swebench.yaml`)

Control run:
- `zwxoegns3rrdnfmslfj8ujgt` (`primeintellect/reverse-text`, completed)

Helm-native env runs:
- `ee852kb6mbo9c43g659fk1vn` (expected fail: local env id in hosted worker)
- `vqkgzi286branqmhkq1myu0g` (completed with Hub slug, reward flat)

## 6) Immediate Next Work

1. Tighten policy-output format adherence.
   - Update environment prompt to force exact required tags only.
   - Add 2-5 few-shot examples with exact tag schema.
2. Add stronger formatting reward pressure.
   - Keep match reward.
   - Increase penalty for missing/unknown tags.
3. Re-publish environment (version bump).
   - `prime env push --path /Users/kenneth/Desktop/lab/projects/helm/environments/helm_orchestration_policy --auto-bump --visibility PRIVATE`
4. Re-run hosted RL with same smoke config.
5. Verify reward lift with:
   - `prime rl rollouts <run-id> -s 0 -n 5`
   - `prime rl metrics <run-id>`

## 7) Terminal Command Checklist

```bash
cd /Users/kenneth/Desktop/lab/projects/helm

# Sanity
./scripts/prime_terminal_preflight.sh
prime whoami
prime teams list
uv run --with pytest pytest -q

# Convert benchmark export -> orchestration dataset
uv run helm benchmark export-orchestration \
  experiments/exports/benchmark-smoke.train.jsonl \
  --output experiments/exports/benchmark-smoke.train.orchestration.jsonl

# Local env install/eval
prime env install helm_orchestration_policy -p ./environments
prime eval run helm_orchestration_policy -m openai/gpt-4.1-mini -n 2 -r 1

# Publish env
prime env push --path environments/helm_orchestration_policy --auto-bump --visibility PRIVATE

# Hosted RL smoke
prime rl run configs/prime/rl.helm-orchestration-smoke.toml
prime rl logs <run-id> -f
prime rl rollouts <run-id> -s 0 -n 5
```

## 8) Account Context

- Team ID: `cmlj2267a00ie5q1j6claku9l`
- Team name: `shoshin-labs`
- Team slug: `local0ptimist`
- Published env slug: `local0ptimist/helm-orchestration-policy`

## 9) Definition Of Success For Next Agent

1. Hosted Helm-native RL run completes with non-zero average reward.
2. Rollout samples show required policy tags, not generic orchestration XML.
3. Docs updated with final prompt/rubric tuning and new run IDs.
