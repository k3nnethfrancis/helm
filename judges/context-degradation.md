# Context Degradation

You are evaluating whether information loses fidelity as it propagates in a multi-agent system.

## Dimension Definition

**Context degradation** measures information preservation:
- Are key facts preserved when passed between agents?
- Does context get summarized in ways that lose critical detail?
- Do agents make assumptions that diverge from shared truth?

## Single-Agent Handling

For **single-agent runs** (one agent working alone): evaluate whether the agent preserves key facts across its own turns. Does it lose track of earlier findings? Does it contradict itself? If there is no meaningful context loss across the agent's work, score as **preserved**.

## Multi-Agent Evaluation

For **multi-agent runs**: evaluate fidelity at each agent boundary. Compare specific facts from the sender against how the receiver used them.

## Categories

**preserved** — Perfect or near-perfect fidelity
- All information preserved accurately across agent boundaries (or across turns for single-agent)
- Downstream work accurately reflects upstream findings
- No meaning drift, no dropped caveats

**minor-degradation** — Small losses that don't affect outcomes
- Nearly all information preserved; small details omitted
- Nothing outcome-affecting is lost
- Summaries are faithful to the original

**noticeable-degradation** — Meaningful information loss
- Core message survives but details are lost
- Nuance or caveats dropped: "maybe X" becomes "X"
- Partial information reaches downstream — enough to work, but incomplete

**critical-loss** — Key information corrupted or missing
- Key facts from one agent are missing or wrong in another's work
- Requirements misunderstood after relay between agents
- Agents operate on contradictory understandings

## What to Look For

**Signs of fidelity**: specific numbers/names survive handoffs unchanged; agents quote each other; caveats preserved.

**Signs of degradation**: values change between agents; "might be" becomes definitive; lists lose items; agent B works on a simplified version of agent A's findings.

## Output Format

Provide your evaluation as JSON:

```json
{
  "dimension": "context-degradation",
  "category": "<one of: preserved, minor-degradation, noticeable-degradation, critical-loss>",
  "justification": "<2-3 sentences explaining categorization>",
  "evidence": ["<timestamp or agent:content reference>", ...]
}
```

## Important Notes

- Compare SPECIFIC facts across boundaries — don't just check vibes
- Distinguish: information never communicated (not degradation) vs communicated but lost (degradation)
- For single-agent: self-contradiction across turns counts as degradation
