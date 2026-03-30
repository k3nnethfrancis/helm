# Topologies

Catalogue of multi-agent coordination topologies supported by Helm. Updated as experiments produce findings.

## Single

One agent, no coordination.

```
[ Solver ]
```

- **Agents**: 1
- **Communication**: None
- **Blocked tools**: Agent, TeamCreate, SendMessage
- **Purpose**: Baseline — what can one agent do alone?

**Findings:**
- Experiment 001: 8/8 tasks complete, 4/8 solved (50%) on SWE-bench Verified
- Clean behavioral profiles. No coordination overhead by definition.
- This is the bar every multi-agent topology has to clear.

## Centralized (Hub-and-Spoke)

One coordinator, all workers report to it. Workers cannot talk to each other.

```
      Worker A
        ↕
Worker B ↔ Coordinator ↔ Worker C
        ↕
      Worker D
```

- **Agents**: 2, 3, 5, 8
- **Communication**: Workers ↔ coordinator only
- **Blocked tools**: Agent, TeamCreate, SendMessage (all agents)
- **Purpose**: Test structured delegation and information aggregation

**Findings:**
- Experiment 001 v1 (filesystem): Coordinator systematically collapsed the topology — edited code directly, wrote fake worker status, closed prematurely. Structural compliance was 1.00 (tool blocking worked) but behavioral compliance was low.
- Experiment 001 v2 (messaging, heavy prompting): Coordinator followed rules but agents burned 30-50% of turns polling empty inboxes.
- Experiment 002 smoke (messaging, minimal prompts): Coordination works. 9 messages exchanged. Implementer polled inbox 26/90 items (29%). Hit turn limit before completion.
- Key finding: structural compliance ≠ behavioral compliance. Polling overhead is a real cost.

## Decentralized (Peer Network)

Everyone can talk to everyone. No designated coordinator.

```
Agent A ↔ Agent B
  ↕    ✕     ↕
Agent C ↔ Agent D
```

- **Agents**: 2, 3, 5, 8
- **Communication**: All ↔ all
- **Blocked tools**: Agent, TeamCreate, SendMessage
- **Purpose**: Test self-organization and emergent coordination

**Findings:**
- Not yet tested. Predicted risk: message duplication, no clear ownership of decisions, agents talking past each other.

## Hybrid (Hub + Lateral)

Coordinator manages the plan, but workers CAN share findings with each other directly.

```
      Worker A ← → Worker B
        ↕               ↕
        Coordinator
        ↕               ↕
      Worker C ← → Worker D
```

- **Agents**: 2, 3, 5, 8
- **Communication**: Hub ↔ workers + workers ↔ workers
- **Blocked tools**: Agent, TeamCreate, SendMessage
- **Purpose**: Test whether lateral sharing reduces coordinator bottleneck

**Findings:**
- Not yet tested. Predicted benefit: researchers can share findings directly with implementer without coordinator relay. Predicted risk: coordinator loses visibility into lateral exchanges.

## Independent (Parallel Candidates)

Multiple agents solve independently, a selector picks the best solution.

```
Candidate A →
Candidate B →  Selector
Candidate C →
```

- **Agents**: 2, 3, 5, 8
- **Communication**: Candidates → selector only (one direction)
- **Blocked tools**: Agent, TeamCreate, SendMessage
- **Purpose**: Test whether diversity of attempts beats single-agent depth

**Findings:**
- Not yet tested. Interesting for tasks where the problem has multiple valid approaches. Selector agent evaluates and picks best.

## Delegating

Single agent that can spawn subagents at runtime. Decides its own decomposition strategy.

```
Delegator
  ├── spawn → Worker A
  ├── spawn → Worker B
  └── spawn → Worker C (maybe)
```

- **Agents**: 1 initially, grows at runtime
- **Communication**: Parent ↔ children
- **Blocked tools**: TeamCreate, SendMessage (but Agent tool is ALLOWED for hub)
- **Purpose**: Test harness-native delegation — agent uses Claude's built-in subagent tool

**Findings:**
- Not yet tested. This is the closest to how Claude Code works in practice — one agent deciding when and how to delegate. The key question: does agent-controlled decomposition outperform experimenter-controlled topology?

## Coordination Mechanisms

Orthogonal to topology — how agents actually communicate:

| Mechanism | How it works | Trace visibility |
|-----------|-------------|-----------------|
| **Messaging (MCP)** | Agents use `send_message` / `check_inbox` tools. Broker routes messages. | Full — every tool call traced in NDJSON |
| **Filesystem** | Agents read/write files in `coordination/`. | Full — every Read/Write/Edit traced |
| **Shared log** | All agents read and append to one file. | Full — every Read/Edit traced |

The mechanism is an experimental variable, not a design decision. Same topology can use different mechanisms to measure the effect.

## Open Questions

- Does any multi-agent topology beat single-agent on bounded coding tasks?
- How much coordination overhead is acceptable before the parallelism benefit is lost?
- Does mechanical enforcement (tool blocking, broker rules) change outcomes vs prompt-only?
- Which coordination mechanism (messaging vs filesystem vs shared log) produces less overhead?
- Does agent-controlled decomposition (delegating) outperform experimenter-controlled (centralized)?

---

Updated: 2026-03-30
