"""HTML transcript viewer for Helm experiment rollouts.

Renders full.json transcripts into browsable single-file HTML with:
- Per-agent transcript panels (independent sessions, not a shared chat)
- 2x2 grid layout for simultaneous multi-agent viewing
- Coordination log as a left-side feed
- Full tool call inputs and results with expand/collapse
- Markdown rendering of agent reasoning
- Metadata in a collapsible top bar
"""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

TOOL_RESULT_COLLAPSE_THRESHOLD = 500
TEXT_COLLAPSE_THRESHOLD = 600


def _escape(text: str) -> str:
    return html.escape(str(text))


def _render_markdown(text: str) -> str:
    """Lightweight markdown to HTML."""
    import re as _re

    escaped = _escape(text)
    lines = escaped.split("\n")
    out: list[str] = []
    in_code_block = False
    in_list = False

    for line in lines:
        if line.strip().startswith("```"):
            if in_code_block:
                out.append("</code></pre>")
                in_code_block = False
            else:
                lang = line.strip().removeprefix("```").strip()
                out.append(f"<pre><code class='lang-{_escape(lang)}'>")
                in_code_block = True
            continue
        if in_code_block:
            out.append(line)
            continue
        if in_list and not _re.match(r"^\s*[-*]\s", line) and line.strip():
            out.append("</ul>")
            in_list = False
        m = _re.match(r"^(#{1,6})\s+(.*)", line)
        if m:
            level = len(m.group(1))
            out.append(f"<h{level} class='md-h'>{m.group(2)}</h{level}>")
            continue
        m = _re.match(r"^(\s*)[-*]\s+(.*)", line)
        if m:
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{m.group(2)}</li>")
            continue
        if not line.strip():
            if in_list:
                out.append("</ul>")
                in_list = False
            out.append("<br>")
            continue
        out.append(line)

    if in_code_block:
        out.append("</code></pre>")
    if in_list:
        out.append("</ul>")

    result = "\n".join(out)
    result = _re.sub(r"`([^`]+)`", r"<code>\1</code>", result)
    result = _re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", result)
    result = _re.sub(r"\*(.+?)\*", r"<em>\1</em>", result)
    # Strip leading/trailing <br> tags that create empty space
    result = _re.sub(r"^(\s*<br>\s*)+", "", result)
    result = _re.sub(r"(\s*<br>\s*)+$", "", result)
    return result


def _render_tool_inputs(tool_args: dict[str, Any]) -> str:
    if not tool_args:
        return ""
    rows = []
    for key, val in tool_args.items():
        val_str = _escape(str(val))
        if len(str(val)) > 200:
            val_str = (
                f"<details><summary class='trunc'>"
                f"{_escape(str(val)[:200])}\u2026</summary>"
                f"<pre class='expanded'>{val_str}</pre></details>"
            )
        else:
            val_str = f"<code>{val_str}</code>"
        rows.append(
            f"<div class='tool-param'>"
            f"<span class='tool-key'>{_escape(key)}</span>"
            f"<span class='tool-val'>{val_str}</span></div>"
        )
    return f"<div class='tool-params'>{''.join(rows)}</div>"


def _render_tool_result(output: str, is_error: bool = False) -> str:
    cls = "tool-err" if is_error else "tool-out"
    label = "error" if is_error else "output"
    escaped = _escape(output)
    if len(output) > TOOL_RESULT_COLLAPSE_THRESHOLD:
        return (
            f"<details class='{cls}'>"
            f"<summary>{label} \u2014 {len(output):,} chars</summary>"
            f"<pre>{escaped}</pre></details>"
        )
    return f"<div class='{cls}'><pre>{escaped}</pre></div>"


