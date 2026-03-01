# RQ1 Experiment Plan

**Research question**: Can we measure visibility/control/steerability of multi-agent systems in a way that differentiates models and orchestration strategies?

**Status**: Draft
**Updated**: 2026-02-28

---

## Design

### Factors

| Factor | Levels | Notes |
|---|---|---|
| **Model** | Claude Sonnet (via `claude-code`), GPT-4.1 (via `codex` or `opencode`) | Single-model swarms: same model as orchestrator and subagents |
| **Topology** | Hub-and-spoke (3 agents), Peer network (3 agents) | Patterns: `hub-and-spoke.yaml`, `peer-network.yaml` |
| **Task** | SWE-bench sampled examples (via `swebench` adapter) | Standardized coding tasks with ground-truth verification |

### Why SWE-bench

SWE-bench is the primary task source because:
- **Ground-truth verification**: test suites provide objective pass/fail, not just completion mode
- **Model comparison baseline**: SWE-bench leaderboard scores exist for single-agent setups, giving us a direct comparison: same model solo vs. same model as a swarm
- **Standardized difficulty**: sampled examples control for task difficulty across cells
- **Reproducibility**: dataset is public, examples are seeded, results are comparable

We use `helm benchmark run` with the `swebench` adapter and `--seed` for deterministic sampling.

### Cell Structure

| | Hub-and-spoke | Peer network |
|---|---|---|
| **Claude Sonnet** | 5 runs | 5 runs |
| **GPT-4.1** | 5 runs | 5 runs |

**Total runs**: 2 models x 2 topologies x 5 replications = 20 runs per task sample.

With a minimum of 3 SWE-bench examples sampled per batch: **60 runs minimum**.

If budget permits, expand to 5 examples: **100 runs**.

### Dependent Variables

Per run:
- **Task verification**: pass/fail/partial + score (ground truth from SWE-bench test suite)
- **Deterministic orchestration metrics**: parallelism efficiency, coordination overhead, escalation precision/recall
- **Judge dimension scores** (5 dimensions, discrete categories):
  - escalation-calibration
  - goal-drift
  - failure-suppression
  - context-degradation
  - resource-waste

---

## Execution

### Prerequisites

1. SWE-bench adapter producing valid examples (`helm benchmark preview`)
2. Judge rubrics in v2 categorical format (completed)
3. At least one working harness per model family
4. `command` mode task verification wired to SWE-bench test runner

### Run Protocol

For each cell (model x topology x task):

```bash
# 1. Sample benchmark examples (seeded for reproducibility)
helm benchmark preview patterns/benchmark-swebench-template.yaml --limit 3

# 2. Run the batch
helm benchmark run patterns/{topology}-swebench.yaml \
  --sample-size 5 --seed 42 \
  --on-turn-limit end

# 3. Judge all completed experiments
for exp_id in $(helm list --experiments-dir experiments/ | grep swebench); do
  helm judge $exp_id --dimensions escalation-calibration,goal-drift,failure-suppression,context-degradation,resource-waste -b openrouter
done

# 4. Generate report
helm benchmark report experiments/benchmark-runs/{summary}.json
```

### Controlling for Confounds

**Prompt differences across harnesses**: Use minimal system prompts that don't prescribe coordination behavior beyond the pattern YAML. Document any harness-specific prompt adaptations.

**Task difficulty**: Use the same seeded sample across all cells. If a task is unsolvable by one model in solo mode, it may still be informative for coordination analysis.

**Judge reliability**: Run judge twice on a subset (10%) and compute inter-run agreement. If agreement < 80%, investigate rubric clarity.

---

## Analysis Plan

### Main Effects

1. **Model effect**: Do Claude and GPT-4.1 swarms differ on any dimension?
   - Per-dimension comparison (category distribution, severity distribution)
   - Task verification pass rate comparison

2. **Topology effect**: Do hub-and-spoke and peer network differ?
   - Coordination overhead comparison
   - Parallelism efficiency comparison
   - Escalation calibration comparison

3. **Interaction**: Does topology affect models differently?
   - Model x topology on each dimension

### Within-Cell Reliability

- Variance within replications (same model, same topology, same task)
- If within-cell variance > between-cell variance, the dimensions aren't differentiating

### Cross-Dimension Correlation

- Which dimensions move together?
- Are any dimensions redundant (high correlation)?
- Do some dimensions capture orchestration effects while others capture model effects?

### Solo vs. Swarm Comparison

Compare single-model SWE-bench performance (from leaderboard / solo runs) against swarm performance:
- Does adding agents improve task pass rate?
- At what cost in coordination overhead and resource waste?
- Which dimensions improve vs. degrade with multi-agent coordination?

---

## Success Criteria

RQ1 is answered affirmatively if:
- At least 2 dimensions show statistically meaningful differences across models OR topologies
- Within-cell variance is lower than between-cell variance for those dimensions
- The differences are interpretable (not just noise)

RQ1 is answered negatively if:
- No dimensions differentiate models or topologies
- This would still be a publishable finding — "current behavioral dimensions don't capture meaningful variation in single-model swarms"

---

## Timeline

1. **Week 1**: Validate SWE-bench adapter end-to-end, run pilot batch (1 model x 1 topology x 2 examples)
2. **Week 2**: Full experiment matrix (60-100 runs)
3. **Week 3**: Judge all runs, compute metrics, preliminary analysis
4. **Week 4**: Write-up, reliability checks, iterate if needed

---

-- Shoshin | 2026-02-28
