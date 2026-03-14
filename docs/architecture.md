# Helm Architecture

## System Overview

Helm is an experimental layer over benchmarked and arbitrary computer-use tasks. It applies swarm policies to those tasks, runs them through different harnesses, collects the resulting traces, scores both outcome and behavior, and exports the evidence for comparison and iterative improvement.

Near-term, the architecture should be read as a **reward-validation lab**, not yet as a mature RL substrate. Benchmark outcome, behavioral judgments, and trace-derived metrics are all collected today, but the judged dimensions still need to clear repeatability and sensitivity gates before they are promoted into training reward.

```
┌─────────────────────────────────────────────────────────────────┐
│                         HELM                                    │
│                                                                 │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │ Task Layer                                                │  │
│  │ - benchmark adapter or arbitrary task                     │  │
│  │ - verifier / task outcome                                 │  │
│  └───────────────────────────────────────────────────────────┘  │
│                          │                                      │
│                          ▼                                      │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │ Swarm Policy Layer                                        │  │
│  │ - YAML topology, roles, orchestration rules, limits       │  │
│  └───────────────────────────────────────────────────────────┘  │
│                          │                                      │
│                          ▼                                      │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │ Execution Layer                                           │  │
│  │ - harness adapters / SDK daemon                           │  │
│  │ - agent sessions + shared filesystem                      │  │
│  └───────────────────────────────────────────────────────────┘  │
│                          │                                      │
│                          ▼                                      │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │ Evaluation Layer                                          │  │
│  │ - event collector                                         │  │
│  │ - behavioral judges                                       │  │
│  │ - trace-derived metrics                                   │  │
│  │ - runtime guard as safety net / experimental variable     │  │
│  └───────────────────────────────────────────────────────────┘  │
│                          │                                      │
│                          ▼                                      │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │ Alignment / Analysis Layer                                │  │
│  │ - comparison studies                                      │  │
│  │ - dataset export                                          │  │
│  │ - iterative improvement                                   │  │
│  └───────────────────────────────────────────────────────────┘  │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

## Components

### Experiment Runner (`experiment.py`)

Manages the full lifecycle of a swarm rollout:

1. **Setup**: Create experiment directory, parse config, initialize shared filesystem
2. **Spawn**: Start agent sessions via Sandbox Agent SDK, inject system prompts
3. **Run**: Monitor event streams until completion or timeout
4. **Collect**: Aggregate events into per-agent traces + unified transcript
5. **Teardown**: Stop sessions, finalize artifacts

Key: the experiment runner should be thought of as lab infrastructure, not the object of optimization. It packages a task with a swarm policy, runs it on a chosen harness, and preserves the resulting trace.

System prompts are injected via `post_message()`. They include:
- The agent's role and responsibilities
- Who the other agents are and what they do
- How to coordinate (filesystem paths, message conventions)
- Working directory context

This is one mechanism for prescribing agent behavior. It is guidance, not enforcement, which is why harness comparisons and trace inspection matter.

More generally: Helm should expose capabilities in the runtime, while keeping coordination policy in the explicit experiment condition. See [coordination-design-principles.md](/Users/kenneth/Desktop/lab/projects/helm/docs/coordination-design-principles.md).

### Runtime Guard (`runtime_guard.py`)

Monitors agent activity and decides when to intervene.

Architecturally, this should be treated as a safety net and experimental variable, not as the canonical orchestrator. If the runtime guard meaningfully changes behavior, that change is part of the condition being studied.

**Rule-based**: Apply configured rules to events
```yaml
rules:
  - on: permission.requested
    if: action contains "rm -rf"
    then: reject
  - on: no_activity
    after: 60s
    then: nudge_coordinator
```

Available actions: `approve`, `reject`, `escalate`, `escalate_to_human`, `log`, `nudge`, `nudge_coordinator`.

**Future**: Could be replaced/augmented with a trained policy model that makes real-time intervention decisions (this would be a deployment target for RQ3 behavioral monitor).

### Agent Harnesses

Two execution backends:

**DirectCLI** (default when all agents have registered adapters):
Spawns agent CLI subprocesses directly, bypassing the SDK daemon. Each harness has an adapter (`HarnessAdapter` subclass) that constructs the CLI command and parses NDJSON output into `SDKEvent` objects.

```python
from helm.sdk import DirectCLIClient, SessionConfig