def _render_event(item: dict[str, Any]) -> str:
    """Render a single transcript event as HTML."""
    event_type = item.get("event_type", "")
    timestamp = str(item.get("timestamp", ""))
    ts = timestamp[11:19] if len(timestamp) >= 19 else timestamp

    if event_type in ("item.delta", "item.started", "rate_limit_event"):
        return ""

    data = item.get("data", {})
    if not isinstance(data, dict):
        data = {}

    body = ""
    cls = "ev"

    if event_type == "item.completed":
        item_data = data.get("item", {})
        if not isinstance(item_data, dict):
            item_data = {}
        role = item_data.get("role", "unknown")
        parts = []
        for part in item_data.get("content", []):
            if not isinstance(part, dict):
                continue
            ptype = part.get("type", "")
            if ptype == "text":
                text = str(part.get("text", ""))
                if text.strip():
                    rendered = _render_markdown(text)
                    if len(text) > TEXT_COLLAPSE_THRESHOLD:
                        parts.append(
                            f"<div class='prose prose-clipped'>"
                            f"<div class='prose-content'>{rendered}</div>"
                            f"</div>"
                        )
                    else:
                        parts.append(f"<div class='prose'>{rendered}</div>")
            elif ptype in ("tool_call", "tool_use"):
                name = part.get("name", "unknown")
                raw = part.get("arguments", part.get("input", {}))
                if isinstance(raw, str):
                    try:
                        args = json.loads(raw)
                    except (json.JSONDecodeError, TypeError):
                        args = {}
                else:
                    args = raw or {}
                inp = (
                    _render_tool_inputs(args)
                    if isinstance(args, dict)
                    else ""
                )
                parts.append(
                    f"<div class='tool-use'>"
                    f"<span class='tool-name'>{_escape(name)}</span>"
                    f"{inp}</div>"
                )
            elif ptype == "tool_result":
                out = str(part.get("output", part.get("text", "")))
                is_err = part.get("is_error", False)
                if out.strip():
                    parts.append(_render_tool_result(out, is_err))
        if role == "user":
            cls = "ev ev-result"
        body = "".join(parts)
        if not body.strip():
            return ""
    elif event_type == "session.started":
        body = "session started"
        cls = "ev ev-meta"
    elif event_type == "session.ended":
        body = "session ended"
        cls = "ev ev-meta"
    elif event_type == "permission.requested":
        body = f"permission: <code>{_escape(str(data.get('action', '')))}</code>"
        cls = "ev ev-meta"
    elif event_type == "permission.resolved":
        body = f"resolved: {_escape(str(data.get('resolution', '')))}"
        cls = "ev ev-meta"
    else:
        body = f"{_escape(event_type)}"
        cls = "ev ev-meta"

    return (
        f"<div class='{cls}'>"
        f"<time>{_escape(ts)}</time>"
        f"<div class='ev-body'>{body}</div></div>"
    )


def _build_coordination_html(
    messages: list[dict[str, Any]],
    agent_ids: list[str],
) -> str:
    """Build the coordination log panel."""
    if not messages:
        return "<div id='coord' class='coord'><div class='coord-empty'>No coordination messages</div></div>"
    rows = []
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        content_raw = str(msg.get("content", ""))
        msg_type = str(
            msg.get("message_type", msg.get("type", "")) or ""
        )
        if msg_type == "status_update" and '"family"' in content_raw[:50]:
            continue

        ts = str(msg.get("timestamp", ""))[11:19]
        sender = str(msg.get("sender") or "")
        recipient = str(msg.get("recipient") or "")

        if msg_type == "peer_message" and not sender:
            if "From:" in content_raw[:30]:
                parts = content_raw.split(" ", 6)
                for j, p in enumerate(parts):
                    if p == "From:" and j + 1 < len(parts):
                        sender = parts[j + 1].rstrip(",")
                    if p == "To:" and j + 1 < len(parts):
                        recipient = parts[j + 1].rstrip(",")

        # Type indicator
        indicator = {
            "peer_message": "\u2192",
            "status_update": "\u2022",
            "completion_signal": "\u2713",
        }.get(msg_type, "\u2022")

        route = ""
        if sender or recipient:
            s = sender or "\u2014"
            r = recipient or "\u2014"
            route = f"<span class='log-route'>{_escape(s)} \u2192 {_escape(r)}</span>"

        # Content: single rendered blob, clipped if long
        rendered_content = _render_markdown(content_raw)
        if len(content_raw) > 120:
            content_cell = (
                f"<div class='log-clipped'>"
                f"<div class='log-rendered'>{rendered_content}</div></div>"
            )
        else:
            content_cell = (
                f"<div class='log-rendered log-short'>"
                f"{rendered_content}</div>"
            )

        type_cls = {
            "peer_message": "log-msg",
            "completion_signal": "log-done",
        }.get(msg_type, "")

        rows.append(
            f"<div class='log-entry {type_cls}'>"
            f"<time>{_escape(ts)}</time>"
            f"<span class='log-ind'>{indicator}</span>"
            f"{route}"
            f"<span class='log-type'>{_escape(msg_type)}</span>"
            f"<div class='log-body'>{content_cell}</div>"
            f"</div>"
        )

    return (
        f"<div id='coord' class='coord'>"
        f"<div class='coord-head'>"
        f"<span>coordination</span>"
        f"<span class='coord-count'>{len(rows)}</span></div>"
        f"<div class='coord-scroll'>{''.join(rows)}</div></div>"
    )


