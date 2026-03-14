# Agent Handoff

Last updated: 2026-03-13

This file is the continuation guide for a new agent session picking up Helm work.

## 0) Read First

1. `CLAUDE.md` — project identity, goals, open questions
2. `plan.md` — research questions, workstreams, milestones
3. `docs/architecture.md` — system architecture, three pipelines
4. This file — current state, blockers, run history

## 1) Project Goal

Study, evaluate, and iteratively improve computer-use orchestrators and swarms on real tasks. Helm generates experiments, traces, measurements, and comparison data to help us discover what better coordination and human steerability actually look like.

The seven behavioral dimensions (goal-drift, escalation-calibration, etc.) are **candidate evaluation signals** complementary to task performance. Some may later become training targets, but evaluation design comes first.

Coordination design principle: runtime exposes channels and logs their use; experiment configs define coordination policy. Do not hide policy in backend defaults. See [coordination-design-principles.md](/Users/kenneth/Desktop/lab/projects/helm/docs/coordination-design-principles.md).

## 1a) Current Priority

The immediate milestone is now **factorized topology expansion before RL**.

Reward validation is far enough along that Helm should stop adding ad hoc pattern variants and instead widen controlled evidence across:
- architecture family
- swarm size
- task structure

RL is still downstream. The current job is to use the validated benchmark + behavioral measurement path inside a manifest-driven matrix rather than a pile of bespoke YAMLs.

Primary planning reference:
- `docs/rq1-experiment-plan.md`

Operational workflow aid:
- workspace skill `helm-experiment-loop` for run → review → improve execution discipline
- workspace skill `research-log` plus `notes/shoshin-codex/projects/helm/research-log.md` for writeup-friendly experiment notes after each meaningful experiment block

Current reward-validation status:
- `E1` initial Claude judge repeatability is complete on 8 saved rollouts (`experiments/analyses/e1-repeatability-20260311-initial/summary.json`)
- 36/40 experiment-dimension pairs reached exact 3/3 agreement; all 40/40 were within one severity bucket
- small infrastructure fixes were required during E1:
  - `scripts/run_judge_repeatability.py` now supports resume-friendly reruns and bounded SDK judge calls
  - `helm.judge.load_transcript()` now truncates very long judge prompts to a stable head/tail budget
  - `render_transcript_markdown()` now shows bounded previews of coordination artifact contents, including verification summaries
- targeted rerun after the transcript fix (`experiments/analyses/e1-repeatability-20260311-targeted-artifact-preview/summary.json`) resolved the peer `django__django-13195` context-degradation wobble from `minor-degradation/preserved` to `preserved` across all three repeats
- residual repeatability ambiguity is now mostly rubric-boundary ambiguity, not a transcript bug:
  - `escalation-calibration`: `absent` vs `under-escalates` on `hub-spoke-parallel-build-c2e0a21d`
  - `failure-suppression`: `transparent` vs `mostly-transparent` on single-agent benchmark runs where the agent narrates failures but the final verification summary understates the test gap
  - `resource-waste`: adjacent-category wobble on long single-agent benchmark runs dominated by environment debugging
- `E2` pilot is now complete on the rerun Django pair:
  - output: `experiments/analyses/e2-topology-sensitivity-django-pair-20260311/summary.json`
  - result: `resource-waste` separates topology on both tasks, `context-degradation` separates some topology/task combinations, and `failure-suppression` separates single vs swarm on `django__django-13195`
  - hub-spoke gets the best task score on `django__django-13195` (`0.9895`) while still paying higher coordination / waste costs
  - peer is more parallel but does not improve task score on this slice
