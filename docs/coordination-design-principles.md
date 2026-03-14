# Coordination Design Principles

**Status**: Working design note  
**Last updated**: 2026-03-07

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

## Current Position

Helm should currently be treated as:
- a runtime that exposes coordination channels
- a logger that preserves evidence about their use
- an evaluator that studies the consequences

Not:
- a hidden coordination-policy engine

## Planned Code Changes (Do Not Execute Yet)

1. Make the capability/policy boundary explicit in docs and comments.
2. Ensure coordination backends do not inject strategy text by default.
3. Add schema support to record coordination channel type and usage more explicitly.
4. Review YAML patterns so coordination guidance lives there, not in backend code.
5. Add evaluation fields that distinguish:
   - persistent artifact creation
   - ephemeral message attempts
   - ephemeral delivery success
   - evidence of downstream uptake
6. Only after that, consider adding richer live-message channels as optional capabilities.

---

-- Shoshin | 2026-03-07
