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
4. Critical Steps metric adopted for our dimension measurements

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

## Research Notes

### On "Baseline" Behavior (2026-01-30)

The Kimi K2.5 technical report revealed that orchestration is increasingly a learned capability, not just emergent behavior. Their PARL framework trains orchestrators to parallelize via RL with staged reward shaping.

**Implications for Helm:**
- The "raw coordination" we observe may reflect trained policies, not natural behavior
- Serial collapse (defaulting to sequential execution) is a known failure mode
- We should probe whether agents exhibit learned orchestration patterns
- Critical Steps metric adopted for measuring latency vs total work
- Parallelization Calibration added as candidate dimension

**What stays the same:**
- Niwa still held back as treatment (explicit tooling vs learned capability)
- Dimension measurements still valuable—comparing model capabilities
- Human-in-loop gap remains our research opening (PARL has zero intervention surfaces)

**Framing shift:** We're not measuring "natural" coordination—we're measuring *model capability differences* in coordination. The baseline isn't pristine; it's whatever coordination-relevant training each model received. This is still interesting and measurable.

---

