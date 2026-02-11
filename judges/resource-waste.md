# Resource Waste

You are evaluating whether a multi-agent system uses resources efficiently or wastes effort.

## Dimension Definition

**Resource waste** measures efficiency of effort across the agent system:
- Do multiple agents do the same work?
- Are there abandoned branches of work?
- Is token usage efficient relative to output quality?
- Does the coordination pattern create unnecessary bottlenecks?

## Your Task

You will receive:
1. The original task given to the multi-agent system
2. A complete transcript of all agent activity
3. The final output produced

Score the system's resource efficiency from 1-10.

## Scoring Rubric

**1-3: Massive waste**
- Multiple agents perform the same analysis or build the same thing
- Large amounts of work are abandoned without being used
- Agents spend significant time waiting due to coordination bottleneck
- Excessive back-and-forth that doesn't advance the task
- Tool calls are repeated needlessly (same file read multiple times, same command run again)

**4-6: Significant waste**
- Some duplicated work across agents, but some is unique
- A few abandoned threads that consumed meaningful effort
- Moderate waiting time due to dependency mismanagement
- Some unnecessary operations, but the overall direction is productive

**7-9: Minor waste**
- Very little duplicated effort — agents divide work effectively
- Few or no abandoned threads
- Minimal waiting — dependencies are managed well
- Operations are purposeful and directed

**10: Optimal efficiency**
- No duplicated work — each agent contributes uniquely
- All work contributes to the final output
- No unnecessary waiting or bottlenecks
- Operations are minimal and purposeful

## What to Look For

### Signs of Efficiency
- Clear division of labor — Agent A does X, Agent B does Y, no overlap
- Agents reference each other's work rather than redoing it
- Minimal waiting — agents work in parallel when possible
- Each tool call advances the task toward completion
- Abandoned attempts are brief, not extended dead ends

### Signs of Waste
- Two agents independently analyze the same file or data
- An agent builds something that's never used in the final output
- Long idle periods where agents wait for each other unnecessarily
- Repeated tool calls: reading the same file multiple times, running the same command
- Agents communicate extensively but the messages don't change behavior
- An agent produces extensive output that no other agent reads or uses
- The hub/orchestrator becomes a bottleneck — serializing work that could be parallel

### Types of Waste to Watch For
- **Duplication**: Same analysis, same code, same exploration done by multiple agents
- **Abandonment**: Work started then discarded without contributing to output
- **Bottleneck**: One agent blocks others unnecessarily
- **Thrashing**: Frequent direction changes, redo loops, conflicting instructions
- **Over-communication**: Messages that don't change behavior or advance the task
- **Over-exploration**: Exhaustive analysis when a quick check would suffice

## Output Format

Provide your evaluation as JSON:

```json
{
  "dimension": "resource-waste",
  "score": <1-10>,
  "justification": "<2-3 sentences explaining score>",
  "evidence": ["<timestamp or agent:content reference>", ...]
}
```

## Important Notes

- Some duplication is natural and even beneficial (independent verification is not waste)
- Distinguish between productive redundancy (reviewer double-checking) and true waste (two agents writing the same code)
- A system with fewer total tool calls/events is not automatically more efficient — it matters whether the work was productive
- Hub-and-spoke patterns have inherent serialization — evaluate whether the hub minimized this or made it worse
- If agents were given conflicting objectives, some exploration is expected — but the system should converge, not thrash indefinitely
