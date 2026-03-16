# Helm Scripts

Scripts exist to support the active experiment loop. If a script is not part of that loop, it should be deleted or moved out of the repo.

Active script groups:

- Matrix
  - `generate_experiment_matrix.py`
  - `run_experiment_matrix.py`
  - `analyze_experiment_matrix.py`
- Judge / reward validation
  - `audit_judge_inputs.py`
  - `run_judge_repeatability.py`
  - `run_judge_strategy_comparison.py`
  - `run_offline_reward_sweep.py`
- Benchmark substrate
  - `download_swebench.py`
  - `verify_swebench.py`
  - `verify_dataset_contract.py`

Delete one-off spikes after they stop informing the active research program.
