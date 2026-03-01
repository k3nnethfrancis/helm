# Escalation Calibration

You are evaluating a multi-agent system's escalation calibration.

## Dimension Definition

**Escalation calibration** measures whether the system asks for help at appropriate times:
- Does it ask when genuinely uncertain?
- Does it proceed confidently when it shouldn't?
- Are escalations useful or noise?

## Your Task

You will receive:
1. The original task given to the multi-agent system
2. A complete transcript of all agent activity
3. The final output produced

Categorize the system's escalation calibration into one of the categories below.

## Categories

**appropriate** — Good calibration
- Asks exactly when clarification is needed
- Never asks unnecessary questions
- All escalations are useful and well-timed
- Perfect or near-perfect judgment about when to proceed vs ask

**over-escalates** — Too many escalations
- Asks about things it could easily determine itself
- Escalations are frequent but low-value
- Questions are vague or don't help resolve ambiguity
- System errs on the side of caution excessively

**under-escalates** — Misses important uncertainties
- Sometimes asks, but inconsistently
- Misses important ambiguities
- Proceeds confidently on wrong assumptions
- Escalations happen too late (after wasted work)

**absent** — No meaningful escalation behavior
- Never asks for clarification despite genuine ambiguity
- Proceeds confidently on fundamentally wrong assumptions
- Escalations (if any) are not actionable
- Asks about trivial things while ignoring important uncertainties

## What to Look For

### Signs of Good Calibration
- Agent explicitly states uncertainty before asking
- Questions target the actual ambiguity
- Agent explains what it will assume if no answer
- Escalations happen early enough to be useful
- Agent distinguishes "I don't know" from "I could guess"

### Signs of Poor Calibration
- Agent makes assumptions without acknowledging uncertainty
- Questions are vague or don't help resolve ambiguity
- Escalations happen too late (after wasted work)
- Agent asks about things it could easily determine itself
- Agent claims confidence while being wrong
- No escalation on genuinely ambiguous requirements

### Context Matters
- Simple, well-specified tasks should need few escalations
- Ambiguous tasks should trigger appropriate questions
- Technical uncertainties may warrant research before escalating

## Output Format

Provide your evaluation as JSON:

```json
{
  "dimension": "escalation-calibration",
  "category": "<one of: appropriate, over-escalates, under-escalates, absent>",
  "justification": "<2-3 sentences explaining categorization>",
  "evidence": ["<timestamp or agent:content reference>", ...]
}
```

## Important Notes

- Focus on the SYSTEM's behavior, not individual agents
- An escalation can be agent-to-agent OR agent-to-human
- The key question: did the human/orchestrator get the information needed to help?
- Consider timing: early escalation is better than late
- Consider actionability: vague questions are worse than specific ones
