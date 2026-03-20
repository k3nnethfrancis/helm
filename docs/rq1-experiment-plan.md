# RQ1 Reward Validation Plan

**Research question**: Are Helm's current behavioral dimensions robust enough to join benchmark performance as training signals for orchestrators and swarms?

**Status**: Active
**Updated**: 2026-03-14

---

## Why This Comes Before RL

Helm's intended reward target is not benchmark score alone. It is benchmark performance plus behavioral dimensions that capture coordination quality and human steerability.

The immediate problem is not reward invention. It is reward validation.

Before RL or policy optimization, we need evidence that the current judged dimensions:
- are repeatable enough to trust
- actually separate better from worse swarm behavior
- add signal when benchmark score is flat or ambiguous
- do not reward pathological rollouts that merely sound good

The current judged dimensions are:
- `goal-drift`
- `context-degradation`
- `failure-suppression`
- `escalation-calibration`
- `resource-waste`

`monitoring-evasion` and `human-model-accuracy` remain future dimensions because they require dedicated experimental designs that are not yet implemented.

---

## Claude-First Strategy

The near-term program should use Claude Code as the primary execution and judging harness because:
- it is the cheapest high-volume path available to us right now
- it already has the deepest run history inside Helm
- it is the cleanest current baseline for small SWE-bench slices
- it lets us validate the reward ontology without spending the budget on cross-model breadth too early

Codex and other harnesses should remain secondary spot checks until the reward battery is stable on Claude-first conditions.

Current milestone state:
- the Claude-first reward-validation battery is complete enough to support a first reward recommendation
- the basic cross-harness topology baseline is now also complete on the validated SymPy pair:
  - Claude and Codex each have single / hub-spoke / peer coverage on the same tasks
  - the benchmark-flat / behavior-different result survives across both harnesses
- immediate next work should therefore emphasize:
  - short internal writeup synthesis
  - judge hardening before larger baselines or RL
  - a second internal note/report on judge hardening outcomes
  - only then broader `3 / 5 / 8` baseline expansion and RL handoff design

---

## Judge Hardening Gate

Before RL or broader matrix widening, Helm needs a focused judge-hardening pass. The current dimensions and reward recommendation are useful, but the judge path is still a research instrument under construction.

The gate questions are:
- Does the judge receive the right context from multi-agent transcripts, tool outputs, and coordination artifacts?
- Does transcript rendering preserve enough information to understand what actually happened in the swarm?
- Does long-context handling keep the most important evidence, or are we silently dropping the parts that matter?
- Are benchmark verifier outcomes, closure state, and warnings surfaced consistently enough for the judge to reason over them?
- Is the judging process repeatable and auditable enough for future training use?
- Would Inspect- or Petri-style structured auditability and seeded reproducibility improve the current path?

Current implementation state:
- the multi-view hierarchical judge is now implemented and is the default `helm judge` path
- legacy merged-transcript judging remains available only as explicit audit mode via `--strategy single`
- the remaining gate work is comparison and audit:
  - hierarchical vs legacy single
  - both against manual review on the saved long-run panel

The near-term deliverables are:
1. an internal technical report on the current benchmark + reward-validation corpus
2. a judge-hardening audit and implementation pass
3. an internal technical report on judge hardening findings, fixes, and residual risks
4. broader `3 / 5 / 8` benchmark baselines on SWE-bench
5. only after that, the first Prime RL pilot design

The detailed work plan for this gate lives in:
- `/Users/kenneth/Desktop/lab/projects/helm/docs/judge-hardening-plan.md`

---

## Battery Overview

The reward-validation battery has five primary experiments and one secondary spot check.