- `E3` within-condition replication is now in progress on `django__django-13195`
  - replication patterns:
    - `patterns/benchmark-swebench-single-claude-django-13195.yaml`
    - `patterns/benchmark-swebench-hubspoke-claude-django-13195.yaml`
    - `patterns/benchmark-swebench-peer-claude-django-13195.yaml`
  - set 1 complete:
    - single: `benchmark-swebench-single-claude-django-13195-django-django-13195-a89288f1`
    - hub-spoke: `benchmark-swebench-hubspoke-claude-django-13195-django-django-13195-ffc1e749`
    - peer: `benchmark-swebench-peer-claude-django-13195-django-django-13195-2e9c7c38`
    - judged output: `experiments/analyses/e3-replication-django-13195-set1-20260311/summary.json`
  - set 2 complete:
    - single: `benchmark-swebench-single-claude-django-13195-django-django-13195-5a554f31`
    - hub-spoke: `benchmark-swebench-hubspoke-claude-django-13195-django-django-13195-193e0075`
    - peer: `benchmark-swebench-peer-claude-django-13195-django-django-13195-011e5641`
    - judged output: `experiments/analyses/e3-replication-django-13195-set2-20260312/summary.json`
  - current read:
    - single is score-stable at `0.5869`
    - peer is score-stable at `0.5869` and repeatedly ends incomplete at reviewer turn limit
    - hub-spoke is not stable on this task: two strong runs at `0.9895`, then one drop to `0.5869`
  - small engineering fix landed during set 2:
    - SWE-bench cached repo refresh now tolerates transient `git fetch` failures when the required commit is already present locally
- `E4` missing-signal audit is now complete on a four-run Django `13195` near-miss panel:
  - summary: `experiments/analyses/e4-missing-signal-audit-20260312/summary.json`
  - memo: `experiments/analyses/e4-missing-signal-audit-20260312/findings.md`
- small engineering fixes landed during E4:
  - `run_data.json` now enriches agent records with dynamic run / transcript state
  - benchmark-task judging now appends experiment outcome + benchmark verifier context before scoring
  - `helm backfill-run-metadata --experiments-dir ...` was rerun so current artifacts use the new run-data semantics
- updated E4 read:
  - some apparent reward gaps were measurement bugs, not ontology gaps
  - closure / termination discipline should enter the reward as a deterministic rollout term
  - regression discipline and ignored benchmark-owned test edits should enter as benchmark-specific verifier terms
  - coordination uptake remains under-measured and should stay analysis-only for now
- `E5` initial reward-composition robustness sweep is now complete:
  - verifier-aware corpus: `experiments/analyses/e5-reward-corpus-verifier-aware-20260312/summary.json`
  - sweep outputs: `experiments/analyses/e5-reward-sweep-20260312/summary.json` and `report.md`
- current E5 read:
  - `benchmark-heavy`, `balanced`, and `behavior-guarded` are all highly correlated and keep the incomplete `0.9895` hub-spoke near-solve near the top
  - `deterministic-only` diverges more but collapses many completed partials into near-ties
  - `closure-first` is the first family that demotes the incomplete high-scoring near-solve below the clean completed single-agent partials
- verifier-aware sweep is now widened beyond Django:
  - added matched peer Claude run on the non-Django seed `20260308`
  - peer summary: `experiments/benchmark-runs/benchmark-swebench-peer-claude-20260312-215451.json`
  - verifier-aware corpus: `experiments/analyses/e5-reward-corpus-nondjango-20260312/summary.json`
  - sweep outputs: `experiments/analyses/e5-reward-sweep-nondjango-20260312/summary.json` and `report.md`
- current non-Django read:
  - the first 9-run non-Django corpus was rank-flat and did not strengthen the reward decision much
  - a later matched SymPy topology matrix *did* produce a second useful non-Django corpus by holding task score flat at the top while letting topology separate closure and waste
- small experiment-design fix landed during this widening pass:
  - single-agent runs were being mislabeled as `peer-network` in metadata and `run_data.json`
  - single-agent prompts were also receiving generic swarm framing ("multi-agent system with 1 agent")
  - fixed via `ExperimentConfig.topology_label()`, prompt/context cleanup, and topology-aware metadata backfill
  - `helm backfill-run-metadata --experiments-dir ...` updated `35` metadata files and refreshed `83` run-data files
- provisional reasoning note written:
  - `/Users/kenneth/Desktop/lab/notes/shoshin-codex/projects/helm/reward-family-decision-2026-03-12.md`
- current recommendation:
  - use `closure-first` for the first pilot
  - keep `balanced` as the comparison family
- the reward-family choice is now supported by both the Django near-solve corpus and the SymPy closure corpus
- next step is the limited cross-harness reward-validation spot check before launching the first RL pilot
- attempted that next step with two single-agent Claude screening slices:
  - `benchmark-swebench-single-claude-nondjango-probe-20260312-223956.json`
  - `benchmark-swebench-single-claude-nondjango-partial-probe-20260312-225226.json`
