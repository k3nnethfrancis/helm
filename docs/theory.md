# Helm: Theoretical Foundations

Running log of theoretical reasoning underpinning Helm's systems design. Updated during research discussions. Companion to `progress-ledger.md` (implementation progress) — this file tracks the *reasoning* that drives design decisions.

---

## Working Thesis

Helm is a research environment for studying, evaluating, and iteratively improving computer-use orchestrators and swarms on real tasks.

It composes with benchmarks rather than replacing them. Existing benchmarks provide task difficulty and verification; Helm adds swarm policy, behavioral evaluation, trace collection, cross-harness comparison, and export paths for iterative alignment.

Helm does **not** assume we already know what "good coordination" is. The project is set up to discover, test, revise, and eventually optimize that definition. The canonical artifact is therefore a **swarm rollout**: task, policy, harness, full trace, verifier result, and behavioral scores.

### Architectural Principles

1. **Evaluation precedes optimization.** Reward signals and policy labels should be treated as hypotheses before they become training targets.
2. **The trace is the source of truth.** Summaries, metrics, tags, and datasets are all derived artifacts.
3. **The swarm rollout is the primary unit of analysis.** Per-agent traces are useful views, but the whole coordinated run is the main research object.
4. **Harness effects are first-class variables.** Execution substrates shape behavior and must be measured, not treated as neutral plumbing.
5. **Single-agent baselines remain mandatory.** If a simpler system achieves similar task performance with fewer coordination failures, that is a core scientific result.
6. **Control must be measured, not assumed.** Legibility, escalation, failure surfacing, and intervention response need explicit operationalization.

---

## The Control Problem in Multi-Agent Systems

### Core Thesis

As AI systems move from single-agent to multi-agent architectures, the alignment problem transforms from "make one model behave well" to "maintain human control over coordinated swarms of agents." Helm is infrastructure for studying and solving this.

The key insight: **humans cannot attend to swarms of agents at scale, but they can attend to a single orchestrator.** If the orchestrator is sufficiently aligned and controls the swarm, human oversight scales through the orchestrator rather than requiring attention to every agent. This is a requisite variety argument (Ashby, 1956) — you need a controller with enough complexity to manage the system, but you also need the control chain to remain legible to humans.

This is structurally identical to how organizations work. A CEO doesn't attend to every employee — they attend to a management layer that coordinates the work. The quality of the organization depends on the quality of that coordination layer. The same applies to agent swarms.

### Weak-to-Strong Iterative Alignment

