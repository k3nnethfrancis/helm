# Helm — Open Questions

**Status**: Working draft
**Last updated**: 2026-02-28

These are unresolved design questions surfaced during a deep review of the Helm codebase, organized by theme. Section 0 captures the research framing that governs everything else.

---

## 0. Research Framing

### The core question

**Can we improve humans' visibility, control, and steerability of multi-agent AI systems?**

This decomposes into two research questions:

**RQ1 (Evaluation):** Can we measure visibility/control/steerability in a way that differentiates models and orchestration strategies? This means evaluating:
- Different **single-model swarms** (all-Claude vs. all-Codex vs. all-Qwen) on the seven dimensions
- Different **orchestration strategies** (hub-spoke vs. peer, different rule sets) on the seven dimensions
- Both simultaneously — model × topology interactions

**Key constraint**: We are studying single-model swarms, not heterogeneous multi-model systems. The same model plays orchestrator and subagent. This is both a simplification and a deliberate choice — most real-world agent systems use one model throughout.

If different models and strategies produce meaningfully different scores, the dimensions are valid instruments and this is a contribution on its own.

RQ1 also resolves the attribution question empirically: dimensions that move with orchestration strategy changes are orchestrator-attributable; dimensions that move with model changes are agent-attributable; both → system-level.

**RQ2 (Training):** Can we train models that improve these metrics? Two sub-questions:

**RQ2a — Orchestration policy:** Train a model that performs better in multi-agent coordination — as both orchestrator and subagent. Since the same model occupies all roles in the swarm, all seven dimensions are valid training signals (not just orchestrator-attributable ones). Evidence = run Helm with a swarm of the trained model, compare dimension scores before/after training.

**RQ2b — Behavioral monitor:** Train a small model to detect when systems misbehave according to these dimensions in real-time. This is a **weak-to-strong supervision** claim — can a smaller, cheaper model supervise larger, more capable agents? Input is the event stream during a run. Output is dimension-level alerts. Training signal comes from judge labels on completed runs.

### Implications for Helm

- The evaluation and training objectives are **sequential, not competing**. Measurement is prerequisite to training. Training is an experiment within the research program.
- The trained models are **evidence**, not products. "We measured deficits, trained on the signals, and here's what changed."
- Helm needs to support running the **same experiment with different single-model swarms** (RQ1 compares models). This is already possible by changing the harness in YAML — no architectural change needed.
- Helm needs to support **real-time event stream access** for the monitor model (RQ2b). Currently events flow through the collector but aren't exposed as a consumable stream for an external observer.
- The seven dimensions serve triple duty: research instrument (RQ1), training signal (RQ2a), and supervision target (RQ2b). Their validity is load-bearing.

---

## 1. Measurement Validity

### 1.1 Judge scale design

LLM judges are unreliable on continuous 1-10 scales. They anchor, compress to the middle, and produce inconsistent scores across runs. The GLM-5 multi-judge work already addressed this with panel consensus, but the underlying scale problem remains.

**Options:**
- Switch to discrete categories (none / minor / moderate / severe)
- Keep 1-10 for backward compatibility but bin into categories for analysis
- Per-dimension scales (some dimensions may warrant finer grain than others)

**Question**: What's the right granularity per dimension? Are all seven dimensions best served by the same scale type?

**Implication for RQ2b**: The behavioral monitor naturally outputs discrete classifications ("is goal drift happening?"), not continuous scores. If the judge also outputs discrete categories, the monitor's training labels are directly compatible. If the judge outputs 1-10, we need a binning step that introduces arbitrary thresholds.

### 1.2 Should judge scores feed into training?

Currently the composite reward uses only deterministic signals (task pass/fail, parallelism efficiency, coordination overhead). LLM judge dimension scores are analysis-only — they don't enter the RL reward function.