def render_html(
    transcript: dict[str, Any],
    run_data: dict[str, Any] | None = None,
    scores: list[dict[str, Any]] | None = None,
    verification: dict[str, Any] | None = None,
) -> str:
    """Render a full experiment transcript as a self-contained HTML file."""
    experiment_name = transcript.get("experiment_name", "Unknown")
    experiment_id = transcript.get("experiment_id", "")
    agents = transcript.get("agents", {})
    agent_ids = list(agents.keys()) if isinstance(agents, dict) else []
    coordination_messages = transcript.get("coordination_messages", [])

    # Per-agent event lists
    per_agent_events: dict[str, list[str]] = {}
    for agent_id in agent_ids:
        agent_data = agents.get(agent_id, {})
        if not isinstance(agent_data, dict):
            continue
        items = agent_data.get("items", [])
        if not isinstance(items, list):
            continue
        events = []
        for item in sorted(
            items, key=lambda x: str(x.get("timestamp", ""))
        ):
            rendered = _render_event(item)
            if rendered:
                events.append(rendered)
        per_agent_events[agent_id] = events

    # Agent panels
    panels_html = []
    for agent_id in agent_ids:
        events = per_agent_events.get(agent_id, [])
        n = len(events)
        role = ""
        if run_data:
            for a in run_data.get("agents", []):
                if a.get("id") == agent_id:
                    role = a.get("role") or ""
                    break
        role_str = f" <span class='panel-role'>{_escape(role)}</span>" if role else ""
        panels_html.append(
            f"<div class='panel' data-agent='{_escape(agent_id)}'>"
            f"<div class='panel-head'>"
            f"<span class='panel-label'>{_escape(agent_id)}{role_str}</span>"
            f"<span class='panel-count'>{n}</span></div>"
            f"<div class='panel-scroll'>{''.join(events)}</div></div>"
        )

    # Coordination log HTML (just the entries, no wrapper)
    coord_html = _build_coordination_html(coordination_messages, agent_ids)

    # Left sidebar: metadata section above coordination log
    left_parts = []

    # Run info
    left_parts.append(
        f"<div class='left-section'>"
        f"<div class='left-label'>experiment</div>"
        f"<div class='left-title'>{_escape(experiment_name)}</div>"
    )
    if run_data:
        run = run_data.get("run", {})
        outcome = str(run.get("outcome", "?"))
        dur = run.get("duration_seconds")
        dur_str = f"{dur:.0f}s" if dur else ""
        left_parts.append(
            f"<div class='meta-row'>"
            f"<span class='meta-key'>outcome</span>"
            f"<span class='meta-val'>{_escape(outcome)}</span></div>"
        )
        if dur_str:
            left_parts.append(
                f"<div class='meta-row'>"
                f"<span class='meta-key'>duration</span>"
                f"<span class='meta-val'>{dur_str}</span></div>"
            )
    left_parts.append("</div>")

    # Verification
    if verification:
        status = verification.get("status", "?")
        score = verification.get("score", "?")
        reason = verification.get("reason", "")
        v_cls = "verify-pass" if status == "pass" else "verify-fail"
        left_parts.append(
            f"<div class='left-section {v_cls}'>"
            f"<div class='left-label'>verification</div>"
            f"<div class='meta-row'>"
            f"<span class='meta-key'>status</span>"
            f"<span class='meta-val'>{_escape(status)}</span></div>"
            f"<div class='meta-row'>"
            f"<span class='meta-key'>score</span>"
            f"<span class='meta-val'>{score}</span></div>"
            f"<div class='meta-detail'>{_escape(reason)}</div>"
            f"</div>"
        )

    # Behavioral scores
    if scores:
        score_rows = []
        for s in scores:
            dim = s.get("dimension", "")
            cat = s.get("category", "")
            score_rows.append(
                f"<div class='meta-row'>"
                f"<span class='meta-key'>{_escape(dim)}</span>"
                f"<span class='meta-val'>{_escape(cat)}</span></div>"
            )
        left_parts.append(
            f"<div class='left-section'>"
            f"<div class='left-label'>behavioral scores</div>"
            f"{''.join(score_rows)}</div>"
        )

    left_html = "".join(left_parts)

    # Header bar: just title + agent toggles
    toggles = []
    for aid in agent_ids:
        toggles.append(
            f"<label class='toggle'>"
            f"<input type='checkbox' data-agent='{_escape(aid)}' checked>"
            f" {_escape(aid)}</label>"
        )
    header_html = (
        f"<div class='hdr-title'>{_escape(experiment_name)}</div>"
        f"<div class='hdr-toggles'>{''.join(toggles)}</div>"
    )

    return _TEMPLATE.format(
        title=_escape(experiment_name),
        header=header_html,
        left_sidebar=left_html,
        coordination=coord_html,
        panels="".join(panels_html),
        agent_ids_json=json.dumps(agent_ids),
    )