sdk = DirectCLIClient()
await sdk.create_session(session_id, SessionConfig(agent="claude"))
await sdk.post_message(session_id, task_prompt)  # Spawns subprocess
async for event in sdk.stream_events(session_id):  # Reads NDJSON
    collector.record(session_id, event)
```

Registered adapters:
- `ClaudeAdapter`: `claude -p --output-format stream-json --verbose --dangerously-skip-permissions`
- `CodexAdapter`: `codex exec --json --dangerously-bypass-approvals-and-sandbox`

**SDK Daemon** (fallback for unknown harnesses):
Routes through the Sandbox Agent SDK daemon using ACP (JSON-RPC over HTTP). Used when an agent's harness doesn't have a registered adapter.

**Harness aliases** (`experiment.py:HARNESS_ALIASES`):
- `claude-code` → `claude` (Claude Code CLI)
- `codex` → `codex` (Codex CLI, GPT-5)
- `opencode` → `opencode` (OpenCode CLI, multi-provider via OpenRouter)
- `amp` → `amp` (Amp CLI)

#### Harness Control (Open Question)

The YAML config defines topology (hub-spoke, peer, etc.) and roles. But agents are autonomous, and harnesses differ in what they actually enforce. Current control mechanisms:

| Control | Mechanism | Enforcement |
|---------|-----------|-------------|
| Role/behavior | System prompt | Soft (model can ignore) |
| Permission gating | SDK permission events + runtime guard rules | Hard (if SDK enforces) |
| Turn limits | `max_turns_per_agent` config | Hard (Helm stops session) |
| Blocked commands | `limits.blocked_commands` config | Hard (permission denied) |
| Inactivity nudge | Timer-based `post_message()` | Soft |

What we **cannot** currently control:
- Sub-agent spawning (Claude Code's Agent/TeamCreate tools)
- Direct model-to-model communication outside filesystem
- Tool selection within the agent's native capabilities

**Open question**: Is system prompt steering sufficient for generating useful training traces? Or do we need hard constraints (e.g., Claude Code headless mode with `--allowedTools`, Codex flag equivalents)? This is empirical — run experiments, review traces, measure compliance.

### Shared Filesystem

Agents coordinate via filesystem. This is a policy choice and an experimental condition, not a universal truth about swarms:

```

The important boundary is:
- runtime exposes channels like shared files, persistent state, and live follow-up messages when available
- YAML/prompt decides how agents are asked to use those channels
- evaluation measures what they actually chose to do

Helm should not quietly turn a capability into a hidden policy default, because that contaminates the training/evaluation evidence.
experiments/{id}/
├── config.yaml           # Experiment configuration
├── coordination/
│   ├── messages/         # Timestamped inter-agent messages
│   ├── state.json        # Shared state
│   ├── signals/          # Coordination signals (ready, blocked, done)
│   ├── tasks/            # Hub-spoke task assignments
│   ├── status/           # Per-agent status files
│   └── reviews/          # Code review artifacts
├── workspace/            # Actual work artifacts (code, data)
├── transcripts/          # Per-agent event traces
├── scores.json           # Dimension scores
├── metadata.json         # Experiment metadata + provenance
├── run_data.json         # Versioned run data contract
└── summary.md            # Human-readable summary
```

### Event Collector (`collector.py`)

Aggregates events from all sessions.

- Per-agent traces (full tool calls, messages, coordination events)
- Unified multi-agent transcript (merged by timestamp)
- Information flow reconstruction
- Deterministic orchestration metrics

The collector should preserve enough raw detail that new evaluation questions can be asked later without rerunning the experiment.

#### Parallelism Metrics

Computed from transcript timing:
- `assistant_active_seconds`: summed assistant interval duration across all agents
- `wall_clock_seconds`: elapsed time first→last assistant step
- `critical_path_ratio`: `wall_clock / assistant_active`
- `parallelism_efficiency`: `1 - critical_path_ratio`

### Judge (`judge.py`)

Evaluates experiments in isolated context:

1. Spawn fresh session (no shared history with experiment)
2. Provide only the transcript + dimension rubric
3. Score with justification and evidence citations
4. Return structured result

Two backends:
- `sdk`: Claude Code headless (free, slower)
- `openrouter`: OpenRouter API (costs credits, faster, configurable model)

### Verifier

Task correctness verification:

- **Completion mode**: pass/fail based on coordination signals (`signals/done`)
- **Command mode**: run external verifier script per example
  - SWE-bench: `scripts/verify_swebench.py` — clones repo, applies patch, runs tests
  - Placeholders: `{experiment_dir}`, `{example_id}`, `{dataset_path}`, etc.

### Training Data Pipeline

```
Experiment run
    → Per-agent traces (event collector)
    → Judge scores (5 behavioral dimensions)
    → Verifier score (task pass/fail)
    → Candidate reward terms: benchmark + judged dimensions + trace metrics
    → Export: helm benchmark export → training JSONL
