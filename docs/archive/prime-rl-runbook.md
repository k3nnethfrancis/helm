# Prime RL Runbook (Helm)

This runbook covers the RL training pipeline from Helm experiments to Prime training runs.

**Important context**: Helm is evaluation-first. Optimization is downstream of evidence that a signal is worth optimizing. The current Prime RL environments are **single-turn stepping stones** that validate training pipeline plumbing, not the main research loop. See `plan.md` for the full research plan.

For terminal-only continuity details, see `docs/AGENT_HANDOFF.md`.

---

## 1) Prerequisites

### Prime CLI health

```bash
./scripts/prime_terminal_preflight.sh
prime --version
prime config view
```

Ready when:
- `API Key` is set
- `User ID` is set
- Team ID is `cmlj2267a00ie5q1j6claku9l` (`shoshin-labs` / `local0ptimist`)

If needed:
```bash
prime upgrade
prime config set-api-key <your_api_key>
prime config set-team-id cmlj2267a00ie5q1j6claku9l
prime whoami
COLUMNS=200 prime teams list
```

### Helm health

```bash
uv run --with pytest pytest -q
uv run helm benchmark adapters
```

---

## 2) Current Training Environments

### helm_orchestration_policy (Stepping Stone)

**What it does**: Single-turn env. Model receives an orchestration scenario, outputs 7 XML policy tags, gets scored on format compliance and policy match.

**What it's for**: Validates Prime RL pipeline. Proves we can define reward functions, publish to Hub, and run hosted training. Not the main training path.

**Current status**: Published as `local0ptimist/helm-orchestration-policy`. First hosted run completed (`vqkgzi286branqmhkq1myu0g`) but reward flat at 0.0 (format compliance issue). Prompt fixed with few-shot examples in v0.3.0, needs retest.

```bash
# Local install and eval
prime env install ./environments/helm_orchestration_policy
prime eval run helm_orchestration_policy -m openai/gpt-4.1-mini -n 5

# Hosted RL smoke
prime rl run configs/prime/rl.helm-orchestration-smoke.toml
prime rl logs <run-id> -f
prime rl rollouts <run-id> -s 0 -n 5
```

### helm_swebench (Stepping Stone)

**What it does**: Single-turn env. Model generates a code patch, verifier runs real tests against it, returns pass/fail score.

**What it's for**: Validates SWE-bench verifier integration with Prime. Proves we can score code patches in the RL loop. Not the main training path.

```bash
# Download dataset
python scripts/download_swebench.py

# Local install and eval
prime env install helm_swebench
prime eval run helm_swebench -m openai/gpt-4.1-mini -n 1 --rollouts-per-example 1

# Full dataset
prime eval run helm_swebench -m openai/gpt-4.1-mini -n 5 \
  -a '{"dataset_path":"data/swe_bench_verified.jsonl","max_examples":5}'
```

**Key config differences**:

| Knob | Orchestration-policy | SWE-bench | Why |
|------|---------------------|-----------|-----|
| `batch_size` | 32 | 4 | Each rollout runs real tests (30-300s) |
| `max_tokens` | 512 | 4096 | Patches can be long |
| `learning_rate` | 1e-6 | 5e-7 | Code generation is harder |

**Cache sizing**: Verifier caches git clones at `~/.cache/helm/swebench-repos/`. Each repo 100MB-2GB, expect ~10GB total.

**Hub deployment note**: Verifier script lives at `scripts/verify_swebench.py` (not in wheel). For Hub-hosted runs, set `HELM_VERIFY_SWEBENCH` env var to absolute path on worker.

---

## 3) A Richer Optimization Path (Not Yet Implemented)

Any serious optimization path requires multi-turn RL on full agent traces:

```
Run multi-agent experiment (Helm)
    → Collect per-agent traces (all tool calls, coordination, outcomes)
    → Score: judge dimensions + verifier task correctness
    → Composite reward per trace
    → Train model on traces from all roles
```

**What's missing for this**:
1. Multi-turn RL support in Prime (or alternative training infra)
2. Per-agent trace extraction in RL-compatible format
3. Reward attribution to individual agents in a multi-agent experiment
4. Trace/control fidelity fixes in the current harness layer

The single-turn environments above are stepping stones that validate pieces of this pipeline.

---

## 4) Helm Benchmark → Training Data Pipeline

### Run a sampled benchmark batch

```bash
uv run helm benchmark run patterns/benchmark-swebench-single-claude.yaml -n 10 --seed 42 --on-turn-limit end
```

