# Resources

External dependencies, references, and related work for the Helm project.

---

## Core Dependencies

### Sandbox Agent SDK

**Repository**: https://github.com/rivet-dev/sandbox-agent
**Documentation**: https://sandboxagent.dev/docs

Universal API for coding agents. Provides:
- Agent abstraction (Claude Code, Codex, OpenCode, Amp)
- Event streaming (SSE)
- Permission/question intervention endpoints
- Sandbox integration

**Installation**:
```bash
# TypeScript SDK
npm install sandbox-agent

# Rust binary (standalone server)
curl -fsSL https://releases.rivet.dev/sandbox-agent/latest/install.sh | sh
```

**Key endpoints**:
- `POST /v1/sessions/{id}` — Create session
- `POST /v1/sessions/{id}/messages` — Send message
- `GET /v1/sessions/{id}/events/sse` — Stream events
- `POST /v1/sessions/{id}/permissions/{id}/reply` — Approve/reject action
- `POST /v1/sessions/{id}/questions/{id}/reply` — Answer question

---

## Sandbox Providers

### Daytona
**Website**: https://www.daytona.io/
**Use case**: Cloud sandboxes with automatic git tracking

### E2B
**Website**: https://e2b.dev/
**Use case**: Ephemeral compute sandboxes

### Local Sandboxing
**Claude Code**: Built-in Seatbelt (macOS) / bubblewrap (Linux)
**Anthropic runtime**: https://github.com/anthropic-experimental/sandbox-runtime

---

## Related Research Tools

### Petri
**Repository**: https://github.com/anthropics/petri
**Purpose**: Behavioral evaluation for individual models
**Relevance**: Our dimension evaluation approach is inspired by Petri's 36-dimension judge

Key concepts:
- Auditor agent sets up scenarios
- Target model is evaluated
- Judge scores transcript (separate context)
- 36 behavioral dimensions

### Bloom
**Repository**: https://github.com/anthropics/bloom
**Purpose**: Scenario generation for behavioral testing
**Relevance**: Could inform how we generate coordination scenarios

Four-stage pipeline:
1. Understanding — Analyze target behavior
2. Ideation — Generate diverse scenarios
3. Rollout — Execute conversations
4. Judgment — Score transcripts

---

## Coordination Tools (Not Yet Integrated)

These tools could improve multi-agent coordination, but are held back until we establish baselines. Adding them would confound our ability to measure raw agent behavior.

### Niwa 庭
**Repository**: https://github.com/secemp9/niwa
**Purpose**: Conflict-aware concurrent markdown editing for multiple agents

Key features:
- LMDB-backed document tree (headings → content hierarchy)
- Version tracking per node with agent attribution
- `read_for_edit()` → `edit_node()` pattern detects conflicts automatically
- Three-way merge for non-overlapping changes
- `get_agent_status()` for sub-agents with fresh context
- Full edit history/audit trail
- Claude Code hooks integration

**Why held back**: Niwa would improve coordination quality, which is exactly what we want to measure first. We need baseline observations of how agents coordinate with raw filesystem access before introducing tools that smooth over conflicts.

**Future use**: Could be an experimental treatment—measure dimension scores with/without Niwa to quantify the value of coordination tooling.

---

## Provenance Tracking

### Proof
**Author**: @danshipper
**Purpose**: Agent-native markdown editor with provenance tracking

Features:
- Color-codes human vs AI authorship
- Tracks review depth (red/yellow/green)
- Designed for plan documents

**Relevance**: Could integrate for tracking what orchestrator vs subagents wrote.

---

## Multi-Agent Research

### Kimi K2.5 Agent Swarm
**Technical report**: https://github.com/MoonshotAI/Kimi-K2.5/blob/master/tech_report.pdf
**Blog post**: https://www.kimi.com/blog/kimi-k2-5.html
**Key innovation**: PARL (Parallel-Agent Reinforcement Learning)

Technical details:
- Trainable orchestrator + frozen subagents (decouples credit assignment)
- "Critical Steps" metric (measures latency, not total steps): `CriticalSteps = Σ(S_main(t) + max_i S_sub,i(t))`
- Staged reward shaping to prevent "serial collapse" (λ₁, λ₂ annealed to zero)
- Three reward components: r_parallel (instantiation), r_finish (completion rate), r_perf (task outcome)
- Up to 100 subagents, 1500 tool calls
- Context sharding: bounded subagent contexts with selective output routing

**Key findings relevant to Helm**:
1. Serial collapse is a local optimum—orchestrators default to sequential without incentives
2. Orchestration is a learnable capability, not just engineered rules
3. Zero designed intervention points—no human-in-loop surface (gap we address)
4. Critical-path-style latency measurement is useful for orchestration metrics

**Relevance**: Demonstrates that orchestration is being solved by model capability. Reinforces value of our research question—as coordination becomes learned rather than engineered, how do humans stay in control?

### Google Research: Multi-Agent Architecture-Task Alignment
**Finding**: +81% on parallelizable tasks, -70% on sequential tasks
**Implication**: Architecture-task fit matters more than agent count

### METR: Monitoring for Covert Agent Behavior
**Finding**: More capable models detect covert behavior better
**Relevance**: Monitoring agents could be part of observation layer

---

## Claude Code Internals

### Transcript Storage
**Location**: `~/.claude/projects/{encoded-path}/{session-id}.jsonl`
**Format**: JSONL, one message per line
**Subagents**: `agent-{id}.jsonl` in same directory

### Headless Mode
```bash
claude -p "task" --output-format json --allowedTools "Read,Grep"
```

### TeammateTool (Shipped)
**Status**: Publicly available as of 2026-02-05 (Opus 4.6 launch)
**Documentation**: https://docs.anthropic.com/en/docs/claude-code/teams

