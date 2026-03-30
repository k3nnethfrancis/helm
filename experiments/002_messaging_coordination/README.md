# Experiment 002: Messaging Coordination

## Question

Does broker-based messaging (MCP tools) improve multi-agent coordination compared to experiment 001's filesystem approach? Does plan-then-execute prompting eliminate the polling waste observed in experiment 001 v2?

## Conditions

| Condition | Topology | Coordination | Agents | Tasks |
|-----------|----------|-------------|--------|-------|
| centralized-5-messaging | Hub-spoke | Broker messaging (MCP) | 5 | 8 SWE-bench |
| hybrid-5-filesystem | Hybrid | Filesystem | 5 | 8 SWE-bench |
| delegating-1-native | Delegating | Filesystem + native Agent tool | 1+ | 8 SWE-bench |

## Baselines (from Experiment 001)

- Single-agent: 8/8 complete, 4/8 solved (50%)
- Centralized@5 v1 (filesystem): coordinator collapse
- Centralized@5 v2 (messaging, continuous polling): 30-50% turn waste

## Key Changes from Experiment 001

1. **Plan-then-execute prompting**: Workers check inbox at start, do work, report back. No continuous polling.
2. **Broker messaging with MCP tools**: `helm_send_message`, `helm_check_inbox` as traced native tools (centralized condition).
3. **Mechanical enforcement**: Broker topology rules enforce who can message whom.
4. **Delegating topology**: Single agent with native `Agent` tool unblocked — studies harness-native delegation.

## Tasks (same 8 as experiment 001)

- sympy__sympy-17630
- sympy__sympy-21930
- django__django-13195
- pytest-dev__pytest-5809
- django__django-12754
- matplotlib__matplotlib-23412
- sphinx-doc__sphinx-8638
- pytest-dev__pytest-7205

## Running

```bash
# Centralized with messaging (8 tasks)
helm benchmark run experiments/002_messaging_coordination/configs/centralized-5.yaml \
  -n 8 --on-turn-limit end \
  --experiments-dir experiments/002_messaging_coordination/runs

# Hybrid with filesystem (8 tasks)
helm benchmark run experiments/002_messaging_coordination/configs/hybrid-5.yaml \
  -n 8 --on-turn-limit end \
  --experiments-dir experiments/002_messaging_coordination/runs

# Delegating with native Agent tool (8 tasks)
helm benchmark run experiments/002_messaging_coordination/configs/delegating-1.yaml \
  -n 8 --on-turn-limit end \
  --experiments-dir experiments/002_messaging_coordination/runs
```
