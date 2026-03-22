"""Helm agent coordination CLI.

Provides topology-controlled coordination tools for agents running in
Helm experiments. Agents call this via Bash instead of using native
coordination tools (Agent, TeamCreate, SendMessage) which are blocked
by --disallowedTools.

Usage (from within an agent's Bash tool):
    python -m helm.agent_cli send --from researcher_a --to coordinator --msg "Found the bug"
    python -m helm.agent_cli inbox --agent researcher_a
    python -m helm.agent_cli status --agent implementer
    python -m helm.agent_cli spawn --parent coordinator --task "Investigate test failures" --role worker
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path


def _find_config() -> dict:
    """Find and load the .helm-config.json from the coordination directory."""
    # Walk up from cwd looking for coordination/.helm-config.json
    cwd = Path.cwd()
    for parent in [cwd, *cwd.parents]:
        config_path = parent / "coordination" / ".helm-config.json"
        if config_path.exists():
            with open(config_path) as f:
                return json.load(f)
    # Also check HELM_COORDINATION_DIR env var
    coord_dir = os.environ.get("HELM_COORDINATION_DIR")
    if coord_dir:
        config_path = Path(coord_dir) / ".helm-config.json"
        if config_path.exists():
            with open(config_path) as f:
                return json.load(f)
    print("Error: Could not find coordination/.helm-config.json", file=sys.stderr)
    sys.exit(1)


def _coordination_dir(config: dict) -> Path:
    """Get the coordination directory path."""
    coord_dir = os.environ.get("HELM_COORDINATION_DIR")
    if coord_dir:
        return Path(coord_dir)
    cwd = Path.cwd()
    for parent in [cwd, *cwd.parents]:
        if (parent / "coordination" / ".helm-config.json").exists():
            return parent / "coordination"
    raise RuntimeError("Cannot find coordination directory")


def cmd_send(args: argparse.Namespace) -> None:
    """Send a message to another agent, subject to topology rules."""
    config = _find_config()
    agents = config.get("agents", {})
    sender = args.sender
    recipient = args.to

    # Validate sender exists
    if sender not in agents:
        print(f"Error: Unknown sender '{sender}'. Known agents: {list(agents.keys())}", file=sys.stderr)
        sys.exit(1)

    # Validate recipient exists
    if recipient not in agents:
        print(f"Error: Unknown recipient '{recipient}'. Known agents: {list(agents.keys())}", file=sys.stderr)
        sys.exit(1)

    # Check messaging rules
    sender_config = agents[sender]
    allowed_recipients = sender_config.get("can_message", [])
    if allowed_recipients and recipient not in allowed_recipients:
        print(
            f"Error: Topology violation. Agent '{sender}' (role={sender_config.get('role')}) "
            f"cannot message '{recipient}' in {config.get('family')} topology. "
            f"Allowed recipients: {allowed_recipients}",
            file=sys.stderr,
        )
        sys.exit(1)

    # Write message to coordination/messages/
    coord_dir = _coordination_dir(config)
    messages_dir = coord_dir / "messages"
    messages_dir.mkdir(parents=True, exist_ok=True)

    timestamp = time.strftime("%Y%m%d-%H%M%S")
    msg_file = messages_dir / f"{timestamp}-{sender}-to-{recipient}.md"
    msg_file.write_text(f"From: {sender}\nTo: {recipient}\nTime: {timestamp}\n\n{args.msg}\n")

    print(f"Message sent from {sender} to {recipient}: {msg_file.name}")


def cmd_inbox(args: argparse.Namespace) -> None:
    """Read messages directed to an agent."""
    config = _find_config()
    coord_dir = _coordination_dir(config)
    messages_dir = coord_dir / "messages"

    if not messages_dir.exists():
        print("No messages.")
        return

    agent = args.agent
    messages = sorted(messages_dir.glob(f"*-to-{agent}.md"))
    if not messages:
        print(f"No messages for {agent}.")
        return

    for msg_path in messages:
        print(f"--- {msg_path.name} ---")
        print(msg_path.read_text())


def cmd_status(args: argparse.Namespace) -> None:
    """Check status of an agent by reading their coordination artifacts."""
    config = _find_config()
    coord_dir = _coordination_dir(config)
    agent = args.agent

    if agent not in config.get("agents", {}):
        print(f"Error: Unknown agent '{agent}'.", file=sys.stderr)
        sys.exit(1)

    agent_info = config["agents"][agent]
    print(f"Agent: {agent}")
    print(f"Role: {agent_info.get('role', 'unknown')}")
    print(f"Can spawn: {agent_info.get('can_spawn', False)}")
    print(f"Can message: {agent_info.get('can_message', [])}")

    # Check for task assignments
    tasks_dir = coord_dir / "tasks"
    if tasks_dir.exists():
        task_files = list(tasks_dir.glob(f"*{agent}*"))
        if task_files:
            print(f"Task assignments: {len(task_files)}")
            for tf in task_files:
                print(f"  {tf.name}")

    # Check for signals
    signals_dir = coord_dir / "signals"
    if signals_dir.exists():
        signal_files = list(signals_dir.glob(f"*{agent}*"))
        if signal_files:
            print(f"Signals: {[sf.name for sf in signal_files]}")


def cmd_spawn(args: argparse.Namespace) -> None:
    """Spawn a subagent, subject to topology rules."""
    config = _find_config()
    agents = config.get("agents", {})
    parent = args.parent

    if parent not in agents:
        print(f"Error: Unknown parent '{parent}'.", file=sys.stderr)
        sys.exit(1)

    parent_config = agents[parent]
    if not parent_config.get("can_spawn", False):
        print(
            f"Error: Topology violation. Agent '{parent}' (role={parent_config.get('role')}) "
            f"cannot spawn subagents in {config.get('family')} topology.",
            file=sys.stderr,
        )
        sys.exit(1)

    # Check spawn depth
    max_depth = config.get("max_spawn_depth", 1)
    current_depth = int(os.environ.get("HELM_SPAWN_DEPTH", "0"))
    if current_depth >= max_depth:
        print(
            f"Error: Maximum spawn depth reached ({max_depth}). "
            f"Spawned agents cannot spawn further subagents.",
            file=sys.stderr,
        )
        sys.exit(1)

    # Build the subagent command
    import shutil

    harness = config.get("harness", "claude-code")
    task = args.task
    role = args.role or "worker"

    # Get disallowed tools for spawned role
    disallowed = config.get("disallowed_tools_base", ["Agent", "TeamCreate", "SendMessage"])
    # Spawned agents always have Agent blocked (no recursive spawning by default)
    if "Agent" not in disallowed:
        disallowed = ["Agent"] + disallowed

    coord_dir = _coordination_dir(config)
    workspace_dir = coord_dir.parent / "workspace"

    # Build spawn prompt
    spawn_prompt = (
        f"You are a spawned subagent (role: {role}) working on a subtask.\n\n"
        f"## Task\n{task}\n\n"
        f"## Workspace\nWork in: {workspace_dir}\n"
        f"Write your results to: {coord_dir}/results/{parent}-spawn-{role}-{int(time.time())}.md\n\n"
        f"Complete the task and write your findings to the results file."
    )

    if harness in ("claude-code", "claude"):
        claude_bin = shutil.which("claude")
        if not claude_bin:
            print("Error: claude CLI not found.", file=sys.stderr)
            sys.exit(1)

        cmd = [
            claude_bin, "-p", spawn_prompt,
            "--output-format", "text",
            "--dangerously-skip-permissions",
            "--no-session-persistence",
            "--add-dir", str(workspace_dir),
        ]
        if disallowed:
            cmd.extend(["--disallowedTools", ",".join(disallowed)])
    else:
        print(f"Error: Spawn not supported for harness '{harness}'.", file=sys.stderr)
        sys.exit(1)

    # Create results directory
    (coord_dir / "results").mkdir(parents=True, exist_ok=True)

    # Log the spawn
    spawn_log = coord_dir / "spawn_log.jsonl"
    with open(spawn_log, "a") as f:
        json.dump({
            "parent": parent,
            "role": role,
            "task": task[:200],
            "depth": current_depth + 1,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }, f)
        f.write("\n")

    print(f"Spawning subagent (role={role}, depth={current_depth + 1})...")

    # Run the subagent
    env = os.environ.copy()
    env["HELM_SPAWN_DEPTH"] = str(current_depth + 1)
    env["HELM_COORDINATION_DIR"] = str(coord_dir)
    # Strip nested session vars
    for var in ("CLAUDECODE", "_CLAUDE_SESSION_VARS", "CLAUDE_CODE_ENTRYPOINT"):
        env.pop(var, None)

    result = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=300)

    if result.returncode != 0:
        print(f"Subagent failed (exit {result.returncode}): {result.stderr[:200]}", file=sys.stderr)
        sys.exit(1)

    print(f"Subagent completed. Check coordination/results/ for output.")
    if result.stdout:
        # Print last 500 chars of output as summary
        print(f"\n--- Subagent output (tail) ---\n{result.stdout[-500:]}")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="helm-agent",
        description="Helm topology-controlled agent coordination",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # send
    send_parser = subparsers.add_parser("send", help="Send a message to another agent")
    send_parser.add_argument("--from", dest="sender", required=True, help="Sender agent ID")
    send_parser.add_argument("--to", required=True, help="Recipient agent ID")
    send_parser.add_argument("--msg", required=True, help="Message content")

    # inbox
    inbox_parser = subparsers.add_parser("inbox", help="Read messages for an agent")
    inbox_parser.add_argument("--agent", required=True, help="Agent ID to check inbox for")

    # status
    status_parser = subparsers.add_parser("status", help="Check agent status")
    status_parser.add_argument("--agent", required=True, help="Agent ID to check")

    # spawn
    spawn_parser = subparsers.add_parser("spawn", help="Spawn a subagent (if allowed by topology)")
    spawn_parser.add_argument("--parent", required=True, help="Parent agent ID requesting spawn")
    spawn_parser.add_argument("--task", required=True, help="Task description for subagent")
    spawn_parser.add_argument("--role", default="worker", help="Role for spawned agent")

    args = parser.parse_args()

    commands = {
        "send": cmd_send,
        "inbox": cmd_inbox,
        "status": cmd_status,
        "spawn": cmd_spawn,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()