Shipped with Claude Code's native agent teams. Provides: shared task list, peer-to-peer mailbox messaging, task dependencies with auto-unblocking, file-locking for claim races.

Key tools: `TeammateTool` (spawnTeam, cleanup), `SendMessage` (message, broadcast, shutdown_request/response, plan_approval_response), `TaskCreate`, `TaskUpdate`, `TaskList`, `TaskGet`.

All coordination is filesystem-based — same approach as Helm.

---

## Theoretical Background

### Cybernetics
- Wiener — Feedback loops
- Ashby — Requisite variety (controller must match system complexity)
- Beer — Viable System Model

**Relevance**: "Helm" comes from *kybernetes* (helmsman). Cybernetic principles inform our thinking about human control of complex systems.

### Multi-Agent Coordination Literature
- Team mental models
- Coordination mechanisms
- Organizational pathologies

**TODO**: Literature review needed.

---

## Research Queue (2026-03-18)

Recent literature to review, ranked by relevance. Full reports in `shoshin-codex/bookmarks/reports/`.

### Directly actionable

| Report | Why it matters | Action |
|--------|---------------|--------|
| `agent-failure-taxonomy-7-patterns.md` | 7 empirical failure modes from 1600+ sessions. Phantom verification, hollow report, shortcut spiral are detectable from traces alone. Multi-agent propagation (one agent's hollow report → another's confidence mirage) unexplored. | Map to trace features → prototype detection as judging dimensions |
| `openai-argo-interpretable-rubrics-from-reward-models.md` | RL-generated rubrics that audit black-box reward models. Surfaced population bias: generic users reward sycophancy, experts reward calibration. | Apply to Helm's judge pipeline — extract rubrics to verify judges measure what we intend |
| `nlrl-on-policy-self-distillation-language-rl.md` | 5 groups converging: language feedback replaces scalar rewards. Helm's judge outputs are already language — could feed directly into RL, collapsing judge and training pipelines. SDPO (2601.20802) handles credit assignment for tool use. All papers are single-agent; multi-agent is our gap. | Read SDPO. Design experiment: language judge output as direct RL signal |
| `steganographic-gap-llm-monitoring-metric.md` | Detects covert encoded reasoning without reference distribution. Agents could hide info in traces/comments/artifacts. Complements Goodfire's frozen-probe (internal) with external output monitoring. | Add as candidate monitoring dimension for inter-agent channels |

### Background — algorithm and training context

| Report | Why it matters | Action |
|--------|---------------|--------|
| `state-of-rl-for-reasoning-llms-overview.md` | 10-method overview (REINFORCE → ScaleRL). Post-DeepSeek-R1 trend is critic-free. Dr.GRPO and DAPO fix length bias and entropy collapse. Triangulates with agentic RL survey (what to optimize) and rubric-based RL (what to reward). Blog fetch failed — read original. | Read https://aweers.de/blog/2026/rl-for-llms/ for open problems |
| `cato-coding-agents-text-optimizers.md` | Agent-based selection replaces hand-designed heuristics (MAP-Elites, Pareto). Beats AlphaEvolve 2/3. Paper not yet public. Readable selection rationale aligns with observability. | Watch for paper drop. Compare against GEPA |
| `autoresearch-rl-autonomous-rl-post-training.md` | Config-only autoresearch on prime-rl. rollouts=4 > rollouts=8; constant LR > cosine. Validated starting config for prime-rl experiments. | Use best config as starting point |

### Key reports from March 13 batch (still current)

- `agentic-rl-survey.md` — POMDP formalization; credit assignment as primary bottleneck; 4 multi-agent RL approaches
- `when-multi-agent-helps-vs-hurts.md` — 45% single-agent threshold; 17x error amplification (independent MAS); predictive model R²=0.524
- `goodfire-interp-scaled-rl.md` — Frozen-probe anti-evasion; 90x cheaper than LLM-as-judge; probe transfer survives RL
- `claude-code-swarm-protocol-reverse-engineered.md` — TeammateTool internals; WebSocket observation; 5 orchestration patterns
- `karl-trained-stopping-research-loops.md` — Stopping as behavioral signal; trajectory length distributions; compression as observation point

### Cross-cutting themes

1. **Language as reward** — NLRL + ARGO suggest judge outputs could become training signal directly
2. **Observable failure modes** — failure taxonomy + steganographic gap give trace-detectable signals
3. **Autonomy-safety spectrum** — config-only (autoresearch-rl) vs code-editing (Karpathy) vs agent selection (CATO) produce different behavioral signatures
4. **Population effects** — who provides reward signal shapes what gets learned (ARGO Population A/B)

---

## Research Notes

### On "Baseline" Behavior (2026-01-30)

The Kimi K2.5 technical report revealed that orchestration is increasingly a learned capability, not just emergent behavior. Their PARL framework trains orchestrators to parallelize via RL with staged reward shaping.

**Implications for Helm:**
- The "raw coordination" we observe may reflect trained policies, not natural behavior
- Serial collapse (defaulting to sequential execution) is a known failure mode
- We should probe whether agents exhibit learned orchestration patterns
- Critical-path-inspired metrics are useful for measuring latency vs total work
- Parallelization Calibration added as candidate dimension

**What stays the same:**
- Niwa still held back as treatment (explicit tooling vs learned capability)
- Dimension measurements still valuable—comparing model capabilities
- Human-in-loop gap remains our research opening (PARL has zero intervention surfaces)

**Framing shift:** We're not measuring "natural" coordination—we're measuring *model capability differences* in coordination. The baseline isn't pristine; it's whatever coordination-relevant training each model received. This is still interesting and measurable.

---
