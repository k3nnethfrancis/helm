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

**Critical finding:** Topology compliance analysis of the broader_panel corpus (24 runs) revealed that agents systematically violate prescribed topologies:
- **All 16 multi-agent runs** spawned subagents via Claude Code's native `Agent` tool (38 total spawns)
- **Even 2/8 single-agent runs** used `Agent` tool for delegation
- Centralized coordinators used `SendMessage` (9 times) instead of the filesystem protocol
- **Result: prior topology comparisons are confounded.** "Centralized" was actually "centralized + hidden subagents." Task score differences cannot be attributed to topology alone.

**The fix:** Mechanical tool enforcement, not prompt steering.
- Claude Code supports `--disallowedTools` to block `Agent`, `TeamCreate`, `SendMessage`
- Helm needs a controlled alternative: a Helm CLI/tool that agents call to coordinate, with topology rules enforced at the tool level
- This is the prerequisite for valid topology experiments

### What's Validated (Still Good)

**Judge dimensions (J4 post-hardening, 2026-03-21):**
- `escalation-calibration` — 100% counterparty agreement
- `goal-drift` — 100% counterparty agreement
- `human-model-accuracy` — 67% counterparty agreement
- `context-degradation` — 67% (soft signal)
- `resource-waste` — 33% (soft signal)
- `failure-suppression` — excluded (0% agreement)

**Topology compliance analyzer** (`src/helm/topology_compliance.py`): extracts tool usage, subagent spawns, messaging patterns, and filesystem coordination from transcripts. Produces per-agent and per-experiment compliance scores.

### What's Invalid (Needs Re-Run After Enforcement)

- All prior topology comparison results (size ladder, broader panel)
- The `benchmark-flat / behavior-different` narrative is still directionally suggestive but not cleanly attributable to topology
- The broader_panel wave needs to be re-run after enforcement is implemented

### Next Sequence

1. **Build topology enforcement layer** — Helm CLI tool + `--disallowedTools` integration in adapters
2. **Clean the repo for sharing** — delete stale patterns, gitignore experiments, document topology designs
3. **Re-run broader_panel** with mechanical enforcement + compliance verification
4. **Run Codex mirror** when budget available
5. **Blog post** gated on clean, enforced, compliance-verified data

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

Generated matrix patterns under `patterns/generated/` are runtime artifacts, not
source of truth. The source of truth for matrix conditions is the manifest in
`configs/matrices/`.

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
│ Downstream RL / Optimization            │
│ - Optional later training               │
│ - Uses validated signals exported by Helm │
└─────────────────────────────────────────┘
```

## Project Structure

```text
helm/
├── CLAUDE.md             # You are here
├── README.md             # Public-facing overview
├── pyproject.toml        # Package config (hatchling build)
├── src/helm/             # Source package
│   ├── __init__.py
│   ├── cli.py            # Main Typer command surface
│   ├── cli_shared.py     # Shared CLI helpers (paths, escalation, turn limits, output)
│   ├── cli_benchmark.py  # Benchmark/report/export CLI implementation helpers
│   ├── collector.py      # Event aggregation and transcript generation
│   ├── config.py         # Pydantic models for experiment YAML config
│   ├── experiment.py     # Experiment lifecycle management
│   ├── judge.py          # Multi-backend judge (Claude/Codex headless + OpenRouter)
│   ├── matrix.py         # Matrix manifest loading, generation flow, and analysis
│   ├── matrix_families.py # Architecture families, prompts, coordination/orchestrator defs
│   ├── runtime_guard.py  # Rule-based intervention engine
│   ├── run_data.py       # Run-data contract + orchestration evals
│   └── sdk.py            # Python client for Sandbox Agent SDK REST/SSE
├── configs/              # Matrix manifests
├── docs/                 # Small active doc set
│   └── README.md         # Doc map and restart order
├── judges/               # Dimension scoring rubrics
├── patterns/             # Hand-authored experiment YAML configs
│   └── generated/        # Generated matrix outputs (runtime artifacts)
├── experiments/          # Experiment run data
├── scripts/              # Matrix, judge, and benchmark support scripts
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