The alignment problem is fundamentally an evolutionary process. As models improve, alignment techniques must keep pace. The practical strategy is **weak-to-strong alignment**: train a smaller, more controllable system to regulate a larger, more capable one (Burns et al., 2023; Anthropic constitutional AI work; OpenAI's weak-to-strong generalization research).

In the multi-agent context, this means:

1. **The orchestrator is the alignment surface.** Rather than aligning every agent individually, align the orchestrator. The orchestrator controls task decomposition, coordination protocol, escalation paths, and verification gates.

2. **The orchestrator can be smaller than the agents it controls.** A well-trained orchestration model doesn't need to be as capable as the agents at the task — it needs to be good at *organizing* them and *escalating* appropriately. This is the weak-to-strong claim: a weaker model can supervise stronger ones if its supervision domain (orchestration) is well-defined.

3. **Iterative improvement is the mechanism.** Run swarm → measure behavior (dimensions) + task performance (verifiers) → validate which signals are stable enough to trust → only then train orchestrator on a composite signal → deploy improved orchestrator → run again. Each cycle should produce an orchestrator that coordinates better and stays more controllable.

This is analogous to RLHF but at the coordination level — human preferences about *how agents should coordinate* become training signal.

### Why Orchestration Policy is Not Orthogonal

The orchestration policy system (run_data.py → orchestration_dataset.py → helm_orchestration_policy env) formalizes the orchestrator's decision space. The 7 policy tags — escalation_route, dominant_intervention, intervention_intensity, parallelism_target, coordination_style, verification_gate, human_gate_required — are an initial attempt to parameterize orchestration strategy.

The reasoning: if you can train a model to predict *what orchestration policy a task needs*, you have a model that understands the relationship between problem shape and swarm shape. This is the meta-learning claim — the orchestrator doesn't just execute a fixed policy, it selects policy based on task characteristics.

**Current limitation**: the 7 tags are a coarse approximation. They capture broad strategy (how much human oversight, how parallel, how heavy the coordination) but don't capture the full space of possible orchestration patterns. The current tag taxonomy was derived from what `run_data.json` can deterministically compute from traces, not from a theoretical analysis of what orchestration decisions matter.

### Swarm Shape as Function of Problem Shape

Given any agent swarm, how is it decided how to organize? Two mechanisms:

1. **Top-down (orchestrator-driven)**: A meta-agent pre-selects the coordination pattern based on task analysis. Fast, but limited by the orchestrator's generalization ability.

2. **Bottom-up (evolutionary/emergent)**: Agents with in-context learning adapt their coordination patterns through environmental feedback. Slower, but can discover novel patterns. This is analogous to evolutionary processes in biological coordination — ant colonies, bird flocking, distributed consensus.

Both mechanisms can be trained, and they're complementary:

- **In-context learning** is real but limited. Long-running agents with good feedback loops can improve coordination within a session (Bateson Level I learning — new responses in fixed context). But context windows constrain how much adaptation happens.

- **An orchestrator that pre-learns optimal patterns** skips the evolutionary search. If the orchestrator has seen enough task-topology pairings, it can generalize to new problem spaces — selecting the right coordination pattern without trial and error. This is Bateson Level II — learning to learn, changing the frame rather than adapting within it.

The ideal system combines both: an orchestrator that selects good initial patterns (fast) + agents that can adapt in-context when the initial pattern is suboptimal (resilient). The orchestrator provides the prior; in-context learning provides the update.

### Organizational Cybernetics Connection

Beer's Viable System Model (1972) describes organizations as recursive systems with five functions:

| VSM Function | Multi-Agent Equivalent |
|---|---|
| System 1 (Operations) | Worker agents executing tasks |
| System 2 (Coordination) | Coordination protocol (filesystem, messaging) |
| System 3 (Control) | Orchestrator / runtime guard |
| System 4 (Intelligence) | Orchestration policy — adapting strategy to environment |
| System 5 (Identity) | Human operator / alignment constraints |

Helm currently implements Systems 1-3 (agents, coordination, runtime guard). The orchestration policy env is an attempt at System 4. System 5 is what the seven behavioral dimensions measure — are the agents' behaviors consistent with human intent?

Ashby's Law of Requisite Variety states that a controller needs at least as many states as the system it controls. Applied to multi-agent AI:

- A simple rules-based orchestrator (current runtime guard) has low variety — it can reject dangerous commands but can't adapt coordination strategy.
- A trained orchestration policy model has higher variety — it can select strategies based on task characteristics.
- A human operator has the highest variety but lowest bandwidth — they can make any decision but can't attend to everything.

The design goal is to push as much variety as possible into the orchestration layer while keeping the human operator as the ultimate authority (System 5). This is the steerability thesis: **make the orchestrator capable enough to handle routine coordination decisions autonomously, while maintaining legible escalation paths for decisions that require human judgment.**

### The Evaluation Harness as Research Infrastructure

Helm's multi-harness design (Claude Code, Codex, OpenCode) is not just engineering convenience — it's methodologically necessary. Different harnesses impose different constraints on agent behavior (harness-model interaction effects can change agent success by 10x; see can.ac 2026). Running the same orchestration patterns across multiple harnesses lets us separate:

- **Harness effects**: constraints imposed by the tool
- **Model effects**: capabilities of the underlying model
- **Orchestration effects**: impact of the coordination pattern
- **Interaction effects**: combinations that are better/worse than expected

This factorial design is what makes the research interpretable. Without it, you can't attribute coordination quality to the orchestrator vs the harness vs the model.

### What This Means for Helm's Design

The immediate focus should be on **orchestrators and swarm behavior**, not on a separate monitor stack. The same experimental traces may eventually support participant training, orchestrator training, and monitoring work, but those are different downstream uses of the same lab.

In the near term, Helm should prioritize:

1. **Measurement validity**: do the behavioral dimensions and trace-derived metrics actually differentiate policies, topologies, and harnesses?
2. **Policy comparison**: which orchestration strategies improve task performance while preserving human steerability?
3. **Reward validation**: which current and candidate signals are repeatable, sensitive, and robust enough to promote into training?
4. **Iterative improvement**: once a signal is stable enough, can we use it to improve orchestrator policy selection or swarm behavior?

This keeps optimization downstream of empirical understanding.

---

## The Orchestrator IS the Harness (2026-03-07)

### Architectural Simplification

A key realization from discussion: the orchestrator is not a separate system sitting outside the agent harness. **The orchestrator IS the top-level agent.** Claude Code, Codex, or OpenCode starts up, reads its configuration (CLAUDE.md, agents.md, or equivalent), and that configuration contains the orchestration policy — what kind of swarm to spin up, how to coordinate, when to escalate.

This simplifies the architecture significantly:

**Current (over-engineered)**:
```
YAML config → Helm experiment runner → runtime guard → orchestration policy extraction → separate RL env
```

**Simplified**:
```
YAML policy → harness agent (orchestrator) → spawns sub-agents → traces → judge + verifier → reward
```

The YAML isn't just a config file for Helm. It's the **policy representation** — the data structure that captures the full decision space of orchestration: task decomposition, topology, coordination mechanism, agent roles, escalation rules, limits. The YAML is what we're ultimately trying to learn to generate or improve.

Two modes of policy origin:
- **Human-defined**: we write the YAML (current baseline experiments)
- **Agent-defined**: the orchestrator designs the swarm given a problem (future — the orchestrator generates or selects the YAML)

### Traces Are the Data

All the data we need is in the traces from the harness. The traces contain everything:
- What the orchestrator decided (task decomposition, agent spawning, coordination messages)
- How agents coordinated (filesystem writes, message passing, signal files)
- What tools were called and what happened
- What artifacts were produced
- Where things went wrong

We don't need a separate `run_data.py` orchestration policy extraction step as a core dependency. The trace IS the primary data. Deterministic metrics extracted from traces (turn counts, coordination message counts, time to completion, tool call patterns) are useful supplementary signals, but they're derived from the trace — not a separate data source.

### The Reward Signal

The intended training signal is a composite:

1. **Behavioral dimensions (LLM-as-judge)**: How well did the swarm coordinate? Did it maintain human controllability? These are the seven dimensions — goal drift, context degradation, failure suppression, escalation calibration, resource waste, monitoring evasion, human model accuracy.

2. **Task performance (verifier)**: Did the swarm solve the problem? Binary or graded, depending on the verifier (SWE-bench test suite gives binary pass/fail per test, partial credit across tests).

3. **Deterministic trace signals (optional)**: Cheap-to-compute metrics from traces that add gradient signal. Examples: coordination overhead ratio, turns-to-completion, escalation count, tool call efficiency. These don't replace the judge — they supplement it with high-frequency, zero-cost signals.

The intended composite reward is `f(behavioral_dimensions, task_performance, trace_signals)`. But that function is still a research object, not a settled implementation detail. The near-term job is to validate which behavioral dimensions and candidate trace signals are stable enough to enter it at all, and with what weighting.

### Implications for Current Infrastructure

What stays:
- **Harness adapters** (Claude, Codex, OpenCode) — the execution layer
- **Trace collection** — the data layer
- **Judge system** — behavioral dimension scoring
- **Verifier system** — task correctness checking
- **YAML patterns** — the policy representation
- **Benchmark CLI** — experiment management

What changes in priority:
- **Runtime guard**: currently a rule-based intervention engine. In the simplified model, intervention rules belong primarily in the orchestrator's configuration (CLAUDE.md / YAML policy), not in a separate Helm layer. The runtime guard becomes a safety net and an experimental variable, not the primary orchestration mechanism.
- **Orchestration policy env**: the current 7-tag single-turn env is a stepping stone. The real target is comparison and eventual optimization of orchestration policies over full rollouts. The env should eventually move toward "given this task and available harnesses, what swarm policy should you run?"
- **`run_data.py` orchestration extraction**: useful for analysis, dataset shaping, and derived metrics, but not the canonical data source. Deterministic metrics supplement traces; they do not replace them.

### From Rollout Perspective

From a training and evaluation perspective, the rollout for an orchestrator-as-agent looks like:

```
Input: problem description + benchmark or arbitrary task + available harnesses/models
Orchestrator action: generate/select YAML policy → configure swarm → manage execution
Output: full trace of orchestrator + all sub-agents
Evaluation: behavioral_dimensions(trace) + task_performance(verifier) + trace_signals
Optimization target: only after the evaluation signal is shown to be meaningful
```

This is one model doing the orchestration AND the sub-agent work — because that is how many real systems currently operate. Multi-model / multi-family systems are possible in the future, but the near-term scientific question is whether orchestration policy and swarm shape improve the performance/control frontier on benchmarked tasks.

Per-agent trace extraction still matters — especially for role-specific analysis and downstream participant learning — but the highest-leverage research object is the swarm rollout and the orchestrator decisions that shaped it.

---

## Open Theoretical Questions

### What is the right ontology for orchestration decisions?

The current 7 XML tags are a first approximation. A more principled approach would:
- Start from the space of decisions an orchestrator actually makes (task decomposition, agent assignment, coordination protocol selection, escalation thresholds, verification gates)
- Analyze which decisions most affect coordination quality and human controllability
- Design a tag/parameter space that captures these decisions at the right granularity

### Can orchestration policy generalize across task domains?

If we train on SWE-bench orchestration traces, does the policy generalize to different task types? This is the key scaling question. The hypothesis is that coordination patterns are partially task-invariant — some orchestration strategies work across domains (e.g., "escalate when confidence is low" is domain-general).

### What's the right training regime: single-turn or multi-turn?

The current env is single-turn (task description → policy tags). But real orchestration is multi-turn — the orchestrator makes decisions *throughout* the run, adapting to what's happening. The full training path requires multi-turn RL on orchestrator traces, which depends on Prime infrastructure.

### How do we evaluate orchestrator quality?

Agent quality is measured by task performance + behavioral dimensions. Orchestrator quality should be measured by *swarm* quality — how well do agents coordinate under this orchestrator's policy? This is a higher-order evaluation: the orchestrator's output is a policy, and the policy's quality is measured by the swarm's behavior under that policy.

---

## References

- Ashby, W. R. (1956). *An Introduction to Cybernetics*. Chapman & Hall.
- Bateson, G. (1972). *Steps to an Ecology of Mind*. University of Chicago Press.
- Beer, S. (1972). *Brain of the Firm*. Allen Lane.
- Burns, C., Ye, H., Klein, D., & Steinhardt, J. (2023). Weak-to-strong generalization: Eliciting strong capabilities with weak supervision. arXiv:2312.09390.
- Hagendorff, T., et al. (2023). Machine psychology: Investigating emergent capabilities and behavior in large language models using psychological methods. arXiv:2303.13988.
- Varela, F. J., & Maturana, H. R. (1987). *The Tree of Knowledge*. Shambhala.
- Wiener, N. (1948). *Cybernetics: Or Control and Communication in the Animal and the Machine*. MIT Press.

---

*Updated: 2026-03-11 — reward-validation sequencing clarified before RL*
