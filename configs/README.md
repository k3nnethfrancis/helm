# Helm Configs

## Configs

Standalone experiment configs. Each file defines one complete experiment: agents, topology, limits, benchmark, and evaluation dimensions.

```bash
# Run a single-agent experiment on one SWE-bench task
helm benchmark run configs/single-agent.yaml -n 1 --direct-cli --on-turn-limit end

# Run a centralized 5-agent swarm
helm benchmark run configs/centralized-5.yaml -n 1 --direct-cli --on-turn-limit end

# Run a delegating agent that can spawn subagents
helm benchmark run configs/delegating-1.yaml -n 1 --direct-cli --on-turn-limit end
```

### Writing your own config

A config YAML has these sections:

- **`name`** — experiment identifier
- **`agents`** — list of agents with id, harness, role, system_prompt, disallowed_tools
- **`coordination`** — inter-agent coordination mechanism (usually `filesystem`)
- **`evaluation`** — which behavioral dimensions to judge and which judge backend to use
- **`benchmark`** — dataset adapter, dataset path, verifier command
- **`limits`** — max duration, turns per agent, budget

See the examples for the full structure. Modify any field to create your own experiment.

### Topology enforcement

Each agent's `disallowed_tools` field mechanically blocks native Claude Code tools:
- `Agent` — prevents subagent spawning
- `TeamCreate` — prevents team creation
- `SendMessage` — prevents native messaging

Agents coordinate through the filesystem protocol and `helm-agent` CLI instead. See `src/helm/agent_cli.py`.

## Matrices (advanced)

A matrix manifest defines a batch of experiments as a cross-product of variables (families × sizes × tasks). The matrix generator expands a manifest into individual configs and runs them.

This is for batch experiment suites — if you're running a single experiment, use an example config directly.

Matrix manifests live in your experiment directory (not shipped with Helm).