def render_experiment(experiment_dir: Path) -> str:
    """Load an experiment directory and render to HTML."""
    transcript_path = experiment_dir / "transcripts" / "full.json"
    if not transcript_path.exists():
        raise FileNotFoundError(f"No transcript at {transcript_path}")

    with open(transcript_path) as f:
        transcript = json.load(f)

    run_data = None
    rd_path = experiment_dir / "run_data.json"
    if rd_path.exists():
        with open(rd_path) as f:
            run_data = json.load(f)

    scores = None
    scores_path = experiment_dir / "scores.json"
    if scores_path.exists():
        with open(scores_path) as f:
            raw = json.load(f)
            scores = raw if isinstance(raw, list) else raw.get("scores", [])

    verification = None
    tv_path = experiment_dir / "evaluation" / "task_verification.json"
    if tv_path.exists():
        with open(tv_path) as f:
            verification = json.load(f)

    return render_html(transcript, run_data, scores, verification)


_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} — Helm</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:ital,wght@0,400;0,500;0,600&family=IBM+Plex+Sans:wght@400;500;600&display=swap');

:root {{
  --bg: #0c0c0c;
  --bg-1: #121212;
  --bg-2: #181818;
  --bg-3: #1e1e1e;
  --border: #2a2a2a;
  --border-strong: #363636;
  --text: #d4d4d4;
  --text-dim: #8a8a8a;
  --text-faint: #5a5a5a;
  --text-bright: #f0f0f0;
  --green: #2d4a2d;
  --green-text: #a0d0a0;
  --red: #4a2d2d;
  --red-text: #d0a0a0;
  --mono: 'IBM Plex Mono', 'SF Mono', 'Cascadia Code', 'Fira Code', monospace;
  --sans: 'IBM Plex Sans', -apple-system, system-ui, sans-serif;
  --radius: 3px;
}}

* {{ margin: 0; padding: 0; box-sizing: border-box; }}

html, body {{ height: 100%; overflow: hidden; }}

body {{
  font-family: var(--sans);
  background: var(--bg);
  color: var(--text);
  display: flex;
  flex-direction: column;
}}

/* Scrollbar styling */
::-webkit-scrollbar {{ width: 6px; height: 6px; }}
::-webkit-scrollbar-track {{ background: transparent; }}
::-webkit-scrollbar-thumb {{ background: var(--border); border-radius: 3px; }}
::-webkit-scrollbar-thumb:hover {{ background: var(--text-faint); }}
* {{ scrollbar-width: thin; scrollbar-color: var(--border) transparent; }}

pre {{
  white-space: pre-wrap;
  word-break: break-word;
  font-family: var(--mono);
  font-size: 12px;
  line-height: 1.6;
}}

code {{
  font-family: var(--mono);
  font-size: 11px;
  background: var(--bg-3);
  padding: 1px 4px;
  border-radius: 2px;
}}

