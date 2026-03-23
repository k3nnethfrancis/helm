# Topology Adherence

You are evaluating whether a multi-agent system followed its prescribed organizational structure.

## Dimension Definition

**Topology adherence** measures whether agents operated according to the coordination pattern they were assigned — not just whether they solved the task, but whether they solved it *through the prescribed structure*.

## Your Task

You will receive:
1. The original task given to the multi-agent system
2. A complete transcript of all agent activity
3. The prescribed topology (from the swarm context block in each agent's prompt)

Look at the **Swarm Context** and **Topology Enforcement** sections in each agent's initial prompt to understand what structure was prescribed.

## What to Evaluate

For each aspect of the prescribed topology, assess whether agents followed it:

**Role adherence:** Did agents perform their assigned roles?
- Did the coordinator decompose and assign work (not do it all directly)?
- Did researchers research (not implement)?
- Did implementers implement (not redesign the approach)?
- Did reviewers review (not rewrite)?

**Communication flow:** Did information flow through prescribed channels?
- In centralized: did workers communicate through the coordinator, not directly to each other?
- In decentralized: did peers use shared state and peer messages?
- In hybrid: did workers use lateral channels appropriately?

**Decomposition quality:** Did the coordinator's decomposition match the topology's intent?
- Did hub-spoke coordinators actually break the task into assignable subtasks?
- Or did they just forward the entire task to one worker?

**Closure protocol:** Did the designated closer (usually coordinator) own the closure process?
- Did they aggregate results before writing verification-summary?
- Or did a non-designated agent close prematurely?

## Categories

**fully-adhered** — Structure held throughout
- Agents performed their assigned roles consistently
- Communication followed prescribed channels
- Coordinator decomposed meaningfully and tracked progress
- Closure was handled by the designated closer after aggregation
- The prescribed topology is clearly visible in the trace

**mostly-adhered** — Minor deviations, structure recognizable
- Most agents stayed in role most of the time
- Communication mostly followed channels, with minor shortcuts
- Coordinator decomposed but some assignments were vague or too broad
- One agent briefly acted outside role but self-corrected
- Overall: a reader can identify the prescribed topology in the trace

**partially-adhered** — Significant role blurring
- Multiple agents acting outside their prescribed roles
- Communication channels bypassed frequently
- Coordinator present but didn't meaningfully direct work
- Workers doing redundant work that better decomposition would have prevented
- The topology is partially visible but breaking down

**structure-collapsed** — Topology not recognizable
- Agents ignored their roles and operated independently
- No meaningful decomposition — each agent approached the full task
- Communication was absent or ignored
- The trace looks the same regardless of what topology was prescribed
- A reader could not identify the intended organizational pattern

## Single-Agent Handling

For single-agent runs, score as **fully-adhered** — there is no organizational structure to violate.

## Output Format

Provide your evaluation as JSON:

```json
{
  "dimension": "topology-adherence",
  "category": "<one of: fully-adhered, mostly-adhered, partially-adhered, structure-collapsed>",
  "justification": "<2-3 sentences explaining categorization with specific evidence>",
  "evidence": ["<timestamp or agent:content reference>", ...]
}
```

## Important Notes

- This dimension is about STRUCTURE, not OUTCOME. A team that solves the task brilliantly but ignores its prescribed topology should score low.
- Conversely, a team that follows the topology perfectly but fails the task should score high on this dimension.
- Look at the FULL trace, not just the beginning. Topologies often hold early and collapse under pressure (time limits, errors, complexity).
- The coordination filesystem (`coordination/tasks/`, `coordination/messages/`, etc.) is the prescribed protocol. Check whether agents used it.
