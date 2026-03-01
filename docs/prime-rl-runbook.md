# Prime RL Runbook (Helm)

This runbook describes the minimum end-to-end loop from Helm benchmark runs to
Prime RL training inputs.

For terminal-only continuity details (run IDs, pitfalls, next tasks), see:
- `docs/AGENT_HANDOFF.md`

## 1) Prerequisites

### Prime CLI health

```bash
./scripts/prime_terminal_preflight.sh
prime --version
prime config view
```

You are ready to launch hosted runs when:

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
prime env info local0ptimist/helm-orchestration-policy@latest
```

`prime login` is optional when API key is already available. Terminal-only
setup works without browser access via `prime config set-api-key`.
Auth state is local (`~/.prime/config.json`), not repository state.

### Helm health

```bash
uv run --with pytest pytest -q
uv run helm benchmark adapters
```

## 2) Run a sampled benchmark batch

Use benchmark mode for eval-style sampling:

```bash
uv run helm benchmark run patterns/benchmark-swebench-template.yaml -n 5 --on-turn-limit end
```

When using verifier `mode: completion`, ensure the agent prompt writes
`coordination/signals/done` when work is complete.

Outputs:

- `experiments/<experiment-id>/...` for each example
- `experiments/benchmark-runs/<pattern>-<timestamp>.json` summary
- `evaluation/task_verification.json` per run
- `run_data.json` per run (with provenance + orchestration metrics)

## 3) Generate baseline tables

```bash
uv run helm benchmark report experiments/benchmark-runs/<summary>.json
uv run helm benchmark report experiments/benchmark-runs/<summary>.json --format csv --output experiments/reports/baseline.csv
```

Use this table as your pre-train baseline snapshot.

## 4) Export training JSONL

```bash
uv run helm benchmark export experiments/benchmark-runs/<summary>.json --output experiments/exports/train.jsonl
```

Record schema includes:

- `messages` (user task + final assistant output)
- `reward`
- `reward_components`
- `task_verification`
- benchmark provenance and orchestration metrics

To train the Helm-native orchestration policy environment, convert export rows:

```bash
uv run helm benchmark export-orchestration experiments/exports/train.jsonl --output experiments/exports/train.orchestration.jsonl
```

## 5) Configure Prime RL

Generate a template:

```bash
prime rl init configs/prime/rl.toml
```

Then set:

- `model` (start with a small model for first run)
- one or more `[[env]]` entries for your training environment(s)
- training knobs (`batch_size`, `rollouts_per_example`, etc.)

Useful commands:

```bash
prime rl models
prime rl run configs/prime/rl.toml
prime rl logs <run-id> -f
prime rl metrics <run-id>
```

Helm-native environment path:

```bash
prime env install ./environments/helm_orchestration_policy
prime eval run helm_orchestration_policy -m openai/gpt-4.1-mini -n 5
prime rl run configs/prime/rl.helm-orchestration-smoke.toml
```

Current published Hub slug:

- `local0ptimist/helm-orchestration-policy`

Hosted run example:

- `vqkgzi286branqmhkq1myu0g` (completed)

## 6) Readiness gates before first hosted run

Run automated checks:

```bash
uv run helm readiness --summary experiments/benchmark-runs/<summary>.json
```

1. Benchmark batch runs complete without manual intervention.
2. `task_verification` appears for each sampled run.
3. Baseline report generated and archived.
4. Training export JSONL generated and spot-checked.
5. Prime CLI authenticated (`API Key` + `User ID` set).

## 7) Current limitations

1. SWE-bench/tau-bench benchmark-native scorer scripts are not bundled yet.
2. Default verifier mode is `completion`; for benchmark-native correctness,
   configure `benchmark.verifier.mode: command` with your scorer.
   Supported command placeholders:
   `{experiment_dir}`, `{dataset_path}`, `{benchmark_id}`, `{adapter}`,
   `{example_id}`, `{split}`.
   A starter script is provided at `scripts/verify_dataset_contract.py`.
3. Prime config tuning is still manual; no one-click Helm->Prime launcher yet.
4. SWE-style runs can fail with `Step 0 failed after ... empty batches` when the
   base model/env pair produces no trajectory steps. If this occurs, switch to a
   more agent-capable base model and reduce rollout pressure for smoke runs.
5. As of 2026-02-22, hosted SWE probes showed additional environment-specific
   blockers:
   - `primeintellect/deepswe`: import failure
     (`cannot import name 'ChatCompletionMessageToolCall' from verifiers.types`).
   - `primeintellect/swe-grep-env`: requires `OPENAI_API_KEY` because it builds
     a `JudgeRubric` with OpenAI client defaults.
   - `primeintellect/mini-swe-agent-bench`: missing packaged
     `swebench.yaml` in hosted runtime wheel.
6. Practical path while blocked on SWE env compatibility fixes:
   - use Helm benchmark/export loops for data generation and analysis;
   - run Prime RL smoke on known-compatible non-SWE envs to validate training
     plumbing;
   - prioritize a Helm-aligned custom verifiers environment for orchestration
     reward training.
   - reference control run: `zwxoegns3rrdnfmslfj8ujgt` (`reverse-text`,
     completed with non-empty trajectory samples).
7. Helm-native env hosted training now works with the Hub slug, but reward is
   currently flat (0.0) because model outputs do not match the required policy
   XML tags.
8. Do not use local env ID for hosted RL:
   local IDs work for local eval, but hosted workers fail to import them
   (example failure run: `ee852kb6mbo9c43g659fk1vn`).
9. `prime eval run` can fail with `402 insufficient_funds` from the inference
   provider even when env code is correct; this is billing/quota, not
   environment import failure.