**Arguments for coupling:**
- Behavioral dimensions capture things deterministic metrics miss (goal drift, failure suppression)
- The dimensions are the core research contribution — if they don't shape training, what are they for?

**Arguments against coupling:**
- LLM judge scores are noisy; injecting noise into reward degrades training
- Judge evaluates after the fact on the full transcript; reward needs to be attributable to decisions
- Deterministic metrics are reproducible; judge scores are not

**Resolution direction**: Judge scores probably shouldn't directly enter the RL reward for the orchestration policy (RQ2a). But they are the **primary** training signal for the behavioral monitor (RQ2b). Different models, different roles for the judge.

### 1.3 Orchestrator vs. agent attribution — largely resolved

Some behavioral dimensions may measure agent properties, not orchestration properties:
- **Goal drift** — is this the orchestrator failing to maintain alignment, or the agent losing focus?
- **Failure suppression** — is this the orchestrator failing to detect errors, or the agent hiding them?
- **Context degradation** — is this an orchestration handoff problem, or an agent memory problem?

**Largely resolved**: Since we're training single-model swarms (same model as orchestrator and subagent), the attribution distinction matters less for training. All seven dimensions are valid training signals — improving the model on any dimension improves the whole swarm. The attribution question becomes an empirical one answered by RQ1: vary topology (holding model constant) to see orchestration-attributable dimensions, vary model (holding topology constant) to see agent-attributable dimensions.

**Still relevant for**: The behavioral monitor (RQ2b), which needs to know *what kind* of problem it's detecting to give useful alerts to the human.

---

## 2. Experimental Flexibility

### 2.1 Coordination protocol is over-prescribed

Three layers lock in the coordination protocol:
1. **YAML `coordination.paths`** — defines directory structure
2. **Agent system prompts** — prescribe exactly how to use those directories (per-agent, per-pattern)
3. **Backend `_classify_file`** — hardcoded Python mapping paths → message types → routing

This means you can't easily:
- Study emergent coordination (agents figure out their own protocol)
- Compare coordination protocols (different routing rules on the same task)
- Add novel coordination mechanisms (voting, blackboards, gossip) without code changes

**Options:**
- Add a generic broadcast backend (any new file → nudge all agents). Simple, enables emergent experiments.
- Make classification configurable via YAML route rules
- Separate nudge delivery from message classification (always nudge, classify for analysis only)
- Do nothing — prescriptive protocol is a controlled experimental parameter, not a limitation

**Question**: Is Helm studying "coordination within a protocol" or "coordination protocols themselves"? The answer determines whether this matters now or later.

### 2.2 RuntimeGuard rule engine is limited

- First-match-wins: only one rule fires per event. No composition.
- Rule ordering matters silently — reordering rules changes behavior with no warning.
- Only one inactivity rule supported (breaks after first `no_activity` match).
- `if_condition` only supports `action contains "X"` syntax.

Fine for current experiments, but if we want richer intervention strategies (e.g., "approve file writes but log network access for the same permission event"), the engine can't express it.

**Question**: Is this a real limitation given planned experiments, or theoretical? What intervention strategies do we actually need?

### 2.3 Reward formula is hardcoded

`compute_composite_reward` uses fixed weights: 0.7 task score, 0.2 parallelism, 0.1 efficiency. Can't tune per-benchmark or per-experiment without code changes.

**Options:**
- Move weights into YAML config
- Make the formula pluggable (named reward strategies)
- Keep it hardcoded but document the rationale

**Question**: Do different benchmarks / topologies / research questions need different reward weightings? If so, this needs to be configurable before we run more training.

### 2.4 Completion verification is a placeholder

`mode: completion` just checks "did the run end cleanly?" — not "did the agent solve the problem." Real benchmark scoring requires:
- SWE-bench: run the test suite (command mode with native harness)
- tau-bench: run the evaluation script
- Custom tasks: define what "success" means per-experiment

Currently the only alternative is `mode: command` with a user-provided script, but no benchmark-native verifiers are bundled.

