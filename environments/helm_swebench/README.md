# helm-swebench

SWE-bench ground truth verification environment for Prime RL training.

### Overview
- **Environment ID (local install)**: `helm_swebench`
- **Environment ID (after Hub publish)**: `local0ptimist/helm-swebench`
- **Short description**: Single-turn code patch generation scored by real test execution.
- **Tags**: helm, swebench, code-generation, train, eval

### How It Works

The model receives a problem statement from an open-source repo (bug report or feature request) and must produce a unified diff patch. Reward is computed by:

1. **Format compliance** (10%) — Does the output look like a valid unified diff?
2. **Verifier result** (85%) — Subprocess calls `scripts/verify_swebench.py` which clones the repo at the base commit, applies the patch, installs, runs the test suite, and returns a 0.0-1.0 score based on FAIL_TO_PASS / PASS_TO_PASS results.
3. **Patch parsimony** (5%) — Mild preference for shorter, targeted patches.

### Prerequisites

- `uv` (for venv creation and package installation inside the verifier)
- `git` (for repo cloning and patch application)
- Python versions are auto-managed by `uv venv --python X.Y` per the SWE-bench spec

### Latency

Each rollout runs real test execution: **30-300 seconds** depending on the repo (sympy/pytest are fast, django/matplotlib are slower). Plan batch sizes accordingly.

### Quickstart

Install:

```bash
prime env install ./environments/helm_swebench
```

Run a smoke eval:

```bash
prime eval run helm_swebench -m openai/gpt-4.1-mini -n 1 --rollouts-per-example 1
```

Use the full dataset:

```bash
prime eval run helm_swebench \
  -m openai/gpt-4.1-mini \
  -n 10 \
  -a '{"dataset_path":"data/swe_bench_verified.jsonl","max_examples":10}'
```

### Environment Arguments

| Arg | Type | Default | Description |
| --- | ---- | ------- | ----------- |
| `dataset_path` | str | `"data/swe_bench_verified.jsonl"` | Local JSONL path, directory, or HF dataset id |
| `dataset_split` | str | `"train"` | Split name when loading HF dataset |
| `max_examples` | int | `-1` | Cap loaded examples (`-1` means all) |
| `system_prompt` | str | built-in | Override system prompt |
| `timeout` | int | `300` | Seconds per verifier subprocess call |
| `repo_cache` | str | `"~/.cache/helm/swebench-repos"` | Directory for caching cloned repos |

### Metrics

| Metric | Meaning |
| ------ | ------- |
| `reward` | Weighted composite (format + verifier + parsimony) |
| `patch_format_reward` | Fraction of unified diff markers present |
| `verifier_reward` | Score from real test execution (0.0-1.0) |
| `patch_size_reward` | Parsimony bonus (shorter patches score higher) |
