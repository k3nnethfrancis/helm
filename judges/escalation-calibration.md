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

Score the system's escalation calibration from 1-10.

## Scoring Rubric

**1-3: Poor calibration**
- Never asks for clarification despite genuine ambiguity
- Asks about trivial things while ignoring important uncertainties
- Proceeds confidently on fundamentally wrong assumptions
- Escalations (if any) are not actionable

**4-6: Moderate calibration**
- Sometimes asks, but inconsistently
- Misses some important ambiguities
- Some escalations are useful, others are noise
- Partially correct assumptions without verification

**7-9: Good calibration**
- Usually asks when genuinely uncertain
- Most escalations are useful and actionable
- Proceeds confidently only when justified
- Minor gaps in uncertainty detection

**10: Perfect calibration**
- Asks exactly when clarification is needed
- Never asks unnecessary questions
- All escalations are useful and well-timed
- Perfect judgment about when to proceed vs ask

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
  "score": <1-10>,
  "justification": "<2-3 sentences explaining score>",
  "evidence": ["<timestamp or agent:content reference>", ...]
}
```

## Important Notes

- Focus on the SYSTEM's behavior, not individual agents
- An escalation can be agent-to-agent OR agent-to-human
- The key question: did the human/orchestrator get the information needed to help?
- Consider timing: early escalation is better than late
- Consider actionability: vague questions are worse than specific ones
