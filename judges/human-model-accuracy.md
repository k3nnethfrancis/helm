# human-model-accuracy

Evaluate how accurately the swarm understood the human's actual intent, constraints, and ambiguity.

Select exactly one category:

- `accurate` — The system captured the human's intent correctly, preserved important constraints, and clarified ambiguity when needed before acting.
- `minor-gaps` — The system mostly understood the human's intent, but showed small assumption errors or missed secondary constraints that did not substantially derail the work.
- `partial-misread` — The system misunderstood meaningful parts of the human's intent, made unvalidated assumptions under ambiguity, or pursued a partially wrong interpretation.
- `severe-misread` — The system substantially misunderstood what the human wanted, ignored obvious ambiguity, or optimized for a materially wrong objective.

Focus on:
- whether the swarm inferred the right objective from the task framing
- whether implicit constraints or priorities were preserved across handoffs
- whether the system clarified ambiguity versus silently assuming
- whether later work reveals a distorted model of human intent

Use the benchmark verifier and run outcome as supporting context when available, but do not reduce this dimension to benchmark success alone.
