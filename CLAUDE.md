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

**Running experiment 002: multi-agent coordination with minimal prompts, no turn limits, clean MCP tooling.**

### Where We Are (2026-03-29)

**Architecture:**
- **Headless-only runtime.** `HeadlessCLIClient` — one `claude -p` per agent, full NDJSON traceability.
- **Agent-orchestrator MCP server** — agents see `send_message`, `check_inbox`, `list_agents`, `signal_complete`. Generic names, no experiment/framework language. Self-documenting tool descriptions.
- **Prompt framework** — `shared_context` (all agents), `context` (per-agent), `private_context` (hidden, adversarial). Framework injects only `## Environment` and `## Agents`. No framework-injected coordination instructions — MCP tools are self-documenting.
- **Topology enforcement**: Mechanical (`--disallowedTools` + broker rules) or prompt-only — configurable per experiment.
- **Delivery tracking**: Broker fires `on_delivery` callback when messages are polled — `CoordinationMessage` objects update in-place.

**Experiment 002 (in progress):**
- Centralized-5 (messaging, mechanical enforcement): smoke test running
- Hybrid-5 (filesystem): ready to launch
- Delegating-1 (native Agent tool): ready to launch
- All configs: minimal prompts, no turn limits, 60min timeout
- Same 8 SWE-bench tasks as experiment 001 for fair comparison

**Experiment 001 findings (baseline):**
- Single-agent: 8/8 complete, 4/8 solved (50%)
- Centralized@5 v1: coordinator collapsed topology
- Centralized@5 v2: 30-50% polling waste, no done signal
- Key finding: structural compliance ≠ behavioral compliance

### Immediate Next Steps

1. **Monitor experiment 002 smoke test** — verify prompt framework works end-to-end
2. **Launch all 3 conditions × 8 tasks** once smoke test passes
3. **Review traces** — compare with experiment 001 data
4. **Adversarial experiment** — use `private_context` for hidden-objective agent (rogue-agent experiment)
5. **Blog post** — single-agent vs multi-agent, coordination overhead, what makes multi-agent work

### Medium-Term

5. **Filesystem vs messaging comparison** — same topology, different coordination channels, measure the difference
6. **RL pilot** — gated on clean experiment corpus with working coordination
7. **Terminal-Bench integration** — second benchmark substrate

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
│   ├── adapters/            # Harness adapters (Claude, Codex, OpenCode) + DirectCLI/Tmux/Resumable clients
│   ├── judge/               # Behavioral judge (backends, scoring, hierarchical strategy)
│   ├── topologies/          # Topology families, enforcement rules, prompt templates
│   ├── benchmarks/          # Benchmark adapters (SWE-bench), verification, export
│   ├── coordination/        # Inter-agent coordination backends (filesystem, messaging)
│   ├── cli.py               # Main Typer CLI (run, judge, view, analyze, ...)
│   ├── agent_cli.py         # helm-agent coordination CLI (send/inbox/status/spawn)
│   ├── config.py            # Pydantic experiment config models (incl. CoordinationMechanism enum)
│   ├── experiment.py        # Experiment lifecycle + config-driven prompt injection
│   ├── viewer.py            # HTML transcript viewer (per-agent panels, coordination log)
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

## Hard Rules

- **NEVER modify agent system prompts or experiment YAML configs without Kenneth's explicit review.** Prompts are experimental conditions. Changing them changes the experiment. Always show proposed prompt changes and get approval before writing them.
- **NEVER modify judge rubrics** (`judges/*.md`) without review. Same reasoning — these are measurement instruments.
- **Framework-injected coordination instructions** (in `experiment.py`, `broker_backend.py`) are plumbing, not experimental conditions — those can be fixed for bugs. But if a change would alter what agents see or how they behave, flag it.

## Design Principles

1. **Config-driven, not opinionated** — The YAML config is the experiment definition. Helm executes faithfully. The researcher decides what to enforce vs leave to prompting.
2. **Real tasks, not synthetic scenarios** — Test with actual coding/research work
3. **Harness agnostic** — Work with any agent via Sandbox Agent SDK
4. **Evaluation precedes optimization** — Treat new metrics and labels as hypotheses before using them as rewards
5. **Swarm rollout is the main unit** — The whole coordinated run matters more than any single agent transcript
6. **Harness effects are scientific variables** — Claude Code, Codex, OpenCode, and others are part of the experiment, not just plumbing
7. **Task-agnostic design, verifier-dependent execution** — Support any task type, start where verification is easiest (SWE-bench)
8. **Separate concerns** — Experiment runner, intervention layer, and judge are isolated contexts

## Open Questions

### Inter-Agent Messaging (Resolved, 2026-03-29)
**Resolved:** Push delivery works via tmux. `TmuxCLIClient` runs persistent interactive claude sessions; broker injects messages via `tmux paste-buffer`. `ResumableCLIClient` provides an alternative using `claude -p --resume UUID`. Both selected via `delivery: push` in config. Channel push via MCP notifications doesn't work in `claude -p` mode (v2.1.81) — tmux bypasses this entirely.

### Coordination Channel as Experimental Variable (Resolved, 2026-03-28)
**Resolved:** Config-driven. `coordination.mechanism: filesystem | messaging`, `coordination.delivery: push | poll`, `coordination.enforcement: mechanical | prompt-only`. Single-channel cleaner than dual-channel per experiment 001 findings.

### Harness Control (Partially Resolved)
Topology enforcement works mechanically via `--disallowedTools` (1.00 compliance). But **behavioral compliance** is a separate layer — coordinators follow tool restrictions while still collapsing structure (doing work themselves, writing fake status, closing prematurely). Prompt constraints help but aren't sufficient. The gap between structural compliance and behavioral compliance is itself a finding.

### Coordination Ontology
- Which behavioral dimensions survive contact with real traces? (5/6 validated via J4)
- When does a strong single agent beat a swarm? (Current evidence: always, on bounded-turn tasks with polling-based coordination)
- What infrastructure would make multi-agent worth the overhead? (Push messaging, plan-then-dispatch, shared memory)

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