Outputs:
- `experiments/<experiment-id>/` per example
- `experiments/benchmark-runs/<pattern>-<timestamp>.json` summary
- `evaluation/task_verification.json` per run
- `run_data.json` per run (provenance + orchestration metrics)

### Generate baseline tables

```bash
uv run helm benchmark report experiments/benchmark-runs/<summary>.json
uv run helm benchmark report experiments/benchmark-runs/<summary>.json --format csv --output experiments/reports/baseline.csv
```

### Export rollout JSONL

```bash
uv run helm benchmark export experiments/benchmark-runs/<summary>.json --output experiments/exports/train.jsonl
```

Record schema: `messages`, `reward`, `reward_components`, `task_verification`, benchmark provenance, orchestration metrics.

### Convert to orchestration-policy format

```bash
uv run helm benchmark export-orchestration experiments/exports/train.jsonl --output experiments/exports/train.orchestration.jsonl
```

---

## 5) Baseline Sweep Workflow

Before optimization, establish baselines across models and topologies.

### Pattern configs

| Config | Agents | Harness | Topology |
|--------|--------|---------|----------|
| `benchmark-swebench-single-claude.yaml` | 1 | claude-code | single |
| `benchmark-swebench-single-gpt5.yaml` | 1 | codex | single |
| `benchmark-swebench-hubspoke-claude.yaml` | 3 | claude-code | hub-spoke |
| `benchmark-swebench-hubspoke-gpt5.yaml` | 3 | codex | hub-spoke |
| `benchmark-swebench-peer-claude.yaml` | 3 | claude-code | peer |
| `benchmark-swebench-peer-gpt5.yaml` | 3 | codex | peer |

All use `seed: 42`, `max_examples: 10`, same verifier command.

### Step 1: Single-agent calibration

```bash
python scripts/download_swebench.py

uv run helm benchmark run patterns/benchmark-swebench-single-claude.yaml \
  -n 10 --seed 42 --on-turn-limit end

uv run helm benchmark run patterns/benchmark-swebench-single-gpt5.yaml \
  -n 10 --seed 42 --on-turn-limit end
```

Compare pass rates against public SWE-bench leaderboard. Gate: <15% delta.

### Step 2: Multi-agent sweep

2 models x 2 topologies x 10 examples x 3 replications (seeds: 42, 43, 44):

```bash
uv run helm benchmark run patterns/benchmark-swebench-hubspoke-claude.yaml \
  -n 10 --seed 42 --on-turn-limit end
# Repeat with --seed 43, --seed 44, then for all 4 configs
```

Judge and report:
```bash
uv run helm judge <experiment-id> -d escalation-calibration,goal-drift,context-degradation,failure-suppression,resource-waste
uv run helm benchmark report experiments/benchmark-runs/<summary>.json
```

### Step 3: Export rollout / training data

```bash
uv run helm benchmark export experiments/benchmark-runs/<summary>.json \
  --output experiments/exports/baseline-sweep.train.jsonl
```

---

## 6) Readiness Gates

```bash
uv run helm readiness --summary experiments/benchmark-runs/<summary>.json
```

1. Benchmark batch runs complete without manual intervention
2. `task_verification` appears for each sampled run
3. Baseline report generated and archived
4. Training export JSONL generated and spot-checked
5. Prime CLI authenticated

---

## 7) Known Limitations

1. **Single-turn gap**: Current RL environments are single-turn. Full multi-turn agent RL is the goal but not yet implemented.
2. **SWE-bench verifier not in wheel**: For Hub-hosted runs, set `HELM_VERIFY_SWEBENCH` env var.
3. **tau-bench scorer not bundled**: SWE-bench only for now.
4. **No one-click Helm→Prime launcher**: Config tuning is manual.
5. **Empty batch risk**: SWE-style runs can fail with empty batches if model/env pair produces no trajectory steps. Use agent-capable models.
6. Do not use local env ID for hosted RL (fails in remote workers).
7. `402 insufficient_funds` from `prime eval run` is billing/quota, not env-code failure.

---

## 8) Run History

Hub slug: `local0ptimist/helm-orchestration-policy`

| Run ID | Env | Result |
|--------|-----|--------|
| `zwxoegns3rrdnfmslfj8ujgt` | primeintellect/reverse-text | Completed (control) |
| `ee852kb6mbo9c43g659fk1vn` | helm_orchestration_policy (local) | Failed (expected: remote can't import local) |
| `vqkgzi286branqmhkq1myu0g` | local0ptimist/helm-orchestration-policy | Completed (reward flat 0.0) |