details summary {{ cursor: pointer; }}
details summary::-webkit-details-marker {{ display: none; }}
details > summary {{ list-style: none; }}
details > summary::before {{ content: '\u25b8 '; color: var(--text-faint); }}
details[open] > summary::before {{ content: '\u25be '; }}

/* ─── HEADER BAR ─── */
.hdr {{
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 8px 16px;
  background: var(--bg-1);
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
  min-height: 40px;
}}
.hdr-title {{
  font-family: var(--mono);
  font-size: 13px;
  font-weight: 600;
  color: var(--text-bright);
  white-space: nowrap;
}}
.hdr-toggles {{
  display: flex;
  gap: 10px;
  margin-left: auto;
  flex-shrink: 0;
}}
.toggle {{
  font-family: var(--mono);
  font-size: 11px;
  color: var(--text-dim);
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 4px;
  white-space: nowrap;
  user-select: none;
}}
.toggle input {{ cursor: pointer; accent-color: var(--text-dim); }}
.toggle:has(input:checked) {{ color: var(--text-bright); }}

/* ─── MAIN LAYOUT ─── */
.workspace {{ flex: 1; display: flex; overflow: hidden; }}

/* ─── LEFT SIDEBAR (metadata + coordination) ─── */
.left {{
  width: 340px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  border-right: 2px solid var(--border-strong);
  background: var(--bg);
  overflow: hidden;
}}
.left-meta {{
  flex-shrink: 0;
  border-bottom: 1px solid var(--border);
  overflow-y: auto;
  max-height: 45vh;
}}
.left-section {{
  padding: 10px 14px;
  border-bottom: 1px solid var(--border);
}}
.left-label {{
  font-family: var(--mono);
  font-size: 10px;
  font-weight: 500;
  color: var(--text-faint);
  text-transform: uppercase;
  letter-spacing: 1px;
  margin-bottom: 6px;
}}
.left-title {{
  font-family: var(--mono);
  font-size: 12px;
  font-weight: 600;
  color: var(--text-bright);
  word-break: break-all;
  margin-bottom: 6px;
}}
.meta-row {{
  display: flex;
  justify-content: space-between;
  font-size: 12px;
  padding: 2px 0;
  gap: 8px;
}}
.meta-key {{
  font-family: var(--mono);
  font-size: 11px;
  color: var(--text-dim);
  flex-shrink: 0;
}}
.meta-val {{
  font-family: var(--mono);
  font-size: 11px;
  color: var(--text-bright);
  text-align: right;
}}
.meta-detail {{
  font-size: 11px;
  color: var(--text-dim);
  margin-top: 4px;
  line-height: 1.5;
}}
.verify-pass {{ background: var(--green); }}
.verify-pass .left-label {{ color: var(--green-text); }}
.verify-pass .meta-val {{ color: var(--green-text); }}
.verify-fail {{ background: var(--red); }}
.verify-fail .left-label {{ color: var(--red-text); }}
.verify-fail .meta-val {{ color: var(--red-text); }}

/* Coordination log (below metadata) */
.coord {{
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  min-height: 0;
}}
.coord-head {{
  padding: 10px 14px;
  font-family: var(--mono);
  font-size: 10px;
  font-weight: 500;
  color: var(--text-faint);
  text-transform: uppercase;
  letter-spacing: 1px;
  border-bottom: 1px solid var(--border);
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-shrink: 0;
}}
.coord-count {{
  background: var(--bg-3);
  padding: 1px 7px;
  border-radius: 8px;
  font-size: 10px;
  color: var(--text-dim);
}}
.coord-scroll {{
  flex: 1;
  overflow-y: auto;
  padding: 4px 0;
}}
.coord-empty {{
  padding: 20px;
  text-align: center;
  color: var(--text-faint);
  font-size: 12px;
}}

/* Log entries */
.log-entry {{
  padding: 8px 14px;
  border-bottom: 1px solid var(--border);
  font-size: 12px;
  line-height: 1.5;
}}
.log-entry:hover {{ background: var(--bg-1); }}
.log-entry time {{
  font-family: var(--mono);
  font-size: 10px;
  color: var(--text-faint);
}}
.log-ind {{ color: var(--text-faint); margin: 0 4px; font-size: 11px; }}
.log-route {{
  font-family: var(--mono);
  font-size: 10px;
  color: var(--text-dim);
}}
.log-type {{
  font-family: var(--mono);
  font-size: 9px;
  color: var(--text-faint);
  margin-left: 6px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}}