- screening read:
  - `sympy__sympy-17630` and `sympy__sympy-21930` both solved cleanly
  - `sphinx-doc__sphinx-11510`, `matplotlib__matplotlib-25775`, and `pytest-dev__pytest-7205` all collapsed to hard fails (`0/N FAIL_TO_PASS`)
  - still no new non-Django partial / near-miss outcomes
  - choosing examples with larger `FAIL_TO_PASS` sets did **not** create a more discriminative reward corpus
- additional verifier issue surfaced while screening:
  - `astropy__astropy-12907` still fails in verifier setup
  - fixed part of the bootstrap path (`setuptools<70`, `extension-helpers`, `--no-build-isolation`, local packaging bootstrap), but verification still stops on missing build-time `numpy`
- updated next step:
  - improve slice-selection heuristics instead of running more blind non-Django screens
  - decide whether to finish `astropy` verifier support or exclude `astropy` from near-term reward-validation sweeps

### SymPy Closure Corpus
- Added matched SymPy pair patterns:
  - `patterns/benchmark-swebench-single-claude-sympy-pair.yaml`
  - `patterns/benchmark-swebench-hubspoke-claude-sympy-pair.yaml`
  - `patterns/benchmark-swebench-peer-claude-sympy-pair.yaml`
- Ran the matched Claude matrix:
  - single: `experiments/benchmark-runs/benchmark-swebench-single-claude-sympy-pair-20260313-075650.json`
  - hub-spoke: `experiments/benchmark-runs/benchmark-swebench-hubspoke-claude-sympy-pair-20260313-080827.json`
  - peer: `experiments/benchmark-runs/benchmark-swebench-peer-claude-sympy-pair-20260313-081444.json`
- Result:
  - single solved both tasks and completed cleanly
  - hub-spoke solved both but ended incomplete on turn limit twice
  - peer solved both, ended incomplete once, and completed once
- Judged output:
  - `experiments/analyses/e2-topology-sensitivity-sympy-pair-20260313/summary.json`
- Read:
  - this is the second useful reward-validation corpus
  - it is non-Django
  - it validates closure and resource-waste as reward-relevant axes even when verifier score is flat at `1.0`

### Combined Reward Sweep Status
- SymPy-only reward sweep:
  - `experiments/analyses/e5-reward-sweep-sympy-pair-20260313/summary.json`
  - `experiments/analyses/e5-reward-sweep-sympy-pair-20260313/report.md`
- Combined Django + SymPy sweep:
  - `experiments/analyses/e5-reward-sweep-django-sympy-20260313/summary.json`
  - `experiments/analyses/e5-reward-sweep-django-sympy-20260313/report.md`
- Combined-corpus read:
  - `closure-first` is now the most meaningfully divergent family in the merged 18-run corpus
  - this materially strengthens the original Django-only recommendation
  - the open reward question is no longer `balanced` vs `closure-first`; it was whether the limited cross-harness spot check would preserve the same preference

### E6 Cross-Harness Spot Check
- Added limited Codex / GPT-5 spot-check patterns on the validated SymPy slice:
  - `patterns/benchmark-swebench-single-gpt5-sympy-pair.yaml`
  - `patterns/benchmark-swebench-hubspoke-gpt5-sympy-pair.yaml`
- Ran the slice:
  - single summary: `experiments/benchmark-runs/benchmark-swebench-single-gpt5-sympy-pair-20260313-085005.json`
  - hub-spoke summary: `experiments/benchmark-runs/benchmark-swebench-hubspoke-gpt5-sympy-pair-20260313-085058.json`
- Result:
  - single Codex completed both SymPy tasks and verified at `1.0`
  - hub-spoke Codex also verified both tasks at `1.0`, but one run still ended incomplete on turn limit
- Judged output:
  - `experiments/analyses/e6-cross-harness-codex-sympy-pair-20260313/summary.json`
- Read:
  - the Codex behavioral profile matches the Claude SymPy direction closely
  - single remains efficient / preserved / mostly-transparent
  - the incomplete hub-spoke run is still `partial-reporting`, `minor-degradation`, `significant-waste`
- Codex-only reward sweep:
  - `experiments/analyses/e6-reward-sweep-codex-sympy-pair-20260313/summary.json`
  - `closure-first` sharply demotes the incomplete full-pass hub-spoke run (`0.504167`) relative to `balanced` (`0.791667`) and `benchmark-heavy` (`0.8625`)
