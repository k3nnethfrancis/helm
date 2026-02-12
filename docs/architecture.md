# Helm Architecture

## System Overview

Helm orchestrates multi-agent experiments, observes their behavior, and evaluates coordination quality. It builds on Sandbox Agent SDK for agent management and adds coordination, observation, and evaluation layers.

```
┌─────────────────────────────────────────────────────────────────┐
│                         HELM                                     │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ Experiment Runner                                        │    │
│  │ - Reads pattern config (YAML)                            │    │
│  │ - Spawns agent sessions via Sandbox Agent SDK            │    │
│  │ - Sets up shared filesystem                              │    │
│  │ - Manages experiment lifecycle                           │    │
│  └─────────────────────────────────────────────────────────┘    │
│                          │                                       │
│                          ▼                                       │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ Runtime Guard                                            │    │
│  │ - Subscribes to event streams from all sessions          │    │
│  │ - Applies intervention rules                             │    │
│  │ - Approves/rejects permissions                           │    │
│  │ - Detects stuck states, nudges agents                    │    │
│  │ - (Optional) Escalates/pauses for human intervention     │    │
│  └─────────────────────────────────────────────────────────┘    │
│                          │                                       │
│     ┌────────────────────┼────────────────────┐                 │
│     ▼                    ▼                    ▼                 │
│  ┌──────────┐      ┌──────────┐         ┌──────────┐           │
│  │ Agent 1  │      │ Agent 2  │   ...   │ Agent N  │           │
│  │ Session  │      │ Session  │         │ Session  │           │
│  │          │◄────►│          │◄───────►│          │           │
│  │ (via SDK)│      │ (via SDK)│         │ (via SDK)│           │
│  └──────────┘      └──────────┘         └──────────┘           │
│        │                 │                    │                 │
│        └─────────────────┼────────────────────┘                 │
│                          ▼                                       │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ Shared Filesystem                                        │    │
│  │                                                          │    │
│  │  coordination/                                           │    │
│  │  ├── messages/        # Inter-agent messages             │    │
│  │  ├── state.json       # Shared state                     │    │
│  │  └── signals/         # Coordination signals             │    │
│  │                                                          │    │
│  │  workspace/           # Actual work artifacts            │    │
│  └─────────────────────────────────────────────────────────┘    │
│                          │                                       │
│                          ▼                                       │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ Event Collector                                          │    │
│  │ - Aggregates streams from all sessions                   │    │
│  │ - Persists to experiments/{id}/                          │    │
│  │ - Reconstructs multi-agent transcript                    │    │
│  └─────────────────────────────────────────────────────────┘    │
│                          │                                       │
│                          ▼                                       │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ Judge (Separate Context)                                 │    │
│  │ - Fresh agent session, no shared history                 │    │
│  │ - Receives only transcript                               │    │
│  │ - Scores against dimension rubric                        │    │
│  │ - Returns score + justification + evidence               │    │
│  └─────────────────────────────────────────────────────────┘    │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

## Components

### Experiment Runner

Manages the full lifecycle of an experiment:

1. **Setup**: Create experiment directory, parse config, initialize shared filesystem
2. **Spawn**: Start agent sessions via Sandbox Agent SDK
3. **Run**: Monitor until completion or timeout
4. **Collect**: Aggregate all events into unified transcript
5. **Teardown**: Stop sessions, finalize artifacts

### Runtime Guard (Rule Engine)

Monitors agent activity and decides when to intervene. Two modes:

**Rule-based**: Apply configured rules to events
```yaml
rules:
  - on: permission.requested
    if: action contains "rm -rf"
    then: reject
  - on: no_activity
    after: 60s
    then: nudge
```

**Agent-based (future)**: A separate agent could monitor streams and make judgment calls. More flexible but harder to analyze.

### Sandbox Agent SDK Integration

Each agent session is managed via Sandbox Agent SDK:

```python
from helm.sdk import SDKClient, SDKConfig, SessionConfig

# Start daemon and connect
sdk = SDKClient(SDKConfig(binary_path=Path("bin/sandbox-agent")))
await sdk.start()

# Create session
session_config = SessionConfig(agent="claude", permission_mode="bypass")
await sdk.create_session(session_id, session_config)

# Send task
await sdk.post_message(session_id, task_prompt)

# Stream events
async for event in sdk.stream_events(session_id):
    collector.record(session_id, event)

    if event.type == "permission.requested":
        permission_id = event.data.get("permission_id")
        await sdk.reply_permission(session_id, permission_id, "once")
