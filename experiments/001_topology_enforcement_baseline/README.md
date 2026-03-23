# 001: Topology Enforcement Baseline

## Question

How do different orchestration topologies compare on SWE-bench when topology is mechanically enforced?

Prior experiments (pre-enforcement) showed all multi-agent runs violated prescribed topologies — agents spawned 38 subagents and used native messaging to bypass the filesystem protocol. This experiment re-runs the comparison with `--disallowedTools` enforcement and the `helm-agent` CLI as the controlled coordination mechanism.

## Design

**Benchmark:** SWE-bench Verified (8 tasks)

| Task | Structure | Repo |
|---|---|---|
| sympy__sympy-17630 | decomposable | sympy |
| sympy__sympy-21930 | decomposable | sympy |
| django__django-13195 | decomposable | django |
| pytest-dev__pytest-5809 | decomposable | pytest |
| django__django-12754 | sequential | django |
| matplotlib__matplotlib-23412 | sequential | matplotlib |
| sphinx-doc__sphinx-8638 | sequential | sphinx |
| pytest-dev__pytest-7205 | sequential | pytest |

**Topologies:** single@1, centralized@5, hybrid@5, delegating@1

**Harness:** Claude Code / Opus 4.6

**Judge:** Claude Sonnet 4.6 (hierarchical strategy)

**Dimensions:** escalation-calibration, goal-drift, human-model-accuracy, context-degradation, resource-waste, topology-adherence

**Enforcement:** `--disallowedTools Agent,TeamCreate,SendMessage` on all agents (except delegating hub which allows Agent)

**Compliance verification:** `topology_compliance.py` run post-experiment to confirm enforcement held

## Configs

Experiment configs in `configs/`. Base configs are `single-agent.yaml`, `centralized-5.yaml`, `delegating-1.yaml` from the repo root configs.

## Status

- [ ] Generate configs (single, centralized, hybrid, delegating × 8 tasks)
- [ ] Run single@1 baseline (8 tasks)
- [ ] Run centralized@5 (8 tasks)
- [ ] Run hybrid@5 (8 tasks)
- [ ] Run delegating@1 (8 tasks)
- [ ] Compliance verification on all runs
- [ ] Judge all runs (6 dimensions)
- [ ] Compile results
- [ ] Figures for blog post

## Expected Output

- `results/summary.json` — task scores, closure rates, compliance scores per topology
- `results/behavioral_profiles.json` — judge dimension scores per condition
- `results/compliance.json` — topology enforcement verification
- `figures/` — comparison charts for blog post
