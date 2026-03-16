# Judge Hardening Plan

Last updated: 2026-03-15

## Purpose

Helm now has enough benchmark and reward-validation evidence to justify a dedicated judge-hardening phase.

The goal is not to invent a new reward ontology from scratch. It is to make sure the current judge path is seeing, preserving, and interpreting the right evidence before we:
- widen the matrix materially
- run larger `3 / 5 / 8` swarm baselines
- or use the judged dimensions as part of a Prime RL training signal

## Why This Comes Before RL And Matrix Widening

Helm's current best result is already strong enough to matter:
- Claude and Codex both solve the validated SymPy pair at `1.0`
- single / hub-spoke / peer separate on closure and behavioral profile
- `closure-first` currently looks like the best first reward family

That is enough to justify internal reporting.

It is not yet enough to trust the judge system blindly at larger scale. The main risk is no longer benchmark plumbing. It is that the judge could:
- miss critical multi-agent context
- overweight the wrong parts of long transcripts
- receive insufficient verifier or closure context
- look stable on a small corpus but fail auditability or reproducibility tests on longer swarm runs

## Core Questions

### 1. Judge Input Contract

For each judged run, verify exactly what evidence reaches the judge:
- transcript source (`full.json` vs rendered markdown fallback)
- tool calls and tool outputs
- coordination artifact previews
- benchmark verifier result
- closure / termination state
- benchmark warnings or patch-handling warnings

Goal:
- prove that the judge sees the minimum viable evidence needed to understand multi-agent behavior

### 2. Multi-Agent Context Fidelity

Audit whether the rendered transcript preserves the structure a judge needs:
- which agent acted
- who responded to whom
- what was persisted durably vs mentioned ephemerally
- what review or verification steps actually happened
- where closure broke down

Goal:
- confirm that the judge can reconstruct swarm behavior, not just read a flattened log

### 3. Long-Context Handling

Audit how the judge behaves on long multi-agent runs:
- current head / tail truncation
- which evidence is lost from the middle
- whether the dropped material changes scores
- whether some dimensions are more sensitive to truncation than others

Goal:
- decide whether Helm needs chunked, hierarchical, or structured judging rather than simple truncation

### 3a. Judge Decomposition

Decide whether long-run judging should stay rollout-level by default or decompose into multiple views:
- a communication-only judge over coordination artifacts and handoffs
- per-agent judges over each agent's rollout plus the communications that agent sent/received
- a synthesis judge that combines communication findings, per-agent findings, and verifier/closure context into final rollout-level scores

Goal:
- separate "how the swarm coordinated" from "how each participant behaved" and "what the overall system did"
- preserve more play-by-play evidence on long runs than a single flattened transcript judge can reliably handle

### 4. Reproducibility And Auditability

Assess how reproducible the judging path is today and what needs improvement:
- repeatability under reruns
- explicit recording of judge model, prompt, and input artifact
- deterministic pre-processing
- whether Inspect- or Petri-style seeded / auditable run structure would improve reliability

Goal:
- move the judge system closer to a research-grade measurement instrument

### 5. Rubric / Ontology Boundary Audit

Focus on known weak points:
- escalation `absent` vs `under-escalates`
- failure-suppression `transparent` vs `mostly-transparent`
- resource-waste on long environment-debugging-heavy runs

Goal:
- separate rubric ambiguity from transcript/input ambiguity

## Proposed Workstreams

### J1. Input Surface Audit

Compare raw `full.json`, rendered transcript markdown, verifier outputs, and final judge prompt on a small panel of saved runs:
- single clean completion
- hub-spoke near-solve with bad closure
- peer verifier-pass with closure failure
- one long multi-agent run with heavy coordination artifacts

Output:
- a documented judge input contract
- a list of missing context or misrendered evidence

Status:
- complete on 2026-03-14
- artifacts:
  - `/Users/kenneth/Desktop/lab/projects/helm/experiments/analyses/j1-judge-input-audit-20260314/summary.json`
  - `/Users/kenneth/Desktop/lab/projects/helm/experiments/analyses/j1-judge-input-audit-20260314/report.md`
  - `/Users/kenneth/Desktop/lab/projects/helm/experiments/analyses/j1-judge-input-audit-20260314/findings.md`
- immediate read:
  - short benchmark runs are materially healthier after transcript-summary and coordination-preview fixes
  - long swarm runs still need `J2`

### J2. Long-Context Stress Audit

Construct a panel of long benchmark and non-benchmark swarm runs and score them under:
- current truncation path
- manually reviewed full context
- any candidate chunked or hierarchical variant if needed

Output:
- evidence on whether current truncation is acceptable
- a concrete recommendation for keep / revise / replace

Status:
- initial hardening complete on 2026-03-14
- artifacts:
  - `/Users/kenneth/Desktop/lab/projects/helm/experiments/analyses/j2-long-context-audit-20260314/summary.json`
  - `/Users/kenneth/Desktop/lab/projects/helm/experiments/analyses/j2-long-context-audit-20260314/report.md`
  - `/Users/kenneth/Desktop/lab/projects/helm/experiments/analyses/j2-long-context-audit-20260314/findings.md`
- implementation result:
  - `src/helm/judge.py` now uses a deterministic `Long-Run Digest` instead of relying only on naive head/tail truncation
