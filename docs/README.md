# Helm Docs

Active docs only. This directory explains how Helm works now.

Read in this order:
1. `../CLAUDE.md` — project context, current priority, structure
2. `architecture.md` — system shape and pipelines
3. `dimensions.md` — behavioral dimensions, validation status, scoring
4. `coordination-design-principles.md` — runtime vs policy boundaries
5. `run-data-contract.md` — derived artifact contract

Reference:
- `monitoring-evasion-design.md` — paired-run design for monitoring evasion (deferred)
- `resources.md` — external references and related work

Key source packages:
- `src/helm/adapters/` — harness adapters (Claude, Codex, OpenCode) + DirectCLI client
- `src/helm/judge/` — behavioral judge (backends, scoring, hierarchical strategy)
- `src/helm/topologies/` — topology families, enforcement rules, prompt templates
- `src/helm/agent_cli.py` — helm-agent coordination CLI
- `src/helm/topology_compliance.py` — compliance analysis
- `configs/` — runnable experiment configs
