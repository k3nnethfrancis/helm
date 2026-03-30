# Experiments

Each subdirectory is a self-contained experiment. The structure is standardized:

```
experiments/{name}/
├── README.md          # Purpose, hypothesis, design, conditions, findings
├── *.yaml             # Helm configs (one per condition)
├── runs/              # Auto-created by helm (gitignored)
└── results/           # Curated analysis, figures, summaries (tracked)
```

## Creating an Experiment

1. Create `experiments/{name}/`
2. Write `README.md` with at minimum: question, hypothesis, conditions
3. Write one YAML config per condition
4. Run: `helm benchmark run experiments/{name}/{condition}.yaml -n 8 --on-turn-limit end --experiments-dir experiments/{name}/runs`
5. Document findings in README.md

## Config Standards

All configs must use the current prompt framework:
- `shared_context` (top-level): situation all agents share
- `context` (per-agent): role and instructions
- `private_context` (per-agent, optional): hidden objectives

No `system_prompt` (deprecated). No framework language (no "Helm", "experiment", "broker"). No over-specified protocols — describe the role, let the agent figure out the strategy.

## Naming

`{number}_{short_description}` — e.g., `003_coordination_mechanisms`
