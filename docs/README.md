# Helm Docs

Active docs only. This directory explains how Helm works now.

Read in this order when restarting:
1. `../CLAUDE.md` — project context, current priority, structure
2. `architecture.md` — system shape and pipelines
3. `dimensions.md` — behavioral dimensions and scoring
4. `coordination-design-principles.md` — runtime vs policy boundaries
5. `run-data-contract.md` — derived artifact contract

Reference docs (historical context, not active planning):
- `rq1-experiment-plan.md` — original experiment program (mostly superseded by matrix manifests)
- `judge-hardening-plan.md` — judge architecture evolution (hardening complete)
- `monitoring-evasion-design.md` — paired-run design for the 7th dimension (deferred)
- `resources.md` — external references

What each file is for:
- `architecture.md` — System shape, the three pipelines, coordination patterns
- `coordination-design-principles.md` — Runtime vs policy boundary for coordination
- `dimensions.md` — 5 validated + 1 excluded + 1 paired-run behavioral dimensions
- `run-data-contract.md` — Derived artifact contract for analysis/export

Project-state logs live in the vault:
- ledger: `shoshin-codex/projects/helm/progress-ledger.md`
- research log: `shoshin-codex/projects/helm/research-log.md`
- tasks: `shoshin-codex/tasks.md`

Source structure:
- `src/helm/cli.py` — main command surface
- `src/helm/matrix_families.py` — topology families, rules, prompts
- `src/helm/agent_cli.py` — helm-agent coordination CLI
- `src/helm/topology_compliance.py` — compliance analysis
