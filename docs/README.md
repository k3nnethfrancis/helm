# Helm Docs

Active docs only. This directory should explain how Helm works now, not preserve every past phase.

Read in this order when restarting:

1. `../CLAUDE.md`
2. `/Users/kenneth/Desktop/lab/notes/shoshin-codex/projects/helm/vision.md`
3. `/Users/kenneth/Desktop/lab/notes/shoshin-codex/projects/helm/roadmap.md`
4. `rq1-experiment-plan.md`
5. `judge-hardening-plan.md`
6. `architecture.md`
7. `dimensions.md`
8. `run-data-contract.md`

What each file is for:
- `architecture.md`
  System shape and the main pipelines.
- `coordination-design-principles.md`
  Runtime vs policy boundary for coordination.
- `dimensions.md`
  Behavioral dimensions and what they mean.
- `judge-hardening-plan.md`
  Judge architecture and hardening path.
- `resources.md`
  External references worth keeping close.
- `rq1-experiment-plan.md`
  Active experiment program and matrix phase.
- `run-data-contract.md`
  Derived artifact contract for analysis/export.

Project-state logs do not live here:

- priorities: `/Users/kenneth/Desktop/lab/notes/shoshin-codex/tasks.md`
- long-term vision: `/Users/kenneth/Desktop/lab/notes/shoshin-codex/projects/helm/vision.md`
- long-term roadmap: `/Users/kenneth/Desktop/lab/notes/shoshin-codex/projects/helm/roadmap.md`
- ledger: `/Users/kenneth/Desktop/lab/notes/shoshin-codex/projects/helm/progress-ledger.md`
- research log: `/Users/kenneth/Desktop/lab/notes/shoshin-codex/projects/helm/research-log.md`

Use the ledger as the continuity layer when restarting work.

Source-structure note:
- `src/helm/cli.py` is now the main command surface, with shared helpers in `src/helm/cli_shared.py` and benchmark/report/export implementation in `src/helm/cli_benchmark.py`
- `src/helm/matrix.py` now focuses on manifest loading, generation flow, and summary analysis, while architecture family layouts/prompts live in `src/helm/matrix_families.py`
