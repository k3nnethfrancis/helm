# Helm

Experimental environment for studying, evaluating, and iteratively improving computer-use orchestrators and swarms.

## What This Is

Helm is research infrastructure for running swarm experiments on real computer-use tasks, collecting full rollout traces, and comparing how different orchestrators, topologies, harnesses, and evaluation schemes behave.

We do not assume we already know what "better coordination" means. Helm exists to help discover, test, refine, and eventually optimize that definition by attaching behavioral and control-oriented evaluation to existing benchmarks and arbitrary tasks.

**Evaluation comes before optimization.** Measurement, trace collection, and analysis are first-class. Training is downstream of evidence that a signal is useful.

**This is research infrastructure, not a product.**

## Core Research Question

*How do different orchestrators and swarm policies change task performance, coordination quality, and human steerability on real computer-use tasks?*

This breaks down into:
1. Can we measure coordination quality and human steerability in ways that meaningfully differentiate models, harnesses, and topologies?
2. Which orchestration policies and swarm structures improve outcomes, and where do they add failure modes?
3. Which signals are robust enough to become training targets for iterative alignment?

## Current Priority

The current priority is **topology enforcement and repo cleanup before the next experiment run**.

### Where We Are (2026-03-22)

**Repo is clean, refactored, and enforcement-ready.**

Completed this session:
- Source refactored: 3 monolithic files → 3 subpackages (`adapters/`, `judge/`, `topologies/`)
- Topology enforcement built and verified: `--disallowedTools` + `helm-agent` CLI → 1.00 compliance on test run
- Topology-adherence judge dimension added (8th dimension)
- Repo restructured: `configs/` (4 topology YAMLs), `experiments/` (tracked, numbered), `runs/` (gitignored)
- Stale code deleted: 22 patterns, 6 scripts, 2 docs, tracked experiment data
- Experiment 001 scaffolded

**Judge dimensions (J4 post-hardening, 2026-03-21):**
- `escalation-calibration` — 100% counterparty agreement
- `goal-drift` — 100% counterparty agreement
- `human-model-accuracy` — 67% counterparty agreement
- `context-degradation` — 67% (soft signal)
- `resource-waste` — 33% (soft signal)
- `topology-adherence` — new, needs J4 validation
- `failure-suppression` — excluded (0% agreement)

### Immediate Next Steps

1. **Run experiment 001** (topology enforcement baseline): 4 topologies × 8 SWE-bench tasks with mechanical enforcement
2. **Validate topology-adherence dimension** via cross-judge counterparty comparison
3. **Run Codex mirror** when budget available — head-to-head Claude vs Codex comparison
4. **Blog post** reporting which agents and topologies produce better multi-agent coordination

### Medium-Term

5. **RL pilot** — closure-first reward on centralized@5, gated on clean experiment data
6. **Terminal-Bench integration** — second benchmark substrate (ICLR 2026, 89 CLI tasks)
7. **Prompt template extraction** — move 600+ lines of f-strings from prompts.py to .md template files

### Long-Term Vision

Helm exists to answer: **How do humans understand and stay in control of multi-agent AI systems?**

The research arc is: measure coordination quality → validate measurement instruments → identify trainable signals → optimize agents to coordinate better while remaining steerable. The current phase (measure + validate) feeds the downstream phase (train). Everything in Helm — the topologies, dimensions, enforcement, compliance analysis — is infrastructure for producing reliable training signals for multi-agent coordination under human control.

### Key Synthesis Artifacts

- `notes/shoshin-codex/projects/helm/helm-internal-technical-report-2026-03-20.md`
- `notes/shoshin-codex/projects/helm/helm-rl-pilot-design-2026-03-20.md`
- `notes/shoshin-codex/projects/helm/helm-j4-crossjudge-synthesis-2026-03-21.md`
- `notes/shoshin-codex/projects/helm/helm-j4-post-hardening-synthesis-2026-03-21.md`

Use Claude Code as the main execution path unless there is a specific reason to widen to Codex or another harness.

The Helm context system now has four layers:
- `tasks.md` for priorities
- `progress-ledger.md` for implementation progress and project-state changes
- `research-log.md` for writeup-friendly experiment notes
- project docs for durable operating context

The matrix workflow now also has a repo-local skill:
- `.claude/skills/helm-matrix-generation/SKILL.md`

Matrix manifests generate experiment patterns into `runs/generated/` (gitignored).
The source of truth for experiments is `configs/` (standalone configs) or matrix
manifests in your experiment directory.

The repo is intentionally narrower than earlier phases:
- no active Prime RL environment layer inside Helm
- no active Tau / Terminal-Bench substrate inside Helm
- no need to preserve one-off probe patterns once their outputs are durable in artifacts and notes