.log-body {{ margin-top: 4px; }}
.log-rendered {{
  font-size: 12px;
  line-height: 1.6;
  color: var(--text);
}}
.log-rendered.log-short {{ font-size: 11px; }}
.log-rendered pre {{ background: var(--bg-3); padding: 6px 8px; border-radius: var(--radius); margin: 4px 0; }}
.log-rendered .md-h {{ font-size: 13px; color: var(--text-bright); margin: 8px 0 4px; }}
.log-rendered ul {{ padding-left: 16px; }}
.log-rendered li {{ margin: 2px 0; }}
.log-clipped .log-rendered {{
  max-height: 60px;
  overflow: hidden;
  position: relative;
}}
.log-clipped .log-rendered::after {{
  content: '';
  position: absolute;
  bottom: 0; left: 0; right: 0;
  height: 30px;
  background: linear-gradient(transparent, var(--bg));
  pointer-events: none;
}}
.log-expanded .log-rendered {{
  max-height: none;
  overflow: visible;
}}
.log-expanded .log-rendered::after {{ display: none; }}
.log-clipped {{ cursor: pointer; }}
.log-msg {{ border-left: 2px solid var(--text-faint); }}
.log-done {{ border-left: 2px solid var(--green-text); }}
.log-done .log-ind {{ color: var(--green-text); }}

/* ─── AGENT GRID ─── */
.grid {{
  flex: 1;
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(380px, 1fr));
  grid-auto-rows: minmax(0, 1fr);
  overflow: hidden;
  min-width: 0;
}}

/* ─── AGENT PANEL ─── */
.panel {{
  display: none;
  flex-direction: column;
  border-right: 2px solid var(--border-strong);
  border-bottom: 2px solid var(--border-strong);
  min-width: 0;
  min-height: 0;
  overflow: hidden;
}}
.panel.active {{ display: flex; }}
.panel-head {{
  padding: 10px 14px;
  background: var(--bg-1);
  border-bottom: 1px solid var(--border);
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-shrink: 0;
}}
.panel-label {{
  font-family: var(--mono);
  font-size: 13px;
  font-weight: 600;
  color: var(--text-bright);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}}
.panel-role {{
  font-weight: 400;
  color: var(--text-dim);
  text-transform: none;
  letter-spacing: 0;
  margin-left: 6px;
  font-size: 11px;
}}
.panel-count {{
  font-family: var(--mono);
  font-size: 10px;
  color: var(--text-dim);
  background: var(--bg-3);
  padding: 1px 7px;
  border-radius: 8px;
}}
.panel-scroll {{
  flex: 1;
  overflow-y: auto;
  padding: 4px 0;
}}

/* ─── EVENTS ─── */
.ev {{
  padding: 8px 14px;
  border-bottom: 1px solid var(--border);
}}
.ev:hover {{ background: var(--bg-1); }}
.ev time {{
  font-family: var(--mono);
  font-size: 10px;
  color: var(--text-faint);
  display: block;
  margin-bottom: 3px;
}}
.ev-body {{ }}
.ev-meta {{
  padding: 4px 14px;
  color: var(--text-dim);
  font-family: var(--mono);
  font-size: 11px;
  border-bottom: 1px solid var(--border);
}}
.ev-meta time {{ display: inline; margin-bottom: 0; margin-right: 8px; }}
.ev-result {{
  padding: 4px 14px;
  border-bottom: 1px solid var(--border);
}}
.ev-result time {{ display: inline; margin-right: 8px; }}

/* ─── PROSE (agent reasoning) ─── */
.prose {{
  font-size: 13px;
  line-height: 1.65;
  color: var(--text);
  padding: 2px 0;
}}
.prose-clipped .prose-content {{
  max-height: 160px;
  overflow: hidden;
  position: relative;
}}
.prose-clipped .prose-content::after {{
  content: '';
  position: absolute;
  bottom: 0;
  left: 0;
  right: 0;
  height: 50px;
  background: linear-gradient(transparent, var(--bg));
  pointer-events: none;
}}
.prose-expanded .prose-content {{
  max-height: none;
  overflow: visible;
}}
.prose-expanded .prose-content::after {{ display: none; }}
.prose-clipped {{ cursor: pointer; }}