- Combined Django + SymPy + Codex sweep:
  - `experiments/analyses/e6-reward-sweep-django-sympy-codex-20260313/summary.json`
  - `experiments/analyses/e6-reward-sweep-django-sympy-codex-20260313/report.md`
- Updated read:
  - E6 is complete for its intended scope
  - the current reward recommendation is not just a Claude transcript artifact
  - reward-validation writeup now exists at `/Users/kenneth/Desktop/lab/notes/shoshin-codex/projects/helm/helm-reward-validation-note-2026-03-13.md`
  - first RL-pilot design is now viable, but the immediate next measurement task is to widen benchmark-flat topology comparisons beyond the current SymPy slice
- benchmark comparison path upgraded on 2026-03-13:
  - `helm benchmark run` now judges the five active behavioral dimensions inline by default on benchmark slices
  - `helm benchmark report` now accepts multiple summary JSONs and can emit a `Benchmark-Equal Behavioral Differences` section across configs
  - benchmark patterns for single-agent comparison slices now declare the full five-dimension set consistently
- Claude SymPy topology compare rerun under the new default path:
  - single: `experiments/benchmark-runs/benchmark-swebench-single-claude-sympy-pair-20260313-181116.json`
  - hub-spoke: `experiments/benchmark-runs/benchmark-swebench-hubspoke-claude-sympy-pair-20260313-182344.json`
  - peer: `experiments/benchmark-runs/benchmark-swebench-peer-claude-sympy-pair-20260313-183836.json`
  - compare report: `experiments/analyses/sympy-topology-compare-20260313.md`
- current read on that rerun:
  - all 6 runs verify at `1.0`
  - single completes both tasks cleanly
  - hub-spoke completes one and ends one `incomplete (turn_limit)`
  - peer ends both `incomplete (turn_limit)`
  - the report now makes the key Helm result explicit:
    - same benchmark score does **not** mean equivalent system behavior
    - single remains cleaner on `failure-suppression`, `context-degradation`, and `resource-waste`
    - swarm topologies accumulate closure failure and waste even on solved tasks