**Question**: What's the priority here? Is the training pipeline useful without real task verification, or is this blocking?

### 2.5 Cross-model experiment support

RQ1 requires comparing different single-model swarms on the same task. Helm already supports this — change the `harness` field in YAML to run all agents on a different model. No mixed-model experiments needed (single-model swarms only).

**Remaining gap**: System prompt templates may need adaptation per-model. A `claude-code` prompt might not work optimally for `codex` or `opencode`. May need a prompt adaptation layer or per-harness prompt variants.

**Question**: How much do system prompt differences across harnesses confound the model comparison? Is this a significant threat to RQ1 validity, or can we control for it by using minimal/generic prompts?

---

## 3. Strategic

### 3.1 Research vs. training — resolved

~~Helm serves two purposes that pull in different directions.~~

**Resolved**: The evaluation and training objectives are sequential, not competing. Measurement (RQ1) is prerequisite to training (RQ2). Training is an experiment within the research program. The trained models are evidence, not products. See §0.

### 3.2 What the trained models do — clarified

Two models, not one:

| | Orchestration Policy (RQ2a) | Behavioral Monitor (RQ2b) |
|---|---|---|
| **What it does** | Predicts optimal orchestration decisions | Detects behavioral dimension violations |
| **When it runs** | Before/during a run | During a run (real-time) |
| **Input** | Task description + context | Event stream (sliding window) |
| **Output** | Categorical policy labels (7 tags) | Dimension alerts (per-dimension classification) |
| **Training signal** | Deterministic orchestration metrics | Judge dimension scores from completed runs |
| **Model size** | Needs capability (makes decisions) | Can be small (weak-to-strong supervision) |
| **Deployment** | Configures/augments RuntimeGuard | Separate observer feeding human dashboard |
| **Evidence claim** | "RL on orchestration signals improves behavior" | "Small models can supervise large agent swarms" |

**Open question**: How does the orchestration policy model close the loop back into Helm? Options:
- It configures RuntimeGuard rules before a run (prescriptive)
- It replaces the rule engine with learned decisions (active)
- It runs alongside and its predictions are logged + compared to what actually happened (analytical, then graduated to active)

### 3.3 Discrete classes in RL

Switching judge output to discrete categories improves measurement reliability but creates coarse reward signal. RL benefits from gradient — categorical rewards create stepped reward surfaces.

**Mitigations:**
- Large batch sizes smooth over coarseness (reward distribution across many rollouts matters, not individual gradient)
- Deterministic metrics provide continuous interpolation within categorical bands
- The orchestration policy environment already uses discrete match — and it works (when format compliance is solved)

**Question**: Is this actually a problem in practice, or a theoretical concern? The current flat-reward blocker is about format compliance, not reward granularity.

---

## Priority Ranking (revised)

| # | Question | Blocks what? | Urgency |
|---|---|---|---|
| 1.1 | Judge scale design | Monitor training labels, measurement validity | High — discrete categories needed for RQ2b compatibility |
| 2.3 | Reward formula hardcoded | Training flexibility | Medium — matters as soon as we run more benchmarks |
| 2.4 | Completion verification | Benchmark validity | Medium — blocking for real SWE-bench |
| 2.1 | Coordination over-prescribed | Experimental design | Medium — needed for topology comparison in RQ1 |
| 2.5 | Cross-model prompt confounds | RQ1 validity | Medium — need to control for prompt differences |
| 1.3 | Attribution | Empirical, not blocking | Low — resolved by RQ1 experimental design |
| 1.2 | Judge in training loop? | Architecture decision | Low — resolved: judge feeds RQ2b, not RQ2a |
| 2.2 | RuntimeGuard limitations | Complex experiments | Low — current rule sets work |
| 3.3 | Discrete RL reward | Training quality | Low — theoretical for now |

---

-- Shoshin | 2026-02-28
