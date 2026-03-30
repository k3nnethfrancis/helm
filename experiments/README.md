# Experiments

Each subdirectory is a self-contained experiment.

## Standard Structure

```
experiments/{name}/
├── README.md          # Purpose, hypothesis, design, conditions, findings
├── *.yaml             # Helm configs (one per condition, flat — not in a subdir)
├── runs/              # Auto-created by helm (gitignored)
├── results/           # Curated analysis, scored summaries (tracked)
├── figures/           # Visualizations (tracked)
├── notes/             # Design docs, prompt evolution, working notes (optional)
└── data/              # Experiment-specific data files (optional)
```

## README.md Template

Every experiment README should have:

1. **Question** — What are we trying to learn?
2. **Hypothesis** — What do we expect to happen?
3. **Conditions** — Table of configs and what varies between them
4. **Design** — Tasks, turn limits, baselines, what we're measuring
5. **Running** — Exact commands to reproduce
6. **Findings** — Updated as results come in

## Config Standards

All configs use the current prompt framework:
- `shared_context` (top-level): situation all agents share
- `context` (per-agent): role and instructions
- `private_context` (per-agent, optional): hidden objectives

No `system_prompt` (deprecated). No framework language. No over-specified protocols.

## Running

```bash
helm benchmark run experiments/{name}/{condition}.yaml \
  -n 8 --on-turn-limit end \
  --experiments-dir experiments/{name}/runs
```

## Naming

`{number}_{short_description}` — e.g., `003_coordination_mechanisms`

Exception: `rogue-agent` predates this convention.

## Inventory

| Experiment | Status | Conditions |
|-----------|--------|------------|
| 001_topology_enforcement_baseline | Complete (historical, old config format) | single, centralized-5, hybrid-5, delegating-1 |
| 002_messaging_coordination | In progress | centralized-5 (messaging), hybrid-5 (filesystem), delegating-1 (native) |
| rogue-agent | Ready to run | control (cooperative), treatment (researcher_b personality) |