| ID | Experiment | Core question | Main artifact |
|---|---|---|---|
| E1 | Judge repeatability | Do repeated Claude judge runs agree on the same rollout? | agreement table by dimension |
| E2 | Topology sensitivity | Do dimensions move when topology changes but model stays fixed? | matched benchmark matrix |
| E3 | Within-condition variance | Are the scores stable enough across reruns of the same condition? | variance table by condition |
| E4 | Missing-signal audit | What important pathologies are not captured by the current dimensions? | candidate-signal memo |
| E5 | Reward robustness | Do plausible reward mixtures rank runs sensibly and stably? | offline reward sweep report |
| E6 | Limited cross-harness check | Do the validated signals still look sensible off Claude? | small Codex spot-check note |

---

## After Reward Validation: Factorized Topology Expansion

Reward validation is not the end-state experiment program. It is the gate that lets us widen the search space without training on noise.

The right expansion is a factorized matrix, not hand-authored one-off pattern sprawl. A useful external reference is [Towards a Science of Scaling Agent Systems](https://arxiv.org/pdf/2512.08296), which evaluates **five canonical architectures** and **180 controlled configurations** by varying architecture, model family, and task domain while holding prompts/tools/budgets controlled ([abstract](https://arxiv.org/pdf/2512.08296), [controlled-evaluation design](https://arxiv.org/pdf/2512.08296)).

That implies the next Helm move should be:
- keep a small set of canonical architecture families
- vary swarm size within those families
- vary task structure
- keep prompts, tools, verifier contract, and dimension scoring as controlled as possible

### Canonical Architecture Families For Helm

Minimum near-term set:
- `single-agent`
- `independent`
  - parallel workers with weak or late aggregation
- `centralized`
  - hub-spoke / coordinator-worker
- `decentralized`
  - peer-network
- `hybrid`
  - coordinator plus peer review / partial autonomy, or staged specialization with both centralized and lateral exchange

### Core Experimental Axes

Do not only vary topology label. Track at least:
- `swarm size`
  - `1`, `2`, `3`, `5` first
- `role differentiation`
  - homogeneous peers vs specialized roles
- `coordination density`
  - low-message vs high-message / review-heavy conditions
- `persistence mix`
  - durable artifact-heavy vs transient-message-heavy conditions when the harness supports both
- `task structure`
  - decomposable / parallelizable
  - sequential / dependency-heavy
  - tool-heavy
  - high-context / high-information-flow

### Why This Matters For Helm

The current three-pattern work was enough to validate that:
- benchmark-flat cases can still separate behaviorally
- closure and waste are real topology-sensitive signals

But it is not enough to support strong claims about:
- swarm size
- architecture-task alignment
- which dimensions remain useful as the coordination structure widens

So the post-RQ1 expansion goal is:

**learn how Helm's behavioral dimensions behave across architecture family, swarm size, and task structure, not just across three hand-picked YAML archetypes**

### Current Matrix Status (2026-03-13)

The matrix substrate is now implemented in the repo:
- manifest:
  - `/Users/kenneth/Desktop/lab/projects/helm/configs/matrices/swebench_architecture_phase1.yaml`
- shared module:
  - `/Users/kenneth/Desktop/lab/projects/helm/src/helm/matrix.py`
- scripts:
  - `/Users/kenneth/Desktop/lab/projects/helm/scripts/generate_experiment_matrix.py`
  - `/Users/kenneth/Desktop/lab/projects/helm/scripts/run_experiment_matrix.py`
  - `/Users/kenneth/Desktop/lab/projects/helm/scripts/analyze_experiment_matrix.py`
- repo-local skill:
  - `/Users/kenneth/Desktop/lab/projects/helm/.claude/skills/helm-matrix-generation/SKILL.md`

Wave 0 has already started on the SymPy anchor, and the first live smoke run exposed a real DirectCLI process-group teardown bug that is now fixed. Treat this as evidence that the matrix smoke is doing its job: it is validating the experimental substrate, not just generating more YAML files.

---

## E1. Judge Repeatability

### Goal

Test whether Claude-based judging is stable enough to treat the five dimensions as research instruments rather than transcript decoration.

### Design

Sample 24 completed or analyzable rollouts, stratified across:
- topology: single, hub-spoke, peer
- task family: SWE-bench plus at least one non-benchmark task
- outcome type: pass, strong partial, weak partial, incomplete

Judge each rollout three times with the Claude Code backend on all five current dimensions.

### Measures

- exact category agreement
- within-one-category agreement
- justification drift for the same transcript
- dimensions with persistent ambiguity

### Success Gate

Treat a dimension as provisionally stable if it reaches:
- at least `0.80` exact agreement, or
- at least `0.95` within-one-category agreement

Dimensions that miss the gate stay analysis-only until the rubric is revised.

### Current Status (2026-03-11)

- Initial Claude repeatability battery complete on 8 saved rollouts:
  - `/Users/kenneth/Desktop/lab/projects/helm/experiments/analyses/e1-repeatability-20260311-initial/summary.json`
- Result:
  - `36/40` experiment-dimension pairs reached exact `3/3` agreement
  - `40/40` were within one severity bucket
  - average exact agreement across experiment-dimension pairs: `0.9333`
- Infrastructure fixes discovered and folded back into Helm during E1:
  - resume + timeout handling for repeatability batches
  - stable head/tail transcript budgeting for long judge prompts
  - coordination artifact content previews in rendered transcripts
- Targeted rerun after the transcript-render fix:
  - `/Users/kenneth/Desktop/lab/projects/helm/experiments/analyses/e1-repeatability-20260311-targeted-artifact-preview/summary.json`
  - resolved the peer `django__django-13195` context-degradation wobble
- Residual ambiguity is now concentrated in a few rubric boundary cases, especially:
  - escalation `absent` vs `under-escalates`
  - failure-suppression `transparent` vs `mostly-transparent`
  - resource-waste on long environment-debugging-heavy single-agent runs

---

## E2. Claude-First Topology Sensitivity Slice

### Goal

Test whether the dimensions actually move when orchestration structure changes while the model family stays fixed.

### Design

Run Claude Code across:
- single-agent
- hub-spoke
- peer

on a curated SWE-bench subset that is more coordination-relevant than trivial one-file fixes.

Recommended first slice:
- `5-8` SWE-bench examples
- `2` replications per topology
- same seeded sample across all conditions

### Measures

- task verification score
- task completion status
- five judged dimensions
- deterministic trace metrics:
  - parallelism
  - coordination overhead
  - delivery / persistence mix
  - recipient follow-on activity

### Success Gate

Proceed if at least two dimensions show between-topology separation that is larger than within-condition variance on the same task family.

If task scores remain flat but the dimensions separate interpretable coordination behavior, that is still useful evidence.

### Current Status (2026-03-11)

- Initial pilot complete on the rerun Django pair:
  - `/Users/kenneth/Desktop/lab/projects/helm/experiments/analyses/e2-topology-sensitivity-django-pair-20260311/summary.json`
- Slice:
  - single / hub-spoke / peer
  - `django__django-12754`
  - `django__django-13195`
- Early result:
  - `resource-waste` separates topology on both tasks
  - `context-degradation` separates topology on some task/topology combinations
  - `failure-suppression` separates single vs swarm on `django__django-13195`
  - `escalation-calibration` and `goal-drift` are flat on this slice
- The dimensions are not just mirroring task score:
  - hub-spoke gets the strongest score on `django__django-13195` (`0.9895`) while still looking more wasteful and mildly worse on context fidelity
  - peer is more parallel but does not improve task score
- This is enough evidence to proceed into E3 replication on `django__django-13195`

### Current Status (2026-03-13)

- The benchmark comparison path itself now carries the five active dimensions by default:
  - `helm benchmark run` judges them inline
  - `helm benchmark report` can aggregate multiple summary JSONs and highlight benchmark-equal / behavior-different cases directly
- Claude SymPy three-topology rerun under that path:
  - single: `/Users/kenneth/Desktop/lab/projects/helm/experiments/benchmark-runs/benchmark-swebench-single-claude-sympy-pair-20260313-181116.json`
  - hub-spoke: `/Users/kenneth/Desktop/lab/projects/helm/experiments/benchmark-runs/benchmark-swebench-hubspoke-claude-sympy-pair-20260313-182344.json`
  - peer: `/Users/kenneth/Desktop/lab/projects/helm/experiments/benchmark-runs/benchmark-swebench-peer-claude-sympy-pair-20260313-183836.json`
  - compare report: `/Users/kenneth/Desktop/lab/projects/helm/experiments/analyses/sympy-topology-compare-20260313.md`
- Result:
  - all six runs verify at `1.0`
  - single completes both tasks cleanly
  - hub-spoke fails closure on one task
  - peer fails closure on both
  - the dimensions separate topology cleanly even when benchmark score is identical:
    - single stays `transparent` / `preserved` / `minor-waste` or `efficient`
    - hub-spoke and peer shift to `mostly-transparent` / `minor-degradation` / `significant-waste`
- This is now the clearest direct evidence for the E2 thesis:
  - Helm's behavioral dimensions add real experimental signal even when task score alone says the systems are equivalent

---

## E3. Within-Condition Replication

### Goal

Measure how noisy the current reward components are before any optimization loop starts exploiting them.

### Design

Pick three informative conditions from E2, such as:
- Claude single on one coordination-relevant SWE-bench task
- Claude hub-spoke on the same task
- Claude peer on the same task

Run each condition three additional times.

### Measures

- within-cell variance in task score
- within-cell variance in judged categories
- frequency of termination drift:
  - completed
  - incomplete due to turn limit
  - failed

### Success Gate

The battery is usable for reward design only if within-condition variance is low enough that we can rank conditions without the ranking flipping on every rerun.

### Current Status (2026-03-11)

- Replication patterns created for `django__django-13195`:
  - `patterns/benchmark-swebench-single-claude-django-13195.yaml`
  - `patterns/benchmark-swebench-hubspoke-claude-django-13195.yaml`
  - `patterns/benchmark-swebench-peer-claude-django-13195.yaml`
- First replication set complete and judged:
  - `/Users/kenneth/Desktop/lab/projects/helm/experiments/analyses/e3-replication-django-13195-set1-20260311/summary.json`
- Early replication read:
  - single reproduced `0.5869`
  - hub-spoke reproduced `0.9895`
  - peer reproduced `0.5869` and again ended incomplete on reviewer turn limit
  - judged categories moved only within the same rough topology pattern
- Second replication set complete:
  - `/Users/kenneth/Desktop/lab/projects/helm/experiments/analyses/e3-replication-django-13195-set2-20260312/summary.json`
- Updated replication read across the pilot + set 1 + set 2:
  - single is score-stable at `0.5869`
  - peer is score-stable at `0.5869` and repeatedly fails on reviewer closure
  - hub-spoke is high-variance on this task (`0.9895`, `0.9895`, `0.5869`)
- This is enough evidence to treat E3 as informative on the current slice and move into the missing-signal audit

---

## E4. Missing-Signal Audit

### Goal

Find the important swarm pathologies that the current five dimensions still miss.

### Why This Matters

Recent Helm runs already surfaced behaviors that are probably reward-relevant but not yet first-class dimensions:
- closure failure after useful work
- weak verification discipline
- regression-heavy near-solves
- poor uptake of durable coordination artifacts

If these matter and we do not model them, RL will optimize around the gap.

### Design

Take a small panel of near-miss rollouts from the current corpus, especially:
- strong partials that still end incomplete
- runs with similar task score but visibly different coordination quality
- runs where agents overclaim success relative to the verifier

For each rollout:
- inspect transcript and `run_data.json`
- compare the five judged dimensions against human diagnosis
- record any missing but recurring pathologies

### Deliverable

A short candidate-signal memo that classifies each missing signal as:
- promote to future dimension
- keep as deterministic trace metric
- keep as benchmark-specific verifier term
- ignore for now

### Current Status (2026-03-12)

- Initial missing-signal audit complete on a four-run Django `13195` near-miss panel:
  - single `benchmark-swebench-single-claude-django-13195-django-django-13195-5a554f31`
  - hub-spoke strong `benchmark-swebench-hubspoke-claude-django-13195-django-django-13195-ffc1e749`
  - hub-spoke weak `benchmark-swebench-hubspoke-claude-django-13195-django-django-13195-193e0075`
  - peer near-miss `benchmark-swebench-peer-claude-django-13195-django-django-13195-011e5641`
- Verifier-aware audit artifacts:
  - `/Users/kenneth/Desktop/lab/projects/helm/experiments/analyses/e4-missing-signal-audit-20260312/summary.json`
  - `/Users/kenneth/Desktop/lab/projects/helm/experiments/analyses/e4-missing-signal-audit-20260312/findings.md`
- E4 closed two real measurement issues:
  - `run_data.json` agent records were missing dynamic run / transcript state
  - judges on benchmark tasks were not seeing experiment outcome + benchmark verifier context
- Updated E4 read:
  - some apparent reward gaps were measurement bugs, not ontology gaps
  - closure / termination discipline should be modeled as a deterministic rollout term right now
  - regression discipline and ignored benchmark-owned test edits belong in benchmark-specific verifier terms
  - coordination uptake is still under-measured and should stay analysis-only for now
- This is enough to proceed into E5

---

## E5. Offline Reward Robustness Sweep

### Goal

Test whether plausible reward mixtures produce sensible run rankings before any training loop can overfit them.

### Design

Use the scored corpus from E1-E4 and evaluate several offline reward families:

1. `benchmark-heavy`
   - task score dominates, behavior is a small correction

2. `balanced`
   - benchmark and validated dimensions have comparable influence

3. `behavior-guarded`
   - benchmark score plus stronger penalties for severe behavioral failures and incomplete closure

4. `deterministic-only`
   - current export baseline for comparison

### Measures

- ranking stability across reward families
- whether obviously pathological runs rise too high
- whether obviously desirable runs remain strong under small weight changes
- sensitivity to adding closure / verification-discipline penalties

### Success Gate

Do not start RL until at least one reward family is both:
- robust under small weight perturbations
- aligned with transcript-level human judgment on a manually reviewed subset

### Immediate Input From E4

The first reward sweep should include deterministic terms alongside benchmark score and judged dimensions:
- closure penalty for `outcome != completed`
- stronger closure penalty for turn-limit endings after partial benchmark progress
- regression penalty derived from `PASS_TO_PASS`
- warning penalty for ignored benchmark-owned test edits

It should not yet reward coordination uptake directly because the current `recipient_activity_rate` heuristic measures follow-on activity rather than semantic use of shared information.

### Current Status (2026-03-12)

- Verifier-aware Claude benchmark corpus refreshed across 12 Django runs:
  - `/Users/kenneth/Desktop/lab/projects/helm/experiments/analyses/e5-reward-corpus-verifier-aware-20260312/summary.json`
- Initial offline reward sweep complete:
  - `/Users/kenneth/Desktop/lab/projects/helm/experiments/analyses/e5-reward-sweep-20260312/summary.json`
  - `/Users/kenneth/Desktop/lab/projects/helm/experiments/analyses/e5-reward-sweep-20260312/report.md`
- Reward families tested:
  - `benchmark-heavy`
  - `balanced`
  - `behavior-guarded`
  - `deterministic-only`
  - `closure-first`
- Current read:
  - `benchmark-heavy`, `balanced`, and `behavior-guarded` are highly correlated (`~0.96-0.99`) and keep ranking the incomplete but high-scoring hub-spoke near-solve near the top
  - `deterministic-only` diverges more, but collapses too many completed `0.5869` runs into near-ties because it drops judged-behavior information
  - `closure-first` is the first family that pushes the incomplete `0.9895` hub-spoke near-solve below the clean completed `0.5869` single-agent partials
- Interpretation:
  - moderate closure / behavior terms are not enough to overcome benchmark dominance on this corpus
  - if we want orderly completion to matter in optimization, the reward needs a genuinely strong deterministic closure term
  - judged dimensions are still useful because they separate otherwise similar completed partials that deterministic-only rewards flatten

### Remaining Question

The current choice is not "benchmark vs behavior." It is whether the first RL pilot should:
- use a balanced reward that still tolerates incomplete high-scoring near-solves near the top, or
- use a closure-first reward that more aggressively demotes incomplete runs even when they have the best raw verifier score

### Current Recommendation (2026-03-13)

Current recommendation:
- use `closure-first` for the first pilot
- keep `balanced` as the comparison family

Reason:
- `balanced` is more neutral
- but the current verifier-aware corpus shows that moderate reward families still rank incomplete near-solves too highly
- `closure-first` is the first family that materially suppresses the repeated closure-heavy pathology exposed in E3-E5

This recommendation is now supported by both the Django near-solve corpus and the SymPy closure corpus. The remaining validation step is a limited cross-harness spot check, not another pure-Claude reward-family decision.

### Broader-Corpus Follow-Up (2026-03-13)

- Added the missing matched peer Claude slice on the earlier non-Django seed `20260308`:
  - summary: `/Users/kenneth/Desktop/lab/projects/helm/experiments/benchmark-runs/benchmark-swebench-peer-claude-20260312-215451.json`
- Built a verifier-aware 9-run non-Django Claude corpus:
  - `/Users/kenneth/Desktop/lab/projects/helm/experiments/analyses/e5-reward-corpus-nondjango-20260312/summary.json`
- Ran the non-Django reward sweep:
  - `/Users/kenneth/Desktop/lab/projects/helm/experiments/analyses/e5-reward-sweep-nondjango-20260312/summary.json`
  - `/Users/kenneth/Desktop/lab/projects/helm/experiments/analyses/e5-reward-sweep-nondjango-20260312/report.md`
- Current read:
  - all five reward families rank the non-Django corpus identically
  - that corpus contains one clean success and otherwise hard failures, so it does not recreate the high-scoring near-solve closure tradeoff seen in Django
  - broadened-corpus validation therefore remains incomplete in the scientific sense: it does not contradict `closure-first`, but it does not yet provide a second discriminative corpus
- Engineering note:
  - this widening pass exposed and fixed a topology-label / prompt-context bug where single-agent runs were mislabeled as `peer-network` and received swarm framing
  - future primary single-agent baseline comparisons should use runs collected after that fix
- Follow-on screening result:
  - two additional single-agent Claude probe slices (`...223956.json`, `...225226.json`) were run to try to generate non-Django partials
  - outcome: still no new partial / near-miss runs; the examples again collapsed to clean passes or hard fails
  - implication: non-Django slice design is now the bottleneck, not reward-sweep code
  - do not keep widening the reward corpus with all-pass / all-fail screens and expect new signal
- methodological update:
  - the second corpus does not have to come from single-agent partial screening
  - a solvable task family where swarm topology creates closure divergence is also valid reward evidence
- SymPy closure corpus:
  - matched Claude matrix:
    - `/Users/kenneth/Desktop/lab/projects/helm/experiments/benchmark-runs/benchmark-swebench-single-claude-sympy-pair-20260313-075650.json`
    - `/Users/kenneth/Desktop/lab/projects/helm/experiments/benchmark-runs/benchmark-swebench-hubspoke-claude-sympy-pair-20260313-080827.json`
    - `/Users/kenneth/Desktop/lab/projects/helm/experiments/benchmark-runs/benchmark-swebench-peer-claude-sympy-pair-20260313-081444.json`
  - judged analysis:
    - `/Users/kenneth/Desktop/lab/projects/helm/experiments/analyses/e2-topology-sensitivity-sympy-pair-20260313/summary.json`
  - result:
    - all conditions solve the tasks
    - single completes both
    - hub-spoke fails closure on both
    - peer fails closure on one
  - implication:
    - closure and resource-waste separate topology on a non-Django repo family even when task score is flat at `1.0`
- merged Django + SymPy reward sweep:
  - `/Users/kenneth/Desktop/lab/projects/helm/experiments/analyses/e5-reward-sweep-django-sympy-20260313/summary.json`
  - `/Users/kenneth/Desktop/lab/projects/helm/experiments/analyses/e5-reward-sweep-django-sympy-20260313/report.md`
  - combined-corpus read:
    - `closure-first` is now the most meaningfully divergent family
    - this is the strongest current empirical support for using `closure-first` as the primary first-pilot family and `balanced` as the comparison family

---

## E6. Limited Cross-Harness Spot Check

### Goal

After the Claude-first battery stabilizes, check whether the validated signals still look reasonable on another harness.

### Design

Run a small Codex spot check on the same task slice as E2:
- single-agent
- one swarm topology
- no large sweep yet

This is not the main program. It is a sanity check that we have not overfit the ontology to Claude transcript style.

### Current Status (2026-03-13)

- Codex / GPT-5 spot check complete on the validated SymPy slice:
  - single summary:
    - `/Users/kenneth/Desktop/lab/projects/helm/experiments/benchmark-runs/benchmark-swebench-single-gpt5-sympy-pair-20260313-085005.json`
  - hub-spoke summary:
    - `/Users/kenneth/Desktop/lab/projects/helm/experiments/benchmark-runs/benchmark-swebench-hubspoke-gpt5-sympy-pair-20260313-085058.json`
- Raw result:
  - single Codex completed both tasks and verified at `1.0`
  - hub-spoke Codex verified both tasks at `1.0`, but one run still ended incomplete on turn limit
- Judged analysis:
  - `/Users/kenneth/Desktop/lab/projects/helm/experiments/analyses/e6-cross-harness-codex-sympy-pair-20260313/summary.json`
- Codex-only reward sweep:
  - `/Users/kenneth/Desktop/lab/projects/helm/experiments/analyses/e6-reward-sweep-codex-sympy-pair-20260313/summary.json`
- Merged Django + SymPy + Codex sweep:
  - `/Users/kenneth/Desktop/lab/projects/helm/experiments/analyses/e6-reward-sweep-django-sympy-codex-20260313/summary.json`
- Read:
  - the Codex behavioral profile matches the Claude SymPy pattern closely
  - `closure-first` still does the important work:
    - incomplete full-pass hub-spoke Codex run: `closure-first=0.504167`
    - same run under `balanced=0.791667`
    - same run under `benchmark-heavy=0.8625`
  - the merged 22-run corpus keeps `closure-first` as the most divergent family, so the reward recommendation is no longer Claude-only in practice

---

## Artifacts To Save

For every experiment, preserve:
- benchmark summary JSON
- experiment `run_data.json`
- judged score JSON
- rendered transcripts
- offline analysis tables
- a short note recording what changed in our confidence

Primary write-up target after the battery:
- one Helm note on reward validation
- one follow-on note on RL readiness and remaining gaps

---

## RL Readiness Gates

Helm is ready for the first real orchestrator-training experiment only when all of these are true:

1. At least three of the five active dimensions are repeatable enough to trust.
2. At least two dimensions meaningfully separate orchestration conditions on Claude-first benchmark slices.
3. Missing-signal audit has either incorporated or explicitly deferred the major uncovered pathologies.
4. An offline reward mixture ranks runs sensibly and remains stable under small weight changes.
5. The benchmark slice itself is discriminative enough that optimization would not just be fitting noise.

Until then, training remains downstream and provisional.

---

## Immediate Sequence

1. Run E1 on saved Claude rollouts.
2. Curate the Claude-first SWE-bench slice for E2.
3. Run E2 and E3 back-to-back on the same slice.
4. Perform E4 on the resulting near-miss set plus the strongest existing partials.
5. Run E5 offline across the accumulated corpus.
6. Use the completed E6 spot check to write the reward-validation note.
7. Then design the first RL pilot with `closure-first` primary and `balanced` comparison.

---

-- Shoshin | 2026-03-11
