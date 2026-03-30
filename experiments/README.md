# Experiments

Each subdirectory is a self-contained experiment.

## Standard Structure

```
experiments/{name}/
├── README.md          # Purpose, hypothesis, design, conditions, findings
├── experiment.md      # Detailed design notes (optional)
├── configs/           # Helm YAML configs (one per condition)
├── docs/              # Supporting documentation, prompt evolution, references
├── data/              # Experiment-specific data files (optional)
└── runs/              # Auto-created by helm at runtime (gitignored)
```

**`runs/` is created automatically by Helm.** Each run produces:
- `metadata.json` — config, timing, agent stats
- `transcripts/full.json` + `full.md` — complete traces
- `scores.json` — behavioral dimension scores
- `evaluation/task_verification.json` — SWE-bench test results
- `judge_artifacts/` — per-agent judge inputs, views, scores
- `coordination/` — message files, signals, .helm-config.json
- `mcp-configs/` — per-agent MCP server configs
- `workspace/repo/` — the code agents worked on

Don't create `runs/`, `results/`, or `figures/` manually. Helm creates what it needs.

## README.md Template

1. **Question** — What are we trying to learn?
2. **Hypothesis** — What do we expect?
3. **Conditions** — Table of configs and what varies
4. **Design** — Tasks, limits, baselines, measurements
5. **Running** — Exact commands
6. **Findings** — Updated as results come in

## Config Standards

- `shared_context` (top-level): situation all agents share
- `context` (per-agent): role and instructions
- `private_context` (per-agent, optional): hidden objectives
- No `system_prompt` (deprecated). No framework language. No over-specified protocols.

## Running

```bash
helm benchmark run experiments/{name}/configs/{condition}.yaml \
  -n 8 --on-turn-limit end \
  --experiments-dir experiments/{name}/runs
```

## Inventory

| Experiment | Status | Conditions |
|-----------|--------|------------|
| 001_topology_enforcement_baseline | Complete (historical) | single, centralized-5, hybrid-5, delegating-1 |
| 002_messaging_coordination | Ready | centralized-5 (messaging), hybrid-5 (filesystem), delegating-1 (native) |
| rogue-agent | Ready | control (cooperative), treatment (personality pressure) |
