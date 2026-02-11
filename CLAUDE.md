# Helm

Observation and evaluation framework for multi-agent AI systems.

## What This Is

Helm is a research framework for studying how humans observe, evaluate, and control multi-agent AI systems. It sits on top of orchestration primitives (Sandbox Agent SDK) and asks: can humans actually understand and steer these systems?

**This is research infrastructure, not a product.** We're building tools to run experiments on multi-agent coordination, measure behavioral dimensions, and understand failure modes.

## Core Research Question

*How do humans understand and stay in control of multi-agent AI systems?*

## Key Concepts

### The Seven Dimensions

We measure multi-agent systems along seven behavioral dimensions:

1. **Goal drift** — Do subtasks stay aligned with original objective?
2. **Context degradation** — Does information lose fidelity across agents?
3. **Failure suppression** — Are errors hidden from parent/human?
4. **Escalation calibration** — Does the system ask for help appropriately?
5. **Resource waste** — Is work duplicated? Tokens burned on dead ends?
6. **Monitoring evasion** — Does the swarm behave differently when observed?
7. **Human model accuracy** — Does the swarm understand human intent?

### The Stack

```
┌─────────────────────────────────────────┐
│ Helm (this project)                     │
│ - Experiment orchestration              │
│ - Multi-agent coordination              │
│ - Dimension evaluation                  │
│ - Analysis and reporting                │
└─────────────────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────┐
│ Sandbox Agent SDK                       │
│ - Universal agent API                   │
│ - Event streaming                       │
│ - Permission/intervention primitives    │
│ - Harness abstraction                   │
└─────────────────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────┐
│ Coding Agents                           │
│ - Claude Code, Codex, OpenCode, Amp     │
│ - Running in sandboxes                  │
└─────────────────────────────────────────┘
```

## Project Structure

```
helm/
├── CLAUDE.md             # You are here
├── README.md             # Public-facing overview
├── pyproject.toml        # Package config (hatchling build)
├── src/helm/             # Source package
│   ├── __init__.py
│   ├── cli.py            # Typer CLI (helm run, validate, judge, analyze)
│   ├── collector.py      # Event aggregation and transcript generation
│   ├── config.py         # Pydantic models for experiment YAML config
│   ├── experiment.py     # Experiment lifecycle management
│   ├── judge.py          # Dual-backend judge (OpenRouter + SDK headless)
│   ├── orchestrator.py   # Rule-based intervention engine
│   └── sdk.py            # Python client for Sandbox Agent SDK REST/SSE
├── docs/                 # Documentation
│   ├── architecture.md   # Technical architecture
│   ├── dimensions.md     # Dimension definitions and rubrics
│   └── resources.md      # External resources and references
├── judges/               # Dimension scoring rubrics
├── patterns/             # Coordination pattern configs
├── experiments/          # Experiment runs
└── scripts/              # Utility scripts
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
3. **Observation over control** — Study natural behavior, intervene minimally
4. **Separate concerns** — Orchestrator, swarm, and judge are isolated contexts
