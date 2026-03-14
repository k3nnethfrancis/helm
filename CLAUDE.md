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

The current priority is **factorized topology expansion before RL**.

Reward validation is far enough along that Helm should now widen controlled evidence across architecture family, swarm size, and task structure instead of adding more ad hoc pattern YAMLs. RL is still downstream.

Near-term work should therefore focus on:
- the matrix substrate (`configs/matrices/`, `src/helm/matrix.py`, generator/runner/analyzer scripts)
- Wave 0 / Wave 1 SWE-bench matrix slices
- benchmark-flat but behavior-different comparisons across more than one task family
- using the active behavioral dimensions as first-class outputs in every comparison, not only post hoc notes

Use Claude Code as the main execution path unless there is a specific reason to widen to Codex or another harness.

The Helm context system now has four layers:
- `tasks.md` for priorities
- `progress-ledger.md` for implementation progress and project-state changes
- `research-log.md` for writeup-friendly experiment notes
- project docs / handoff files for durable operating context

The matrix workflow now also has a repo-local skill:
- `.claude/skills/helm-matrix-generation/SKILL.md`

## Key Concepts

### The Research Loop

```
Define experiment (task + swarm policy + harness) → Run agents on task
    → Collect full rollout traces → Score with verifiers + judges
        → Inspect behavior and failure modes → Refine metrics / policies
            → Train or prompt-tune on validated signals → Run again
```

The canonical artifact is the **swarm rollout**: task, topology, harness, orchestration policy, full trace, verifier outcome, and derived behavioral scores. Per-agent views are useful projections of that artifact, not the primary object of study.

### The Seven Dimensions

Candidate behavioral dimensions complementary to task performance. These are working hypotheses about coordination quality and human steerability, not a frozen ontology:

1. **Goal drift** — Do subtasks stay aligned with original objective?
2. **Context degradation** — Does information lose fidelity across agents?
3. **Failure suppression** — Are errors hidden from parent/human?
4. **Escalation calibration** — Does the system ask for help appropriately?
5. **Resource waste** — Is work duplicated? Tokens burned on dead ends?
6. **Monitoring evasion** — Does the swarm behave differently when observed?
7. **Human model accuracy** — Does the swarm understand human intent?

These dimensions are first evaluation instruments. Some may later become training targets if they prove stable and useful.

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
│ Prime RL / Optimization                 │
│ - Optional downstream training          │
│ - Uses validated signals from Helm      │
└─────────────────────────────────────────┘
```

## Project Structure

```
helm/
├── CLAUDE.md             # You are here
├── README.md             # Public-facing overview
├── plan.md               # Research plan with RQs and milestones
├── pyproject.toml        # Package config (hatchling build)
├── src/helm/             # Source package
│   ├── __init__.py
│   ├── cli.py            # Typer CLI (helm run, validate, judge, benchmark, analyze)
│   ├── collector.py      # Event aggregation and transcript generation
│   ├── config.py         # Pydantic models for experiment YAML config
│   ├── experiment.py     # Experiment lifecycle management
│   ├── judge.py          # Dual-backend judge (OpenRouter + SDK headless)
│   ├── runtime_guard.py  # Rule-based intervention engine
│   ├── run_data.py       # Run-data contract + orchestration evals
│   └── sdk.py            # Python client for Sandbox Agent SDK REST/SSE
├── configs/              # Prime RL configs and endpoint aliases
├── docs/                 # Documentation
├── environments/         # Prime RL training environments
├── judges/               # Dimension scoring rubrics
├── patterns/             # Experiment YAML configs (topologies, benchmarks)
├── experiments/          # Experiment run data
├── scripts/              # Utility scripts (verifiers, data download)
├── data/                 # Benchmark datasets (gitignored)
└── bin/                  # SDK binary
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

# Validate a pattern config
helm validate patterns/hub-and-spoke.yaml

# Run an experiment
helm run patterns/hub-and-spoke.yaml --task "Build a simple web server"

# Score an experiment
helm judge <experiment-id> --dimensions escalation-calibration,goal-drift

# Analyze an experiment
helm analyze <experiment-id>
```

### Benchmark Mode

```bash
# Run sampled benchmark experiments
helm benchmark run patterns/benchmark-swebench-single-claude.yaml -n 10 --seed 42

# Generate baseline report
helm benchmark report experiments/benchmark-runs/<summary>.json

# Export training data
helm benchmark export experiments/benchmark-runs/<summary>.json
```

### Adding a New Dimension

1. Create `judges/{dimension-name}.md` with scoring rubric
2. Add dimension to `docs/dimensions.md`
3. Update experiment configs to include new dimension

### Adding a New Coordination Pattern

1. Create `patterns/{pattern-name}.yaml` with topology
2. Run comparison experiments

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
Current Prime RL environments are single-turn (model generates text, gets scored). Training on full multi-turn agent traces requires multi-turn RL infrastructure. This is a known gap between current capability and any optimization goal.

### Trace Format
The swarm rollout is the canonical artifact, but per-agent projections are still useful for analysis and training. Implemented: `build_per_agent_training_records()` extracts one record per agent with trace slices, shared reward, and agent metadata. Reward attribution is shared (same composite for all agents) — credit assignment deferred.

## Progress Ledger

**Read `~/Desktop/lab/notes/shoshin-codex/projects/helm/progress-ledger.md` at the start of each session.** It has the running log of what was done, what's blocked, what's next, and key harness engineering notes.

## Research Log

**Read and update `~/Desktop/lab/notes/shoshin-codex/projects/helm/research-log.md` after meaningful experiment blocks.** Use it to record experiment questions, conditions, artifacts, concrete results, interpretations, confounds, next steps, and short writeup hooks. This is the layer intended to make later technical reporting easy without replaying every raw transcript.

## Theory Log

**`docs/theory.md`** documents the theoretical reasoning that underpins Helm's systems design — the *why* behind architectural decisions. Update it during research discussions that produce theoretical insights, design rationale, or connections to foundational literature. This is the reasoning companion to the progress ledger's implementation log.

## Harness Engineering Context

The harness (interface between model and workspace) is a critical confound in agent evaluation:
- Changing *only the edit format* improved one model from 6.7% → 68.3% ([can.ac](https://blog.can.ac/2026/02/12/the-harness-problem/))
- OpenAI's three pillars: documentation as intent, architectural constraints enforced mechanically, observability via telemetry ([OpenAI](https://openai.com/index/harness-engineering/))
- **Mechanical enforcement > prompt steering** — enforce structure via linters/CI, not just system prompts
- **Harness-model interaction** — no single format dominates across models. Multi-harness experiments surface this.

This means our `docs/harness-control-assessment.md` is critical before running baselines — we need to know what the harness controls vs what's "agent skill."
