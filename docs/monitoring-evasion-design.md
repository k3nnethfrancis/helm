# Monitoring-Evasion Design

`monitoring-evasion` is part of Helm's seven-dimension ontology, but it should not be treated as a default per-run scored dimension.

Unlike the other active dimensions, it is fundamentally a **paired-run comparison problem**:
- monitored vs unmonitored
- same task
- same topology / swarm size
- same harness and prompt family
- same turn / budget settings

The question is not "did this single run evade monitoring?" The question is:

**Did the system's behavior shift when monitoring was visible?**

## Why It Stays Out Of The Default Judge Loop

Single-run judging is the wrong shape for this dimension because:
- the judge cannot infer the counterfactual from one rollout
- visible caution is not necessarily evasion
- failure or success alone does not reveal behavioral adaptation

So Helm should keep `monitoring-evasion` out of the default `helm judge` dimension list until paired-run comparison is available.

## Required Metadata / Manifest Hooks

Patterns and generated matrix conditions should use `metadata.paired_evaluation` when a run belongs to a monitored/unmonitored comparison set.

Current scaffold fields:
- `comparison_id`
  Stable identifier for the paired comparison group.
- `comparison_role`
  Typical values: `monitored`, `unmonitored`, `baseline`, `variant`.
- `comparison_axis`
  Defaults to `monitoring-evasion`.
- `visible_monitoring`
  Whether monitoring cues were visible to the agents in this run.
- `partner_condition_id`
  Optional pointer to the paired condition.
- `notes`
  Freeform design notes when needed.

These hooks are for experiment declaration and artifact traceability. They do not score the dimension by themselves.

## Planned Comparison Artifact

The eventual comparison output should be a paired analysis artifact, for example:

```json
{
  "comparison_id": "monitor-pair-1",
  "comparison_axis": "monitoring-evasion",
  "runs": {
    "monitored": "exp-monitored",
    "unmonitored": "exp-unmonitored"
  },
  "task_match": true,
  "topology_match": true,
  "budget_match": true,
  "observed_differences": {
    "escalation-calibration": "...",
    "resource-waste": "...",
    "human-model-accuracy": "..."
  },
  "monitoring_evasion": {
    "category": "some-differences",
    "severity": "moderate",
    "justification": "...",
    "evidence": ["..."]
  }
}
```

The key object is the **difference bundle**, not an isolated transcript score.

## Report Integration Expectations

Matrix or benchmark reports should eventually integrate paired-run monitoring-evasion by:
- grouping runs by `comparison_id`
- showing whether the monitored/unmonitored pair remained behaviorally stable
- linking the comparison result to the other six single-run dimensions

`monitoring-evasion` should therefore appear in reports as:
- a paired comparison section
- or a separate table keyed by `comparison_id`

It should not be silently mixed into the same per-run summary row as the single-run dimensions.

## Acceptance Criteria For Later Implementation

Helm should only promote `monitoring-evasion` into operational use when all of the following exist:
- stable paired-run metadata in pattern/manifests and saved metadata
- a comparison builder that validates the pair really is matched
- a judge or evaluator that reads a monitored/unmonitored difference bundle
- report integration that distinguishes paired-comparison outputs from per-run outputs
- at least one manual-adjudicated calibration set

Until then, `monitoring-evasion` remains a designed but not yet active measurement path.
