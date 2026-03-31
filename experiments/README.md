# Experiments

Each subdirectory is a self-contained experiment.

## Standard Structure

```
experiments/{name}/
├── README.md          # Purpose, hypothesis, design, findings (encouraged)
├── experiment.md      # Detailed design notes (encouraged)
├── configs/           # Helm YAML configs (one per condition)
├── tasks/             # Task definitions (when not using a pre-built benchmark)
├── environments/      # Files to plant in workspace (referenced by config)
├── docs/              # Documentation, notes, references (subfolders as needed)
└── runs/              # Auto-created by Helm at runtime (gitignored)
```

### Primitives

| Folder | Purpose | Required? |
|--------|---------|-----------|
| `configs/` | Helm YAML configs — one per experimental condition | Yes |
| `tasks/` | Task definitions (JSONL, markdown, etc.) | Only if not using SWE-bench or similar |
| `environments/` | Files planted into agent workspace before run starts | Only if experiment needs planted artifacts |
| `runs/` | Traces, logs, judge output, transcripts | Auto-created by Helm |

### Documentation

| File | Purpose |
|------|---------|
| `README.md` | Question, hypothesis, conditions, design, findings |
| `experiment.md` | Detailed design notes |
| `docs/` | Any supporting .md files, organized with subfolders as needed |

### What Helm Produces (in `runs/`)

Each run creates a subdirectory with:
- `metadata.json` — config, timing, agent stats
- `transcripts/full.json` + `full.md` — complete traces
- `scores.json` — behavioral dimension scores
- `evaluation/task_verification.json` — test results
- `judge_artifacts/` — per-agent judge inputs and scores
- `coordination/` — messages, signals, config
- `mcp-configs/` — per-agent MCP server configs
- `workspace/repo/` — the code agents worked on

## Config Standards

- `shared_context` (top-level): situation all agents share
- `context` (per-agent): role and instructions
- `private_context` (per-agent, optional): hidden objectives
- `environment.workspace_files`: files to plant in workspace (paths relative to experiment dir)

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