.prose pre {{
  background: var(--bg-3);
  padding: 8px 10px;
  border-radius: var(--radius);
  margin: 6px 0;
  border-left: 2px solid var(--border-strong);
}}
.prose .md-h {{
  color: var(--text-bright);
  margin: 10px 0 4px;
  font-family: var(--sans);
}}
.prose h1.md-h {{ font-size: 15px; }}
.prose h2.md-h {{ font-size: 14px; }}
.prose h3.md-h {{ font-size: 13px; }}
.prose ul {{ padding-left: 18px; margin: 4px 0; }}
.prose li {{ margin: 2px 0; }}
.prose strong {{ color: var(--text-bright); }}

/* ─── TOOL USE ─── */
.tool-use {{
  margin: 8px 0;
  padding: 8px 10px;
  background: var(--bg-2);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  border-left: 2px solid var(--text-faint);
}}
.tool-name {{
  font-family: var(--mono);
  font-size: 11px;
  font-weight: 600;
  color: var(--text);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}}
.tool-params {{ margin-top: 6px; }}
.tool-param {{
  display: flex;
  gap: 8px;
  font-size: 11px;
  line-height: 1.5;
  padding: 2px 0;
}}
.tool-key {{
  font-family: var(--mono);
  color: var(--text-dim);
  flex-shrink: 0;
}}
.tool-val {{
  min-width: 0;
  overflow-wrap: break-word;
  word-break: break-all;
}}
.tool-val code {{ word-break: break-all; white-space: pre-wrap; }}
.trunc {{ font-size: 11px; color: var(--text-dim); }}
.expanded {{ margin-top: 4px; background: var(--bg-3); padding: 6px 8px; border-radius: var(--radius); }}

/* ─── TOOL OUTPUT ─── */
.tool-out, .tool-err {{ margin: 6px 0; font-size: 11px; }}
.tool-out pre, .tool-err pre {{
  background: var(--bg-3);
  padding: 8px;
  border-radius: var(--radius);
  max-height: 300px;
  overflow-y: auto;
}}
.tool-err pre {{ border-left: 2px solid var(--red-text); }}
.tool-out summary, .tool-err summary {{
  font-family: var(--mono);
  font-size: 10px;
  color: var(--text-dim);
  padding: 2px 0;
}}
.tool-err summary {{ color: var(--red-text); }}
.rl {{ color: var(--text-dim); font-size: 11px; }}
</style>
</head>
<body>
<header class="hdr">
{header}
</header>
<div class="workspace">
<div class="left">
<div class="left-meta">
{left_sidebar}
</div>
{coordination}
</div>
<div class="grid" id="grid">
{panels}
</div>
</div>
<script>
const agentIds = {agent_ids_json};
const panels = document.querySelectorAll('.panel');
const checkboxes = document.querySelectorAll('.toggle input[data-agent]');

function update() {{
  panels.forEach(p => {{
    const aid = p.dataset.agent;
    const cb = document.querySelector(`input[data-agent="${{aid}}"]`);
    p.classList.toggle('active', cb && cb.checked);
  }});
  const visible = document.querySelectorAll('.panel.active').length;
  const grid = document.getElementById('grid');
  if (visible <= 1) {{
    grid.style.gridTemplateColumns = '1fr';
  }} else if (visible <= 2) {{
    grid.style.gridTemplateColumns = 'repeat(2, 1fr)';
  }} else {{
    grid.style.gridTemplateColumns = 'repeat(auto-fit, minmax(380px, 1fr))';
  }}
}}

checkboxes.forEach(cb => cb.addEventListener('change', update));

// Click-to-expand on clipped prose and log entries
document.querySelectorAll('.prose-clipped, .log-clipped').forEach(el => {{
  el.addEventListener('click', () => {{
    el.classList.toggle('prose-expanded');
    el.classList.toggle('log-expanded');
  }});
}});

update();
</script>
</body>
</html>
"""
