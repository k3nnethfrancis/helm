# Helm Scripts

## Experiment Pipeline

```
generate_experiment_matrix.py → run_experiment_matrix.py → analyze_experiment_matrix.py
```

- `generate_experiment_matrix.py` — Generate experiment patterns from a matrix manifest YAML
- `run_experiment_matrix.py` — Run a generated matrix wave end-to-end (benchmark + judge + analyze)
- `analyze_experiment_matrix.py` — Analyze results from completed matrix runs

## Judge Validation

- `run_judge_backend_comparison.py` — Cross-judge counterparty comparison on saved experiments

## Benchmark

- `download_swebench.py` — Download SWE-bench Verified dataset from HuggingFace
- `verify_swebench.py` — SWE-bench ground truth verifier (clone, patch, run tests)