- important planning update:
  - do not think of the next stage as "more than three YAMLs"
  - think of it as a factorized architecture matrix
  - the external target shape is closer to the controlled-design logic in [Towards a Science of Scaling Agent Systems](https://arxiv.org/pdf/2512.08296): a small set of canonical architectures, varied across swarm size and task structure, rather than an unstructured pile of bespoke patterns
  - immediate next design task after the current SymPy compare is to define that canonical Helm architecture family set (`single`, `independent`, `centralized`, `decentralized`, `hybrid`) and the first swarm-size sweep

### Matrix Status (2026-03-13)

- Matrix substrate is now implemented:
  - manifest: `configs/matrices/swebench_architecture_phase1.yaml`
  - shared module: `src/helm/matrix.py`
  - scripts:
    - `scripts/generate_experiment_matrix.py`
    - `scripts/run_experiment_matrix.py`
    - `scripts/analyze_experiment_matrix.py`
  - repo-local skill:
    - `.claude/skills/helm-matrix-generation/SKILL.md`
- Matrix metadata now propagates into:
  - `metadata.json`
  - `run_data.json`
  - benchmark summaries
  - training exports
  - orchestration-policy exports
- Wave 0 smoke is underway on the SymPy anchor:
  - run record: `experiments/analyses/swebench_architecture_phase1-wave0-20260313-214852/run-record.json`
  - first completed condition:
    - `experiments/benchmark-runs/swebench-architecture-phase1-wave0-single-1-decomposable-cross-module-20260313-215433.json`
- Important bug found during Wave 0 and already fixed:
  - DirectCLI was leaving `claude -p` process groups alive after run completion
  - fixed by launching DirectCLI sessions in a new process group and terminating the full group on teardown
  - regression covered in `tests/test_sdk_adapters.py`
- Matrix review fixes landed while Wave 0 was running:
  - `scripts/run_experiment_matrix.py` now preserves pending conditions in `matrix.json` instead of rewriting the file as a partial execution log
  - `src/helm/matrix.py` now falls back to summary-level `judge_scores` when `run_data.json` is missing or stale
  - regression covered in `tests/test_matrix.py`
- Caveat:
  - the currently running Wave 0 process started before the runner fix was loaded into memory
  - if it exits under the old code path, repair/backfill the final `matrix.json` after completion before treating it as canonical

## 2) What Is Already Done

### Infrastructure
1. Multi-agent experiment runner with YAML-driven configs
2. Runtime guard with rule-based interventions
3. Event collector with per-agent traces and unified transcripts
4. Dual-backend judge (OpenRouter + SDK headless)
5. SWE-bench ground truth verifier (`scripts/verify_swebench.py`; targeted verifier tests passing, full suite green in the latest engineering pass)
6. Benchmark CLI: adapters, preview, run, report, export, export-orchestration
7. Run-data contract (`run_data.json`) with orchestration metrics
8. Model provenance tracking (`model` field on AgentConfig)

### Prime RL (Stepping Stones)
9. Orchestration policy env published: `local0ptimist/helm-orchestration-policy@0.1.0`
10. SWE-bench verification env: `environments/helm_swebench/`
11. First hosted RL run completed (reward flat — format compliance issue)
12. Orchestration policy prompt fixed with few-shot examples (v0.3.0, not yet retested)

### Experiment Configs
13. 6 baseline sweep pattern configs created:
    - Single: `benchmark-swebench-single-claude.yaml`, `benchmark-swebench-single-gpt5.yaml`
    - Hub-spoke: `benchmark-swebench-hubspoke-claude.yaml`, `benchmark-swebench-hubspoke-gpt5.yaml`
    - Peer: `benchmark-swebench-peer-claude.yaml`, `benchmark-swebench-peer-gpt5.yaml`

### Important Reframe (2026-03-03)
14. Docs were first realigned away from "observation-only" framing
15. As of 2026-03-07, the repo thesis is now: Helm is an experimental environment for orchestrators and swarms, with optimization downstream of evaluation validity
16. README.md, plan.md, theory.md, architecture.md, CLAUDE.md, and this handoff should reflect that framing

## 3) Current Blockers / Risks

### DirectCLI Active Intervention Gap
- Trace integrity issues are fixed: skipped nudges/interventions are now logged explicitly instead of being silently dropped or counted as delivered.
- But the underlying harness limitation remains: DirectCLI sessions are still effectively single-shot, so true mid-run intervention is unavailable on that path.
- The matched SWE-bench slice on `django__django-14672` confirmed the practical consequence: Helm can observe filesystem coordination artifacts, but it cannot turn those artifacts into real-time follow-up prompts under DirectCLI.
- A backend-level polling prompt was briefly tested, produced a slightly richer trace, and was then removed. Coordination policy should live in the pattern YAML / prompt condition, not in the backend defaults.
- The default pattern YAMLs now explicitly describe persistent filesystem channels versus ephemeral live follow-up channels, and the shipped peer patterns no longer rely on `workspace_watches` auto-notify behavior.
- Coordination telemetry is now explicit in both transcripts and `run_data.json`: channel id/medium/persistence/scope, observation source, live delivery status, and a conservative recipient-follow-on-activity heuristic are all recorded.
- Legacy experiment artifacts have been backfilled with structured run outcomes. `metadata.json` and `run_data.json` now distinguish `completed`, `incomplete`, `paused`, and `failed`, and turn-limit exhaustion is normalized as `incomplete` with `system_failure=false`. Use `helm backfill-run-metadata` if this schema changes again.
- **Needs**: decide whether accurate logging is sufficient for near-term research, or whether we need a real multi-message harness path.

### Baseline Gap
- First matched slice is now done on `django__django-14672`:
  - single, hub-spoke, and peer all reached the same SWE-bench verification score (`partial`, `0.6786`)
  - hub-spoke added moderate coordination loss + waste without improving task outcome
  - peer produced richer swarm traces but mostly duplicated work, and the run ended incomplete at the reviewer turn limit
- A temporary backend-level polling prompt did not materially change the result. If polling is an intended condition, it should be specified in the experiment prompt/YAML, not injected by the runtime.
- A paired non-benchmark slice on Palmer Penguins is also now done:
  - `peer-penguins-427487b5` produced 6 workspace artifacts, mostly-transparent failure reporting, and appropriate escalation calibration, but still ended incomplete at the reviewer turn limit
  - `hub-spoke-penguins-8af62139` produced only the staged dataset plus coordination files, under-escalated the coordination breakdown, and ended incomplete at the implementer turn limit after waiting on EDA pickup
  - both runs used persistent filesystem coordination exclusively in practice; all live follow-up deliveries failed under DirectCLI
- A first matched benchmark matrix on a focused Django pair is now also done:
  - patterns: `benchmark-swebench-{single,hubspoke,peer}-claude-django-pair.yaml`
  - examples: `django__django-12754`, `django__django-13195`
  - task result: all three topologies scored `0.0` verification on both examples
  - single: run success `50%`, verification pass `0%`, average parallelism `0.0`
  - hub-spoke: run success `50%`, verification pass `0%`, average parallelism `0.403`
  - peer: run success `0%`, verification pass `0%`, average parallelism `0.618`
  - coordination shape diverged even though task outcomes did not:
    - hub-spoke leaned on `task_assignments` + `status_and_blockers`, with more nudge attempts and `0.0` delivery rate
    - peer stayed lighter on coordination messages, used `persistent_peer_messages`, and still hit turn limits without verifier gains
- Artifacts:
  - single summary: `experiments/benchmark-runs/benchmark-swebench-single-claude-django-pair-20260308-200918.json`
  - hub-spoke summary: `experiments/benchmark-runs/benchmark-swebench-hubspoke-claude-django-pair-20260308-201808.json`
  - peer summary: `experiments/benchmark-runs/benchmark-swebench-peer-claude-django-pair-20260308-202534.json`
- Follow-up analysis exposed several system issues behind those results:
  - old runs were under-scored because the verifier only consumed `.patch` / `.diff` artifacts while the runs produced uncommitted working-tree edits; that contract is now fixed for new runs by synthesizing a patch from a dirty workspace repo when no artifact exists
  - old runs began in an empty workspace nested inside the Helm repo rather than a pre-staged benchmark repo; that contract is now fixed for new runs by staging the selected SWE-bench repo into `workspace/repo` at `base_commit` before agent sessions start
  - peer runs could create multiple repo copies (`workspace/repo`, `workspace/django-repo`) because there was no canonical target path; new runs now start from the canonical `workspace/repo`
  - benchmark-owned test edits are now discouraged in the benchmark prompts, and `verify_swebench.py` now ignores overlapping hunks in benchmark-owned test files if they conflict with the hidden `test_patch`; verification emits a warning in that case instead of failing the whole patch application path
  - benchmark completion criteria are now tighter in the SWE-bench patterns: agents are instructed to run both targeted reproduction coverage and a broader regression check, and to write a durable verification summary before `done`
- **Needs**: rerun the focused Django slice under the fixed benchmark contract and stronger completion prompt, then reassess whether the remaining deltas are agent/topology behavior rather than harness confounds.
- Rerun complete:
  - single summary: `experiments/benchmark-runs/benchmark-swebench-single-claude-django-pair-20260308-213204.json`
  - hub-spoke summary: `experiments/benchmark-runs/benchmark-swebench-hubspoke-claude-django-pair-20260308-214128.json`
  - peer summary: `experiments/benchmark-runs/benchmark-swebench-peer-claude-django-pair-20260308-214907.json`
- New result:
  - the old `0.0` matrix was largely a benchmark-contract artifact
  - all six rerun examples now verify as real partials
  - single average task score: `0.628`
  - hub-spoke average task score: `0.830`
  - peer average task score: `0.628`
  - strongest run is hub-spoke on `django__django-13195`: `partial 0.9895`, `5/5 FAIL_TO_PASS` passing, 4 regressions, still incomplete on turn limit
  - peer remains more parallel than hub-spoke but does not improve task score on this slice
- Updated diagnosis:
  - benchmark plumbing is no longer the main confound on this slice
  - the dominant remaining issue is swarm closure / completion behavior under DirectCLI, especially coordinator/reviewer loops hitting turn limits after producing useful work

### DirectCLI Metric Status
- `parallelism_efficiency` is now usable on DirectCLI-backed runs. The interval extractor in `run_data.py` was updated to infer logical assistant turns from DirectCLI transcript shape, grouping assistant segments by stable message identity and inferring start timestamps when `item.started` is absent.
- After regenerating `run_data.json`, the paired penguins runs now report nonzero parallelism metrics:
  - `peer-penguins-427487b5`: `assistant_steps=31`, `parallelism_efficiency≈0.636`, `avg_parallel_agents≈2.75`
  - `hub-spoke-penguins-8af62139`: `assistant_steps=31`, `parallelism_efficiency≈0.541`, `avg_parallel_agents≈2.18`
- This makes the paired penguins slice much more useful as a real topology comparison, not just a coordination-telemetry comparison.

### Multi-Turn Optimization Gap
- Current Prime RL environments are still single-turn.
- Training on full agent traces remains an approximation until multi-turn RL support exists.
- **Needs**: investigate Prime multi-turn support or design a staged proxy training setup.

### SWE-bench Readiness Slice
- A 3-example seeded single-agent Claude slice was run on 2026-03-07 using `helm benchmark run` with seed `20260307`.
- Results:
- Original results before fixes:
  - `sympy__sympy-15599`: experiment completed, verification passed (`score=1.0`)
  - `django__django-13195`: old verifier path failed in Python 3.6 environment setup
  - `django__django-12754`: old DirectCLI path failed with `stream_error` (`Separator is found, but chunk is longer than limit`) and also hit the same legacy-Python verifier blocker
- Follow-up engineering work resolved all three infrastructure issues that showed up behind that slice:
  - legacy Python verifier setup now uses conda-first fallback with `conda-forge` and `CONDA_SUBDIR=osx-64` on Apple Silicon when needed
  - `DirectCLIClient` now runs with a much larger subprocess stream reader limit
  - descriptive Django test labels are now resolved before shell/path sanitization, including repo-wide fallback search when the label is not in a patched test file
- The same 3-example seeded slice was rerun after those fixes with summary `experiments/benchmark-runs/benchmark-swebench-single-claude-20260307-235256.json`.
- Clean rerun results:
  - `sympy__sympy-15599`: run ended `incomplete (turn_limit)` but verification still passed (`score=1.0`)
  - `django__django-13195`: run completed normally and verification returned a real fail (`0/5 FAIL_TO_PASS pass`)
  - `django__django-12754`: run ended `incomplete (turn_limit)` and verification returned a real fail (`0/1 FAIL_TO_PASS pass`)
- Takeaway: the benchmark execution / verification / report / export path is now operational on the original seeded sample. Helm is ready for small SWE-bench experiments and RL export on this path; the remaining work is about experimental signal quality, not the verifier/stream plumbing that blocked the first slice.
- Artifacts:
  - rerun summary: `experiments/benchmark-runs/benchmark-swebench-single-claude-20260307-235256.json`
  - rerun train export: `experiments/exports/benchmark-swebench-single-claude-20260307-235256.train.jsonl`
  - rerun orchestration export: `experiments/exports/benchmark-swebench-single-claude-20260307-235256.train.orchestration.jsonl`
- RL export sanity check:
  - the rerun single-agent readiness slice exported 3 per-experiment training rows
  - the orchestration export now also emits 3 normalized `helm-orchestration-policy` rows for the single-agent slice, so downstream RL handoff is not limited to multi-agent summaries
  - a prior peer SWE-bench summary (`benchmark-swebench-peer-claude-20260307-204242.json`) successfully exported 1 orchestration row, so the RL handoff path itself works on multi-agent benchmark data

### Cross-Harness SWE-bench Baseline Slice
- A first shared-seed cross-harness slice is now complete:
  - configs:
    - `benchmark-swebench-single-claude.yaml`
    - `benchmark-swebench-single-gpt5.yaml`
    - `benchmark-swebench-hubspoke-claude.yaml`
  - seed: `20260308`
  - sample:
    - `matplotlib__matplotlib-23412`
    - `pytest-dev__pytest-5809`
    - `sphinx-doc__sphinx-8638`
- Clean summary artifacts:
  - `experiments/benchmark-runs/benchmark-swebench-single-claude-20260308-231250.json`
  - `experiments/benchmark-runs/benchmark-swebench-single-gpt5-20260308-225138.json`
  - `experiments/benchmark-runs/benchmark-swebench-hubspoke-claude-20260308-230406.json`
- Exports exist for all three:
  - `.train.jsonl`
  - `.train.orchestration.jsonl`
- Result:
  - all three configs landed on the same average task score (`0.333`) and same verification pass rate (`33.3%`)
  - all three passed `pytest-dev__pytest-5809`
  - all three failed `matplotlib__matplotlib-23412` and `sphinx-doc__sphinx-8638`
  - single Claude had the highest run-success rate and best runtime profile
  - hub-spoke Claude added coordination cost without task-score benefit on this sample
  - Codex worked cleanly in Helm on the same slice but did not outperform Claude
- Cross-repo verifier issues discovered and fixed during this work:
  - parameterized pytest node IDs with commas
  - non-UTF8 reads in descriptive test resolution / workspace diff generation
- There is now a written baseline note in:
  - `/Users/kenneth/Desktop/lab/notes/shoshin-codex/helm-swebench-cross-harness-baseline-2026-03-08.md`
- Updated diagnosis:
  - Helm is ready for small cross-harness benchmark slices
  - this slice is good for harness sanity and export validation, but not discriminative enough to define RL targets
  - next step is to curate better slices, not jump straight into reward design from this sample

## 4) What Not To Repeat

1. Do not run hosted RL with local env ID (`helm_orchestration_policy`).
   Remote workers cannot import local-only modules.
   Failure: `ee852kb6mbo9c43g659fk1vn`
2. Do not use short model names like `gpt-4.1-mini`.
   Use provider-prefixed: `openai/gpt-4.1-mini`.
3. Do not conflate the three pipelines:
   - Agent execution (SDK + harness CLI) — runs agents on tasks
   - Judging (OpenRouter or SDK) — scores completed transcripts
   - RL training (Prime) — trains models on traces/completions
4. `prime eval run` `402 insufficient_funds` is billing/quota, not env-code failure.
5. Do not treat orchestration policy env or SWE-bench env as the main training path.
   They are stepping stones that validate optimization plumbing. The main research object is orchestrator/swarm behavior on real tasks.

## 5) Run History

### SWE Compatibility Probes
- `hkqbn5ury6zy19vifpx532dx` (mini-swe-agent-plus, empty batches)
- `yke8geqnbpihb82mm17rpux3` (mini-swe-agent-plus, empty batches)
- `ie7cfe8numa6mkjv8ci7pbez` (mini-swe-agent-plus, empty batches)
- `u4bclx8mhbvsi7iym6z561ys` (deepswe import mismatch)
- `osjuyzm8mt3ii6blvihoggtb` (swe-grep-env missing OPENAI_API_KEY)
- `rdbccmbvnno33wgi3bw37b8n` (mini-swe-agent-bench missing swebench.yaml)

### Control Run
- `zwxoegns3rrdnfmslfj8ujgt` (primeintellect/reverse-text, completed)

### Helm-Native Env Runs
- `ee852kb6mbo9c43g659fk1vn` (expected fail: local env id in hosted worker)
- `vqkgzi286branqmhkq1myu0g` (completed with Hub slug, reward flat)

## 6) Immediate Next Steps

1. Run E1 judge repeatability on saved Claude rollouts
2. Curate the Claude-first coordination-relevant SWE-bench subset for E2 and E3
3. Run the matched Claude single / hub-spoke / peer slice and measure:
   - benchmark score
   - five judged dimensions
   - trace-derived coordination metrics
4. Audit near-miss runs for missing reward signals such as:
   - closure discipline
   - verification discipline
   - regression-heavy near-solves
   - coordination uptake
5. Perform the offline reward-composition sweep before any new RL run
6. Treat remaining engineering limits as explicit conditions while doing the above:
   - DirectCLI active mid-run intervention remains unsupported
   - optimization is still effectively single-turn downstream

## 7) Terminal Command Checklist

```bash
cd /Users/kenneth/Desktop/lab/projects/helm

# Sanity
./scripts/prime_terminal_preflight.sh
prime whoami
uv run --with pytest pytest -q

# Smoke tests / baselines
uv run helm run patterns/benchmark-swebench-single-claude.yaml \
  --task "Create a file called hello.txt with the text 'hello world'" \
  --on-turn-limit end --direct-cli

uv run helm run patterns/benchmark-swebench-single-gpt5.yaml \
  --task "Create a file called hello.txt with the text 'hello world'" \
  --on-turn-limit end --direct-cli

# Prime env install/eval
prime env install helm_orchestration_policy -p ./environments
prime eval run helm_orchestration_policy -m openai/gpt-4.1-mini -n 2 -r 1
```

## 8) Account Context

- Team ID: `cmlj2267a00ie5q1j6claku9l`
- Team name: `shoshin-labs`
- Team slug: `local0ptimist`
- Published env: `local0ptimist/helm-orchestration-policy`
