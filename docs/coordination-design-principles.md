# Coordination Design Principles

**Status**: Active design note
**Last updated**: 2026-03-28

## Core Principle

Helm should expose coordination **capabilities** and preserve coordination **evidence**, but it should not silently impose coordination **policy** through backend defaults.

If a coordination strategy matters, it should appear in the experiment condition:
- YAML config
- agent prompt
- task framing
- evaluation rubric

Not in hidden runtime behavior.

This matters because Helm is a research and training environment. If the runtime quietly forces a strategy, then the resulting traces stop reflecting the model-orchestrator system we are trying to study.

## Capability vs Policy vs Enforcement

### Capabilities

Capabilities are channels or affordances Helm makes available:
- shared filesystem artifacts
- persistent coordination state
- direct follow-up messages to running sessions, when the harness supports them
- runtime guard interventions
- task verifiers and judges

Capabilities belong in the runtime because they define what the environment makes possible.

### Policy

Policy is how agents are instructed or expected to use those capabilities:
- poll `coordination/messages/` after every major step
- wait for research before implementing
- write decisions to a persistent file before acting
- prefer direct messages for urgent coordination

Policy belongs in:
- YAML patterns
- prompts
- task conditions
- explicit experimental variants

Policy should be visible, intentional, and part of the condition under study.

### Enforcement

Enforcement is where Helm hard-constrains behavior:
- turn limits
- permission rejections
- blocked commands
- process termination

Enforcement should be used sparingly and treated as an experimental variable, because it changes behavior by construction.

## Persistent vs Ephemeral Coordination

Helm should support both persistent and ephemeral coordination because they have different research value.

### Persistent channels

Examples:
- files in `coordination/`
- state files
- review artifacts
- written plans and assignments

Properties:
- durable across long runs
- inspectable after the fact
- robust to context loss
- useful for auditability and training

Persistent channels are good for:
- handoffs
- shared memory
- coordination state
- artifacts that multiple agents may need later

### Ephemeral channels

Examples:
- direct follow-up messages to a running agent session
- transient context injected into a live conversation

Properties:
- fast
- local to the active session
- can be lost as context evolves
- may not survive long trajectories

Ephemeral channels are good for:
- urgent redirects
- quick clarifications
- lightweight steering

### What Helm should study

A core research question is not just whether agents coordinate, but **when they choose persistence versus ephemerality**.

That is a meaningful behavioral decision:
- Do they externalize important state?
- Do they overuse transient messages?
- Do they fail because they kept critical information only in context?
- Do they waste time persisting everything?

Helm should log and evaluate that choice rather than deciding it for them.

## Design Implications

### Runtime

The runtime should:
- expose available coordination channels
- log their use faithfully
- distinguish channel existence from channel consumption
- avoid injecting hidden coordination norms

The runtime should not:
- silently require polling
- silently prioritize one channel over another
- rewrite the agent’s coordination strategy at execution time

### YAML / Prompt Layer

Patterns may describe coordination protocols such as:
- hub-spoke task assignment
- peer review loops
- file-first coordination
- mixed persistent + direct-message protocols

That is the right place to encode behavioral expectations, because:
- it is visible
- versioned
- comparable across runs
- trainable as part of the explicit condition

### Evaluation

Evaluation should measure:
- which channels were available
- which channels were actually used
- when persistence helped or hurt
- when direct messages helped or hurt
- where coordination failed because information was not externalized

This suggests coordination metrics should separate:
- artifacts observed
- live messages attempted
- live messages delivered
- downstream evidence that another agent actually acted on the information

## Training Implications

For training, hidden runtime policy is especially dangerous.

If Helm forces behavior in the backend:
- the traces no longer reflect the model’s own coordination choices
- policies become partially unlearnable because they are injected out-of-band
- we risk training on artifacts of the lab rather than on grounded agent behavior

If Helm keeps policy in the explicit experiment condition:
- traces remain interpretable
- policy variants can be compared honestly
- training data reflects visible environment structure

That is closer to reality and better for generalization.

## Current Position (2026-03-28)

Helm is config-driven. The YAML config declares experimental conditions (topology, communication channel, enforcement level, delivery mechanism). Helm executes faithfully. The researcher decides what to enforce mechanically vs leave to prompting.

### What's implemented

**Coordination mechanisms (config-driven):**
- `mechanism: filesystem` — agents coordinate through shared files in `coordination/`. Backend polls for new files and delivers nudges (when harness supports follow-up messages).
- `mechanism: messaging` — agents get MCP tools (`helm_send_message`, `helm_check_inbox`, `helm_list_peers`, `helm_signal_done`) via a Helm broker. Messages route through an HTTP broker running in a background thread.

**Config fields:**
```yaml
coordination:
  mechanism: messaging   # filesystem | messaging
  delivery: poll         # poll | push (push not yet available)
  enforcement: prompt-only  # prompt-only | mechanical
```

**Topology enforcement:**
- `--disallowedTools` mechanically blocks native Agent/TeamCreate/SendMessage (structural compliance)
- Broker optionally rejects messages that violate `can_message` rules when `enforcement: mechanical`
- Prompt-level constraints (coordinator shouldn't edit code, must wait for reviewer) are NOT mechanically enforced

**Prompt injection:**
- The framework auto-injects coordination instructions based on `mechanism` (which tools to use, how to check messages)
- Agent system prompts focus on role and task constraints, not coordination plumbing

### Empirical findings

From Experiment 001 (2026-03-27/28):
- **Dual-channel coordination creates ambiguity agents exploit.** When both filesystem and messaging are available, coordinators wrote fake status files, edited code directly, and closed prematurely.
- **Single-channel is cleaner.** Messaging-only forced proper delegation.
- **Structural compliance ≠ behavioral compliance.** Coordinators follow tool restrictions (1.00 compliance) while still collapsing the topology by doing all work themselves.
- **Polling-based messaging wastes turns.** Without push delivery, agents burn 30-50% of turns checking empty inboxes.

### What's not yet implemented
- **Filesystem write permissions per agent**: Would prevent coordinator from writing to worker status directories.
- **Message authentication/signing**: Inter-agent messages are plaintext — no integrity checking.

### Recently implemented (2026-03-29)
- **Push delivery** (`delivery: push`): Implemented via `TmuxCLIClient` — persistent interactive claude sessions in tmux panes, messages injected via `tmux paste-buffer`. Alternative: `ResumableCLIClient` using `claude -p --resume UUID`. MCP channel notifications still don't work in `claude -p` mode, but tmux bypasses this entirely.
- **Agent spawn via MCP** (`helm_spawn_agent`): Coordinator can dynamically spawn new claude sessions in tmux. Spawned agents get messaging but not spawn capability.
- **Per-agent capability controls**: `HELM_CAN_SPAWN`, `HELM_CAN_SIGNAL_DONE` env vars. MCP server dynamically filters tool list — agents never see tools they can't use.

## Design Implications (unchanged)

The principles from the original document remain correct:
- Runtime exposes capabilities, doesn't impose policy
- Policy belongs in YAML/prompts, visible and versioned
- Enforcement is an experimental variable, used sparingly
- Training data should reflect visible environment structure

---

-- Shoshin | 2026-03-28