```

### Shared Filesystem

Agents coordinate via filesystem rather than direct communication:

```
experiments/{id}/
├── config.yaml           # Experiment configuration
├── coordination/
│   ├── messages/         # Timestamped message files
│   │   ├── 001-agent1-to-all.md
│   │   └── 002-agent2-to-agent1.md
│   ├── state.json        # Shared state (who's doing what)
│   └── signals/          # Coordination signals
│       ├── agent1.ready
│       └── agent2.blocked
├── workspace/            # Actual work artifacts
│   ├── src/
│   └── tests/
├── transcripts/          # Captured events per agent
│   ├── agent1.jsonl
│   └── agent2.jsonl
├── scores.json           # Dimension scores
└── summary.md            # Human-readable summary
```

### Event Collector

Aggregates events from all sessions into a unified transcript:

- Merge streams by timestamp
- Link parent/child events across agents
- Reconstruct information flow
- Persist in standard format
- **Compute Critical Steps metric** (latency-oriented, see dimensions.md)

#### Critical Steps Calculation

Borrowed from Kimi K2.5's PARL framework. For each execution stage t:

```
CriticalSteps = Σ(S_main(t) + max_i S_sub,i(t))
```

This captures the critical path through parallel execution—only work that reduces latency counts. Derived metrics:
- Coordination overhead = total steps − critical steps
- Parallelization efficiency = critical steps / total steps

### Judge

Evaluates experiments in a separate, isolated context:

1. Spawn fresh agent session (no history from experiment)
2. Provide only the transcript + dimension rubric
3. Score 1-10 with justification and evidence citations
4. Return structured result

This mirrors Petri's approach: the judge never participated in the experiment.

## Data Flow

```
Config (YAML)
     │
     ▼
Experiment Runner ──► Sandbox Agent SDK ──► Agent Sessions
     │                       │
     │                       ▼
     │                 Event Streams (SSE)
     │                       │
     ├───────────────────────┤
     │                       │
     ▼                       ▼
Runtime Guard          Event Collector
     │                       │
     ▼                       ▼
Intervention          Unified Transcript
(approve/reject)            │
                            ▼
                         Judge
                            │
                            ▼
                    Scores + Analysis
```

## Coordination Patterns

### Hub and Spoke

One central agent (orchestrator) delegates to workers:

```
        ┌─────────┐
        │  Hub    │
        │(Claude) │
        └────┬────┘
             │
    ┌────────┼────────┐
    ▼        ▼        ▼
┌──────┐ ┌──────┐ ┌──────┐
│Work 1│ │Work 2│ │Work 3│
└──────┘ └──────┘ └──────┘
```

**Pros**: Clear authority, easy to track
**Cons**: Single point of failure, bottleneck

### Peer Network

Agents coordinate as equals via shared state:

```
┌──────┐     ┌──────┐
│Agent1│◄───►│Agent2│
└──┬───┘     └───┬──┘
   │             │
   │  ┌──────┐   │
   └─►│Agent3│◄──┘
      └──────┘
```

**Pros**: Resilient, parallel work
**Cons**: Coordination overhead, potential chaos

### Pipeline

Sequential handoff between specialized agents:

```
┌──────┐    ┌──────┐    ┌──────┐
│Plan  │───►│Build │───►│Review│
└──────┘    └──────┘    └──────┘
```

**Pros**: Clear stages, quality gates
**Cons**: Bottlenecks, no parallelism

## Intervention Points

The Sandbox Agent SDK exposes two intervention mechanisms:

### Permission Approval

When an agent requests permission for an action, the orchestrator matches against rules:

```python
# In runtime_guard.py — rule matching and action
if event.type == "permission.requested":
    permission_id = event.data.get("permission_id")
    action = event.data.get("action", "")

    # Rules can approve, reject, escalate, or log
    await sdk.reply_permission(session_id, permission_id, "once")   # approve
    await sdk.reply_permission(session_id, permission_id, "deny")   # reject
    await sdk.reply_permission(session_id, permission_id, "always") # allow permanently
```

### Question Handling

When an agent asks a question, the orchestrator can answer or reject:

```python
if event.type == "question.requested":
    question_id = event.data.get("question_id")

    # Answer the question
    await sdk.reply_question(session_id, question_id, "Use JWT")

    # Or reject it (agent must proceed without answer)
    await sdk.reject_question(session_id, question_id)
```

### Inactivity Detection

The orchestrator tracks per-agent activity and nudges idle agents:

```yaml
# In pattern YAML
orchestrator:
  rules:
    - on: no_activity
      after: 120s
      then: nudge
      message: "Please continue with your task."
```

## Sandboxing

Agents run in isolated environments via:

- **Daytona**: Cloud sandboxes with git tracking
- **E2B**: Ephemeral compute sandboxes
- **Local**: OS-level sandboxing (Seatbelt/bubblewrap)

Sandboxing ensures:
- Agents can't affect real filesystem
- Network access is controlled
- Experiments are reproducible