## Key Concepts

### The Research Loop

```
Define experiment (task + swarm policy + harness) → Run agents on task
    → Collect full rollout traces → Score with verifiers + judges
        → Inspect behavior and failure modes → Refine metrics / policies
            → Train or prompt-tune on validated signals → Run again
```

The canonical artifact is the **swarm rollout**: task, topology, harness, orchestration policy, full trace, verifier outcome, and derived behavioral scores. Per-agent views are useful projections of that artifact, not the primary object of study.

### Behavioral Dimensions

Five validated dimensions (J4 cross-judge agreement), one excluded, one paired-run:

**Validated (include in experiments):**
1. **Escalation calibration** — 100% cross-judge agreement
2. **Goal drift** — 100% cross-judge agreement
3. **Human model accuracy** — 67% cross-judge agreement
4. **Context degradation** — 67% (soft signal)
5. **Resource waste** — 33% (soft signal, directionally consistent)

**Excluded:** Failure suppression — 0% cross-judge agreement survives hardening. Needs trace-derived redesign.

**Paired-run only:** Monitoring evasion — requires A/B experimental design, not per-run scoring.

### Topology Enforcement

Topologies are mechanically enforced, not just prompt-steered:
- `--disallowedTools` blocks native Agent/TeamCreate/SendMessage per `TOPOLOGY_RULES`
- `helm-agent` CLI (`agent_cli.py`) provides controlled send/inbox/status/spawn
- `.helm-config.json` written during setup with per-agent permissions
- `topology_compliance.py` verifies enforcement held post-run

### The Stack

```
┌─────────────────────────────────────────┐
│ Helm (this project)                     │
│ - Task + swarm experiment design        │
│ - Agent execution + trace collection    │
│ - Behavioral / control evaluation       │
│ - Analysis and reporting                │
│ - Training data generation (downstream) │
└─────────────────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────┐
│ Sandbox Agent SDK                       │
│ - Universal agent API                   │
│ - Event streaming (SSE)                 │
│ - Permission/intervention primitives    │
│ - Harness abstraction                   │
└─────────────────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────┐
│ Coding Agent Harnesses                  │
│ - Claude Code, Codex, OpenCode, etc.    │
│ - Running in sandboxes                  │
│ - Configured per YAML spec              │
└─────────────────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────┐
│ Downstream RL / Optimization            │
│ - Optional later training               │
│ - Uses validated signals exported by Helm │
└─────────────────────────────────────────┘
```

## Project Structure

```text
helm/
├── src/helm/
│   ├── adapters/            # Harness adapters (Claude, Codex, OpenCode) + DirectCLI client
│   ├── judge/               # Behavioral judge (backends, scoring, hierarchical strategy)
│   ├── topologies/          # Topology families, enforcement rules, prompt templates
│   ├── benchmarks/          # Benchmark adapters (SWE-bench), verification, export
│   ├── coordination/        # Inter-agent coordination backends (filesystem)
│   ├── cli.py               # Main Typer CLI
│   ├── agent_cli.py         # helm-agent coordination CLI (send/inbox/status/spawn)
│   ├── config.py            # Pydantic experiment config models
│   ├── experiment.py        # Experiment lifecycle
│   ├── topology_compliance.py  # Deterministic compliance analysis
│   ├── matrix.py            # Matrix manifest generation + analysis
│   ├── collector.py         # Event aggregation + transcript rendering
│   ├── run_data.py          # Run-data contract + orchestration evals
│   ├── runtime_guard.py     # Rule-based intervention engine
│   ├── sdk.py               # Re-export shim → adapters/
│   └── matrix_families.py   # Re-export shim → topologies/
├── configs/                 # Runnable topology configs (ship with Helm)
│   ├── single-agent.yaml
│   ├── centralized-5.yaml
│   ├── hybrid-5.yaml
│   └── delegating-1.yaml
├── judges/                  # Behavioral dimension rubrics (7 active + 1 excluded)
├── experiments/             # Curated experiment results (tracked, numbered)
├── scripts/                 # Pipeline scripts (generate → run → analyze)
├── tests/                   # Test suite
├── docs/                    # Documentation
├── runs/                    # Raw experiment data (gitignored)
└── data/                    # Benchmark datasets (gitignored)
```

## How to Work on This Project

### Key Dependencies

- **Python 3.11+** with `uv` for package management
- **Sandbox Agent SDK binary**: `bin/sandbox-agent` (see README for install)
- **Package deps**: httpx, httpx-sse, pyyaml, pydantic, typer (see `pyproject.toml`)

### Running Experiments