```

**Per-agent trace as one training view**: Each agent in a multi-agent experiment produces its own trace. One experiment with 3 agents can yield 3 role-specific examples.

**But the primary research unit is the swarm rollout**: the full policy + trace + verifier result + behavioral scores. Per-agent traces, orchestrator traces, and derived datasets are all views over that canonical artifact.

**Current state**:
- export already works for rollout artifacts and deterministic placeholder rewards
- judged dimensions are collected and saved, but are not yet treated as trusted reward terms
- the first job is to validate those dimensions before coupling them into RL

**Current limitation**: Export pipeline (`helm benchmark export`) still privileges simplified training rows. Full multi-turn traces with tool use sequences are collected, but the dataset story for swarm-level and orchestrator-level optimization is still evolving.

**Near-term implication**: the next phase is offline reward validation, not immediate online RL. See [rq1-experiment-plan.md](/Users/kenneth/Desktop/lab/projects/helm/docs/rq1-experiment-plan.md).

## Coordination Patterns

### Hub and Spoke

```
        ┌─────────┐
        │  Hub    │
        │(coord.) │
        └────┬────┘
             │
    ┌────────┼────────┐
    ▼        ▼        ▼
┌──────┐ ┌──────┐ ┌──────┐
│Work 1│ │Work 2│ │Work 3│
└──────┘ └──────┘ └──────┘
```

**Pros**: Clear authority, easier to trace decisions
**Cons**: Single point of failure, bottleneck, coordinator context degradation

### Peer Network

```
┌──────┐     ┌──────┐
│Agent1│◄───►│Agent2│
└──┬───┘     └───┬──┘
   │             │
   │  ┌──────┐   │
   └─►│Agent3│◄──┘
      └──────┘
```

**Pros**: Resilient, parallel work, no bottleneck
**Cons**: Coordination overhead, potential chaos, harder to attribute decisions

### Pipeline

```
┌──────┐    ┌──────┐    ┌──────┐
│Plan  │───►│Build │───►│Review│
└──────┘    └──────┘    └──────┘
```

**Pros**: Clear stages, quality gates
**Cons**: Sequential bottlenecks, no parallelism

## Intervention Points

Sandbox Agent SDK exposes two intervention mechanisms:

### Permission Approval

```python
if event.type == "permission.requested":
    permission_id = event.data.get("permission_id")
    action = event.data.get("action", "")
    # Rules can approve, reject, or escalate
    await sdk.reply_permission(session_id, permission_id, "once")    # approve
    await sdk.reply_permission(session_id, permission_id, "deny")    # reject
    await sdk.reply_permission(session_id, permission_id, "always")  # allow permanently
```

### Inactivity Detection

```yaml
orchestrator:
  rules:
    - on: no_activity
      after: 120s
      then: nudge_coordinator
      message: "A worker is idle. Check assignments and unblock if needed."
```

## Sandboxing

Agents run in isolated environments via:
- **Daytona**: Cloud sandboxes with git tracking
- **E2B**: Ephemeral compute sandboxes
- **Local**: OS-level sandboxing (Seatbelt/bubblewrap)

## Benchmark Mode

Two execution modes:
- `helm run`: arbitrary task, user-provided
- `helm benchmark run`: sampled from a pattern's `benchmark` block

Benchmark mode records per-example provenance (adapter, benchmark ID, split, seed, example ID) into metadata and `run_data.json`.

## Three Pipelines (Don't Conflate)

Helm touches models in three distinct ways:

| Pipeline | What runs | What it produces | Current state |
|----------|-----------|-----------------|---------------|
| **Agent execution** | Coding agent CLIs via DirectCLI/SDK | Per-agent traces | Claude working (single + multi-agent). Codex adapter written, untested. |
| **Judging** | LLM scoring transcripts | Dimension scores | Working (OpenRouter + SDK backends) |
| **RL training** | Prime trains on traces | Improved model weights | Single-turn envs working, multi-turn gap |

These are independent systems. "We used Qwen" (RL training target) and "we used OpenRouter" (judge backend) don't mean "we ran Qwen/OpenRouter as agents."