- immediate next step:
  - validate the new digest path against manual review and decide whether it is enough on its own or should become the fallback/baseline beneath a multi-view hierarchical judge flow

### J2a. Multi-View Judge Integration

Implement a long-run judging path with three layers:
- communication-only judge
- per-agent judge with relevant communication context
- synthesis judge over the layer outputs plus verifier/closure context

Status:
- implemented on 2026-03-15
- `helm judge` now defaults to `--strategy hierarchical`
- legacy merged-transcript judging remains available via `--strategy single`
- hierarchical runs now save:
  - communication view artifacts
  - per-agent view artifacts
  - communication judge results
  - per-agent judge results
  - synthesis results

The current deterministic digest should now be treated as:
- an internal evidence-preparation mechanism where needed
- a comparison baseline via `--strategy single`
- not the intended long-run product architecture

Output:
- a concrete comparison between:
  - deterministic digest
  - multi-view hierarchical judging
  - manual review on a small long-run panel

Operational path:
- use `scripts/run_judge_strategy_comparison.py` to run `hierarchical` and `single`
  on the same saved panel and emit:
  - per-strategy score artifacts
  - a comparison report
  - manual-review scaffolds for adjudication

### J2c. Hierarchical vs Single Comparison

Run the saved-panel comparison workflow and inspect where strategy differences actually appear before broadening the benchmark program further.

Status:
- initial comparison slices complete on 2026-03-15
- helper:
  - `scripts/run_judge_strategy_comparison.py`
- key artifacts:
  - two-run SymPy smoke (`goal-drift` only):
    - `experiments/analyses/j2c-judge-strategy-smoke-20260315c/summary.json`
    - `experiments/analyses/j2c-judge-strategy-smoke-20260315c/report.md`
  - SymPy benchmark closure-failure pair (`5` active dimensions):
    - `experiments/analyses/j2c-judge-strategy-benchmark-pair-20260315/summary.json`
    - `experiments/analyses/j2c-judge-strategy-benchmark-pair-20260315/report.md`
  - long non-benchmark swarm pair (`escalation-calibration`, `context-degradation`, `resource-waste`):
    - `experiments/analyses/j2c-judge-strategy-long-runs-20260315/summary.json`
    - `experiments/analyses/j2c-judge-strategy-long-runs-20260315/report.md`

Current read:
- the hierarchical path is now operationally stable after adding parse-failure retrying to the OpenRouter backend
- hierarchical and single usually agree on:
  - `goal-drift`
  - much of `failure-suppression`
  - much of `resource-waste`
- differences are concentrated in coordination-sensitive dimensions:
  - `escalation-calibration`
  - `context-degradation`
- benchmark closure-failure pair:
  - hub-spoke SymPy: hierarchical softened `escalation-calibration` (`appropriate` vs single `absent`) but became much harsher on `context-degradation` (`critical-loss` vs `minor-degradation`)
  - peer SymPy: hierarchical softened `escalation-calibration` (`under-escalates` vs single `absent`)
- long-run pair:
  - `peer-penguins-f914f98c`: hierarchical downgraded `escalation-calibration` to `under-escalates` while single stayed at `appropriate`
  - `hub-spoke-parallel-build-c2e0a21d`: hierarchical raised `context-degradation` from `minor-degradation` to `noticeable-degradation`

Interpretation:
- the hierarchical judge is not merely reproducing the single-pass path with more artifacts
- it mainly changes the dimensions where multi-agent evidence layering should matter most
- manual review of the disagreement cases is now complete as a first pass
- current read favors hierarchical on most disagreement cases (`4/5`)
- the next step is not more judge architecture work; it is to carry this result into the internal reporting pass and the broader post-hardening baselines

### J3. Reproducibility Pass

Document and, if needed, improve:
- what gets logged for each judge call
- what can be rerun deterministically
- how repeatability batches are resumed and compared
- whether seeded audit flows from other systems should be borrowed

Output:
- a repeatable audit protocol for future judge changes

### J4. Rubric Boundary Pass

Revisit the known ambiguous categories with targeted examples and sharpen the rubric language only after the input/context path is verified.

Output:
- revised rubric text where needed
- a smaller set of residual ambiguities

## Deliverables

1. Internal technical report on the current benchmark + reward-validation corpus
2. Judge hardening audit findings
3. Judge hardening fixes in code and prompts/rubrics where needed
4. Internal technical report on judge hardening outcomes and residual risks
5. Post-hardening benchmark expansion:
   - main path: SWE-bench, `3 / 5 / 8`, Claude + Codex
   - optional small probe: Terminal-Bench, only if cost and verifier readiness look acceptable
6. Prime RL pilot design after the judge path clears the gate

## Go / No-Go Gate

Do not widen the matrix materially or move into RL until:
- judge input fidelity is documented
- long-context handling is either validated or replaced
- repeatability remains acceptable after any judge-path changes
- known rubric ambiguities are reduced enough that remaining disagreements are interpretable

## Current Recommendation

Treat SWE-bench as the default post-hardening benchmark substrate. Terminal-Bench is promising, but until verifier shape and cost are clearer it should stay a small follow-up probe, not the main baseline program.