```bash
# Install the package (editable mode)
uv pip install -e .

# Generate experiment patterns from a matrix manifest
# Run a single topology config on one SWE-bench task
helm benchmark run configs/centralized-5.yaml -n 1 --direct-cli --on-turn-limit end

# Run a matrix manifest (batch experiments)
python scripts/run_experiment_matrix.py <manifest>.yaml --wave <wave>

# Score a completed experiment
helm judge <experiment-id> -b claude-headless -m claude-sonnet-4-6

# Analyze matrix results
python scripts/analyze_experiment_matrix.py experiments/benchmark-runs/<summary1>.json <summary2>.json
```

### Adding a New Dimension

1. Create `judges/{dimension-name}.md` with scoring rubric
2. Add dimension to `docs/dimensions.md` and `src/helm/cli_shared.py:ACTIVE_BEHAVIORAL_DIMENSIONS`
3. Validate cross-judge agreement before using as reward signal

### Adding a New Topology Family

1. Add layouts to `FAMILY_LAYOUTS` in `src/helm/topologies/families.py`
2. Add topology rules to `TOPOLOGY_RULES` in `src/helm/topologies/rules.py`
3. Add coordination label to `COORDINATION_FAMILY_LABELS` in `families.py`
4. Add supported sizes to `SUPPORTED_FAMILY_SIZES` in `families.py`
5. Write system prompts for each role in `src/helm/topologies/prompts.py`
6. Create a config YAML in `configs/` for the new topology

## Design Principles

1. **Real tasks, not synthetic scenarios** — Test with actual coding/research work
2. **Harness agnostic** — Work with any agent via Sandbox Agent SDK
3. **Evaluation precedes optimization** — Treat new metrics and labels as hypotheses before using them as rewards
4. **Swarm rollout is the main unit** — The whole coordinated run matters more than any single agent transcript
5. **Harness effects are scientific variables** — Claude Code, Codex, OpenCode, and others are part of the experiment, not just plumbing
6. **Task-agnostic design, verifier-dependent execution** — Support any task type, start where verification is easiest (SWE-bench)
7. **Separate concerns** — Experiment runner, intervention layer, and judge are isolated contexts

## Open Questions

### Harness Control
How much can we control agent behavior through the harness? The YAML defines topology (hub-spoke, peer, etc.) and roles, but agents can deviate. Key questions:
- Can we disable sub-agent spawning in Claude Code? (headless mode flags)
- Does Codex or OpenCode have equivalent controls?
- Is system prompt steering sufficient, or do we need hard constraints?
- Empirical approach: run experiments, review traces, measure compliance with prescribed patterns.

### Coordination Ontology
We do not yet have a complete definition of "better orchestration." Key questions:
- Which behavioral dimensions survive contact with real traces?
- Which metrics correlate with genuine improvement versus cosmetic compliance?
- When does a strong single agent beat a swarm with fewer failure modes?

### Multi-Turn Optimization
Helm no longer keeps active Prime environment packages or RL configs in-repo. When the project returns to Prime RL, that substrate should be regenerated from the validated benchmark/export corpus rather than treated as current source of truth.

### Trace Format
The swarm rollout is the canonical artifact, but per-agent projections are still useful for analysis and training. Implemented: `build_per_agent_training_records()` extracts one record per agent with trace slices, shared reward, and agent metadata. Reward attribution is shared (same composite for all agents) — credit assignment deferred.

## Progress Ledger

**Read `~/Desktop/lab/notes/shoshin-codex/projects/helm/progress-ledger.md` at the start of each session.** It has the running log of what was done, what's blocked, what's next, and key harness engineering notes.

## Research Log

**Read and update `~/Desktop/lab/notes/shoshin-codex/projects/helm/research-log.md` after meaningful experiment blocks.** Use it to record experiment questions, conditions, artifacts, concrete results, interpretations, confounds, next steps, and short writeup hooks. This is the layer intended to make later technical reporting easy without replaying every raw transcript.

## Harness Engineering Context

The harness (interface between model and workspace) is a critical confound in agent evaluation:
- Changing *only the edit format* improved one model from 6.7% → 68.3% ([can.ac](https://blog.can.ac/2026/02/12/the-harness-problem/))
- OpenAI's three pillars: documentation as intent, architectural constraints enforced mechanically, observability via telemetry ([OpenAI](https://openai.com/index/harness-engineering/))
- **Mechanical enforcement > prompt steering** — enforce structure via linters/CI, not just system prompts
- **Harness-model interaction** — no single format dominates across models. Multi-harness experiments surface this.

Treat harness behavior as a standing confound in baseline interpretation. When a result shifts materially, inspect whether the change came from orchestration policy, model capability, or harness mechanics before treating it as a behavioral conclusion.
