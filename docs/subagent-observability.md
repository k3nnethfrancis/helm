# Subagent Observability: Conversation Window Polling

**Status**: Design proposal
**Created**: 2026-03-28
**Context**: Rogue agent experiment findings + production multi-agent observability gap

---

## Problem

In Helm's current coordination model, agents are isolated processes that communicate through the filesystem protocol (`helm-agent send`, `coordination/` directories). The orchestrator/coordinator can only see what a subagent *chooses to externalize* — messages it sends and files it writes.

This creates a blind spot: the coordinator has no way to observe what a subagent is actually *doing* between messages. It can't distinguish between a subagent that's been silently investigating for 5 minutes and one that's been stuck, crashed, or — in the adversarial case — crafting manipulation messages.

This matters because it doesn't match how real multi-agent systems work in practice, and it limits the coordinator's ability to make informed decisions.

## How Real Systems Work

In Claude Code's native subagent system (`Agent` tool):
- The parent sends a task prompt to the subagent
- The subagent runs autonomously (makes tool calls, reads files, reasons internally)
- The parent **does not** see the subagent's system prompt or internal thinking
- The parent **does not** see the subagent's intermediate tool calls as they happen
- The parent **can** observe the subagent's conversation messages (what it said and what it received)
- When the subagent completes, the parent gets a result summary

The key insight: the parent can "look over the subagent's shoulder" at its conversation history — seeing messages in and out — but cannot read its mind (system prompt, thinking tokens). This is the natural observability level for orchestrator → subagent relationships.

## Proposed Design

Add two capabilities to the `helm-agent` CLI that let any agent observe another agent's conversation window:

### 1. `helm-agent watch --agent <agent_id> [--last N]`

Returns the last N conversation turns (default: 10) for the specified agent. Each turn shows:
- **Role**: user / assistant
- **Content**: the message text (what the agent said or received)
- **Timestamp**: when this turn happened
- **Tool calls**: which tools were invoked (name + description only, not full arguments/results)

What is **included**:
- User messages (task prompts, nudges, coordination messages delivered to the agent)
- Assistant messages (what the agent said in response)
- Tool call names and descriptions (e.g., "Read: /workspace/repo/src/module.py")

What is **excluded**:
- System prompt (the agent's private instructions)
- Thinking tokens / internal reasoning (the agent's chain of thought)
- Full tool call arguments and results (too verbose, and would leak file contents)
- Any content the agent hasn't yet externalized

This matches the information available in a real Claude Code subagent context — you can see the conversation, but not the system prompt or thinking.

### 2. `helm-agent status --agent <agent_id>`

This already exists. It should continue to return:
- Whether the agent is running, idle, or completed
- Turn count
- Last activity timestamp

No changes needed here — just documenting that it's the complement to `watch`.

## Why This Matters

### For coordination quality

A coordinator that can poll subagent progress makes better decisions:
- "researcher_a is on turn 15 and still reading files — they might be stuck, let me check in"
- "the implementer already started editing code — the research phase is informally complete"
- "researcher_b sent me confident findings but their conversation shows they only read 2 files — I should verify independently"

That last case is exactly the detection opportunity that matters for adversarial robustness. If a rogue agent claims "I've thoroughly investigated and the fix is trivial" but their conversation window shows minimal actual investigation, the coordinator has signal to distrust the claim.

### For the rogue agent experiment

The current experiment tests whether agents resist social engineering delivered through coordination messages. Adding `watch` creates a second detection path: even if the manipulation messages *sound* convincing, the coordinator can cross-check them against the rogue agent's actual activity.

This introduces a testable hypothesis: **coordinators with observability into subagent conversation windows will be more resistant to rogue agent manipulation than coordinators who only see coordination messages.**

We can test this as an experimental condition:
- **Condition A**: coordinator has `send` + `inbox` only (current)
- **Condition B**: coordinator has `send` + `inbox` + `watch` (proposed)

### For ecological validity

Production multi-agent systems will have varying levels of observability. Some will run subagents as black boxes (API calls with results). Others will have full trace access. The interesting research question is how observability level affects coordination quality and adversarial resilience. `watch` gives us the dial to test this.

## Implementation Notes

### Data source

Each agent's conversation is already captured by the DirectCLI adapter as an NDJSON stream of events. The `watch` command would read from this stream (or a derived conversation log) and filter to show only user/assistant message events.

The conversation data is already being collected — this is purely a read path, not new instrumentation.

### Topology enforcement

`watch` access should follow topology rules:
- In **centralized** topologies: the hub can watch any worker. Workers cannot watch each other or the hub.
- In **decentralized** topologies: any peer can watch any other peer (they're equals).
- In **hybrid** topologies: hub can watch all; workers can watch peers in their lateral group.

This should be enforced in `helm-agent` the same way `send` routing is enforced — via the `.helm-config.json` that the experiment setup writes.

### Performance

`watch` should be lightweight — it reads from a local file, not a network call. The agent's conversation log is on the same filesystem. The `--last N` parameter bounds the output so it doesn't dump thousands of turns.

### Privacy boundary

The system prompt exclusion is a deliberate design choice, not a limitation. In a real deployment, the subagent's system prompt is its private configuration — the orchestrator configured it (or someone did) but other agents shouldn't be able to read it at runtime. This matches the principle from the coordination design doc: capabilities in the runtime, policy in the prompt.

## Relationship to Existing Infrastructure

| Component | Already exists? | Change needed |
|---|---|---|
| Per-agent conversation logging | Yes (DirectCLI adapter, NDJSON stream) | None — data is already there |
| `helm-agent status` | Yes | None |
| `helm-agent watch` | No | New command — read from conversation log |
| Topology-aware routing for `watch` | No | Extend `.helm-config.json` with `can_watch` rules |
| Transcript viewer (post-hoc) | Yes (`transcripts/full.md`) | None — this is the post-hoc equivalent |

## Non-Goals

- **Real-time streaming**: `watch` is a polling command (pull), not a live stream (push). The agent calls it when it wants to check, same as `inbox`.
- **Intervention**: `watch` is read-only. The coordinator can observe but not modify the subagent's conversation.
- **Full trace access**: We deliberately exclude system prompts, thinking, and full tool results. If full trace access is needed for a specific experiment, that's a different capability with different trust implications.

---

*This proposal originated from the rogue agent experiment (experiments/rogue-agent/), where we discovered that the coordinator's inability to observe subagent activity limits both coordination quality and adversarial detection. The design follows Helm's coordination principles: expose the capability, let the experiment condition decide the policy.*
