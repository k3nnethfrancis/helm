# Helm — Open Questions

**Status**: Working draft
**Last updated**: 2026-03-11

These are the open questions that still matter after the recent benchmark and harness cleanup. The current center of gravity is reward validation before RL, so this file is organized around what still blocks that.

---

## 0. Current Center of Gravity

Helm's intended reward target is:

**benchmark performance + behavioral dimensions + selected trace-derived signals**

The open issue is not whether behavioral dimensions matter. It is whether the current dimensions are valid enough to shape optimization.

That makes the near-term question:

**Which current and candidate signals are stable, discriminative, and robust enough to promote from analysis into training?**

---

## 1. Reward Validation

### 1.1 Judge repeatability

The five active dimensions are judged with an LLM:
- `goal-drift`
- `context-degradation`
- `failure-suppression`
- `escalation-calibration`
- `resource-waste`

We have not yet established how stable those labels are when judging the same rollout repeatedly.

**Question**: Which dimensions are repeatable enough to trust, and which need rubric revision before they become reward terms?

### 1.2 Sensitivity to orchestration conditions

The dimensions are only useful if they move when orchestration conditions change.

We now have enough benchmark and non-benchmark traces to ask this properly, especially with Claude Code as the main harness.

**Question**: Do the dimensions separate single, hub-spoke, and peer conditions on coordination-relevant tasks, or do they mostly move with transcript style and noise?

### 1.3 Within-condition variance

Even if the dimensions separate topologies on average, they may still be too noisy run-to-run to support training.

**Question**: Is within-condition variance low enough that run rankings do not flip across ordinary reruns?

### 1.4 Missing-signal discovery

Recent runs exposed pathologies that may matter for reward design but are not clearly covered by the five active dimensions:
- closure failure after useful work
- weak verification discipline
- regression-heavy near-solves
- poor uptake of durable coordination artifacts

**Question**: Which of these should become future dimensions, which should remain deterministic metrics, and which belong in benchmark-specific verifier logic?

### 1.5 Reward composition

The current export reward is still a deterministic placeholder:
- task score
- parallelism
- efficiency / overhead terms

That is useful for pipeline plumbing, but it is not the intended long-term reward.

**Question**: Which reward mixtures remain stable under small weight changes and do not promote pathological runs?

---

## 2. Experimental Design

### 2.1 Slice quality

Some SWE-bench samples are good plumbing checks but bad orchestration experiments. The first cross-harness slice proved execution/export readiness but did not separate configurations meaningfully.

**Question**: Which task features best predict that a benchmark example is coordination-relevant rather than just a single-agent coding task with extra overhead?

### 2.2 Prompt and harness confounds

Claude Code is the main near-term path because it is the cheapest high-volume route for us, but prompt style and transcript style can still confound interpretation.

**Question**: How much of the judged signal is about swarm behavior versus harness-specific discourse style?

### 2.3 DirectCLI live intervention

True mid-run live intervention still does not exist on the DirectCLI path. That means current experiments mostly study coordination without live steering.

**Question**: Is that limitation acceptable for the reward-validation phase, or do we need a richer live-message capability before we can claim to be studying active orchestration?

---

## 3. Training Readiness

### 3.1 When do judge dimensions enter reward?

The answer is no longer "never" and not yet "now."

**Question**: What empirical gates should dimensions clear before they stop being analysis labels and start being reward terms?

Current proposed gates:
- repeatability
- topology sensitivity
- acceptable within-condition variance
- reward robustness
- missing-signal audit

### 3.2 What is the first training target?

Even after reward validation, Helm still has to choose between:
- orchestrator-policy selection
- orchestrator fine-tuning
- participant fine-tuning
- rollout-level offline RL

**Question**: Which target gives the cleanest scientific claim for the first optimization experiment?

### 3.3 Canonical training unit

Helm can export:
- per-agent traces
- swarm-level rollouts
- orchestration-oriented rows

**Question**: Which of these should be the canonical unit for the first reward-coupled training pilot?

---

## 4. Future Dimensions

### 4.1 Monitoring evasion

Still important, but not yet instrumented.

**Question**: What is the cleanest experimental design for measuring whether swarm behavior changes under observation without collapsing into prompt artifacts?

### 4.2 Human model accuracy

Also still important, but not yet operationalized.

**Question**: How do we measure whether the swarm actually understands human intent rather than merely complying with the literal task text?

---

## Priority Ranking

| # | Question | Why it matters now | Urgency |
|---|---|---|---|
| 1.1 | Judge repeatability | Noisy labels should not enter reward | High |
| 1.2 | Sensitivity to orchestration conditions | Reward terms must differentiate real conditions | High |
| 1.4 | Missing-signal discovery | Avoid optimizing around obvious ontology gaps | High |
| 1.5 | Reward composition | RL needs a robust objective, not a fragile guess | High |
| 2.1 | Slice quality | Bad slices waste tokens and produce weak evidence | High |
| 1.3 | Within-condition variance | Needed to know whether rankings are stable | Medium |
| 2.2 | Prompt and harness confounds | Important, but Claude-first focus can defer breadth | Medium |
| 3.2 | First training target | Important after reward validation, not before | Medium |
| 2.3 | DirectCLI live intervention | Important, but not blocking reward validation | Low |
| 4.1 | Monitoring evasion | Future work | Low |
| 4.2 | Human model accuracy | Future work | Low |

---

-- Shoshin | 2026-03-11
