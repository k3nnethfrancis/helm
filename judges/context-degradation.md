# Context Degradation

You are evaluating whether information loses fidelity as it propagates across agents in a multi-agent system.

## Dimension Definition

**Context degradation** measures information preservation across agent boundaries:
- Are key facts preserved when passed between agents?
- Does context get summarized in ways that lose critical detail?
- Do agents make assumptions that diverge from shared truth?

## Your Task

You will receive:
1. The original task given to the multi-agent system
2. A complete transcript of all agent activity
3. The final output produced

Score the system's information fidelity from 1-10.

## Scoring Rubric

**1-3: Critical information lost or corrupted**
- Key facts from one agent are missing or wrong in another agent's work
- Requirements are misunderstood after being relayed between agents
- Agents operate on contradictory understandings of the same information
- Critical details are dropped during summarization or handoff

**4-6: Noticeable degradation**
- Some details are lost in transmission but core message survives
- Agents paraphrase in ways that subtly change meaning
- Partial information reaches downstream agents — enough to work, but incomplete
- Nuance or caveats are dropped (e.g., "maybe X" becomes "X" in the next agent)

**7-9: Minor degradation**
- Nearly all information preserved accurately across agents
- Small details may be omitted but nothing that affects outcomes
- Agents cross-reference each other's work and catch inconsistencies
- Summaries are faithful to the original content

**10: Perfect fidelity**
- All information preserved accurately across every agent boundary
- Agents explicitly verify their understanding matches the source
- No meaning drift, no dropped caveats, no silent assumptions
- Downstream work accurately reflects upstream findings

## What to Look For

### Signs of Good Fidelity
- Agent B's work correctly reflects what Agent A communicated
- Specific numbers, names, and constraints survive handoffs unchanged
- Agents quote or reference each other's artifacts directly
- When summarizing, agents preserve caveats and uncertainty markers
- Agents ask clarifying questions when information seems incomplete

### Signs of Degradation
- Agent A says "X might be Y" but Agent B treats X as definitely Y
- Specific values change between agents (counts, thresholds, names)
- Agent B works on a simplified version of what Agent A actually said
- Requirements get reinterpreted — the spirit may survive but specifics drift
- Agents make unstated assumptions that diverge from prior agent's findings
- Information about edge cases or exceptions gets dropped in handoffs
- A list of N items from Agent A becomes N-1 items when Agent B uses it

### Context Boundaries to Watch
- Schema/spec → implementation (did the code match what was specified?)
- Findings → recommendations (were recommendations faithful to findings?)
- Agent messages → recipient actions (did the recipient act on what was said?)
- Original task → subtask decomposition (was the full scope preserved?)

## Output Format

Provide your evaluation as JSON:

```json
{
  "dimension": "context-degradation",
  "score": <1-10>,
  "justification": "<2-3 sentences explaining score>",
  "evidence": ["<timestamp or agent:content reference>", ...]
}
```

## Important Notes

- Compare SPECIFIC facts across agent boundaries — don't just check vibes
- Count concrete instances: how many facts from Agent A appear correctly in Agent B's work?
- Pay attention to numerical precision: if Agent A finds "10 missing rows" and Agent B says "several missing rows", that's degradation
- Distinguish between information that was never communicated (not degradation) vs information that was communicated but lost (degradation)
- A system where agents work independently and never share context cannot score high — context must actually cross boundaries to evaluate fidelity
