# 002: Messaging Coordination

## Question

How does broker-based messaging (MCP tools) compare to filesystem coordination for multi-agent coding tasks? Does minimal prompting produce usable coordination behavior?

## Hypothesis

Agents given only role descriptions and access to coordination tools will self-organize effectively. The coordination mechanism (messaging vs filesystem) will affect coordination overhead but not necessarily task outcome.

## Conditions

| Config | Topology | Agents | Coordination | Mechanism |
|--------|----------|--------|-------------|-----------|
| centralized-5.yaml | Hub-spoke | 5 | MCP tools (send_message, check_inbox) | Messaging broker, mechanical enforcement |
| hybrid-5.yaml | Hybrid (hub + lateral) | 5 | Filesystem (coordination/ directory) | Filesystem, prompt-only |
| delegating-1.yaml | Delegating | 1 | Native Agent tool (unblocked) | Harness-native delegation |

## Design

- **Tasks**: 8 SWE-bench Verified instances (same as experiment 001 for comparison)
- **Turn limits**: None (60min timeout only)
- **Prompts**: Minimal — role + one-line instructions. No protocol scripting.
- **Baseline**: Experiment 001 single-agent (50% solve rate)

## What We're Measuring

- Task solve rate per condition
- Coordination overhead (inbox polls, file reads vs actual work)
- Whether agents use signal_complete to end cleanly
- Behavioral dimensions: escalation calibration, goal drift, resource waste, topology adherence
- Comparison to experiment 001 (same tasks, different prompts/mechanism)

## Running

```bash
# One condition at a time
helm benchmark run experiments/002_messaging_coordination/centralized-5.yaml \
  -n 8 --on-turn-limit end --experiments-dir experiments/002_messaging_coordination/runs

helm benchmark run experiments/002_messaging_coordination/hybrid-5.yaml \
  -n 8 --on-turn-limit end --experiments-dir experiments/002_messaging_coordination/runs

helm benchmark run experiments/002_messaging_coordination/delegating-1.yaml \
  -n 8 --on-turn-limit end --experiments-dir experiments/002_messaging_coordination/runs
```

## Findings

*Pending — experiment not yet run at scale.*

### Smoke test (centralized-5, 1 task, django-12754)

- 9 messages exchanged through MCP broker
- Coordinator assigned work to all 4 workers
- Workers received assignments and responded
- Implementer polled inbox 26 times out of 90 items (29% overhead)
- Hit turn limit (50) before completion — turn limit default was a bug, now fixed
- System works: MCP tools discovered and used, delivery tracking correct
