"""SWE-bench ground truth verification environment for Prime RL.

Wraps the standalone verifier (scripts/verify_swebench.py) as a
vf.SingleTurnEnv so Prime can sample patches and score them against
real test execution.

Each rollout:
  1. Model receives repo + issue description, outputs a unified diff patch.
  2. Reward functions score format compliance, verifier result, and parsimony.
  3. The verifier subprocess clones, patches, installs, and runs tests.

Latency: 30-300s per rollout (real test execution). Plan batch sizes accordingly.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import verifiers as vf
from datasets import Dataset, load_dataset

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are an expert software engineer. You will be given a description of a bug or feature request in an open-source Python repository, along with the repository name, base commit, and relevant context.

Your task: produce a unified diff patch that fixes the described issue.

Requirements:
- Output ONLY a valid unified diff (the kind produced by `git diff` or accepted by `git apply`).
- The patch must include proper `--- a/path` and `+++ b/path` headers.
- Include `@@ ... @@` hunk headers with correct line numbers.
- Do NOT include any prose, explanation, or markdown fencing — only the raw patch.
- Make minimal, targeted changes. Do not rewrite entire files.
- Ensure the patch applies cleanly to the base commit specified."""


# ---------------------------------------------------------------------------
# Dataset loading (reuses pattern from helm_orchestration_policy)
# ---------------------------------------------------------------------------


def _normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    """Convert a SWE-bench JSONL row into the vf.SingleTurnEnv schema."""
    instance_id = row.get("instance_id", "")
    repo = row.get("repo", "")
    base_commit = row.get("base_commit", "")
    version = row.get("version", "")
    problem_statement = row.get("problem_statement", "")
    hints_text = row.get("hints_text", "")

    # Build the question prompt
    parts = [
        f"Repository: {repo}",
        f"Base commit: {base_commit}",
        f"Version: {version}",
        "",
        "## Problem Statement",
        problem_statement,
    ]
    if hints_text and hints_text.strip():
        parts.extend(["", "## Hints", hints_text])

    parts.extend([
        "",
        "## Instructions",
        "Produce a unified diff patch that resolves the issue above.",
        "Output ONLY the raw patch — no explanation, no markdown fencing.",
    ])

    question = "\n".join(parts)

    # The answer carries everything the verifier needs
    answer = json.dumps({
        "instance_id": instance_id,
        "repo": repo,
        "base_commit": base_commit,
        "version": version,
        "FAIL_TO_PASS": row.get("FAIL_TO_PASS", "[]"),
        "PASS_TO_PASS": row.get("PASS_TO_PASS", "[]"),
        "test_patch": row.get("test_patch", ""),
    })

    return {
        "question": question,
        "answer": answer,
        "info": {
            "instance_id": instance_id,
            "repo": repo,
            "created_at": row.get("created_at", ""),
        },
        "task": "helm-swebench",
    }


def _resolve_dataset_path(dataset_path: str) -> Path | None:
    """Resolve a dataset path, checking relative to this file too."""
    candidate = Path(dataset_path)
    if candidate.exists():
        return candidate
    local_candidate = (Path(__file__).resolve().parent / dataset_path).resolve()
    if local_candidate.exists():
        return local_candidate
    return None


def _load_dataset_rows(
    dataset_path: str,
    dataset_split: str,
    max_examples: int,
) -> Dataset:
    """Load and normalize SWE-bench rows into a Dataset."""
    resolved = _resolve_dataset_path(dataset_path)
    if resolved is not None:
        if resolved.is_dir():
            split_file = resolved / f"{dataset_split}.jsonl"
            if split_file.exists():
                raw = load_dataset(
                    "json",
                    data_files={dataset_split: str(split_file)},
                    split=dataset_split,
                )
            else:
                candidates = sorted(resolved.glob("*.jsonl"))
                if not candidates:
                    raise ValueError(f"No JSONL files found under {resolved}")
                raw = load_dataset("json", data_files=str(candidates[0]), split="train")
        else:
            raw = load_dataset("json", data_files=str(resolved), split="train")
    else:
        raw = load_dataset(dataset_path, split=dataset_split)

    if max_examples > 0:
        raw = raw.select(range(min(max_examples, len(raw))))

    rows: list[dict[str, Any]] = []
    for row in raw:
        if isinstance(row, dict):
            rows.append(_normalize_row(row))
    if not rows:
        raise ValueError("No valid rows found for helm-swebench dataset.")
    return Dataset.from_list(rows)


# ---------------------------------------------------------------------------
# Reward helpers
# ---------------------------------------------------------------------------

_DIFF_HEADER_RE = re.compile(r"^(---|\+\+\+|@@)", re.MULTILINE)


def _completion_to_text(completion: Any) -> str:
    """Extract plain text from various completion formats."""
    if isinstance(completion, str):
        return completion
    if isinstance(completion, dict):
        if "content" in completion:
            return _completion_to_text(completion.get("content"))
        if "text" in completion and isinstance(completion.get("text"), str):
            return str(completion["text"])
    if isinstance(completion, list):
        parts: list[str] = []
        for item in completion:
            text = _completion_to_text(item).strip()
            if text:
                parts.append(text)
        return "\n".join(parts)
    return str(completion)


def _resolve_verifier_script() -> Path:
    """Find verify_swebench.py, with env var override for Hub deployment."""
    override = os.environ.get("HELM_VERIFY_SWEBENCH")
    if override:
        return Path(override)
    return Path(__file__).resolve().parent.parent.parent / "scripts" / "verify_swebench.py"


# ---------------------------------------------------------------------------
# load_environment
# ---------------------------------------------------------------------------


def load_environment(
    dataset_path: str = "data/sample.jsonl",
    dataset_split: str = "train",
    max_examples: int = -1,
    system_prompt: str = SYSTEM_PROMPT,
    timeout: int = 300,
    repo_cache: str = "~/.cache/helm/swebench-repos",
    **kwargs: Any,
) -> vf.Environment:
    """Create a SWE-bench verification environment for Prime RL.

    Args:
        dataset_path: Path to JSONL file, directory, or HuggingFace dataset id.
        dataset_split: Split name for HF datasets or split-file directories.
        max_examples: Cap loaded examples (-1 means all).
        system_prompt: System prompt for the model.
        timeout: Seconds per verifier subprocess invocation.
        repo_cache: Directory for caching cloned repos.
    """
    dataset = _load_dataset_rows(
        dataset_path=dataset_path,
        dataset_split=dataset_split,
        max_examples=max_examples,
    )
    parser = vf.Parser()
    verifier_script = _resolve_verifier_script()
    expanded_repo_cache = Path(repo_cache).expanduser()

    # --- Reward function 1: patch format compliance ---

    def patch_format_reward(completion: Any, **_kwargs: Any) -> float:
        """Does the completion look like a valid unified diff?"""
        text = _completion_to_text(completion)
        markers = _DIFF_HEADER_RE.findall(text)
        if not markers:
            return 0.0
        has_minus = any(m == "---" for m in markers)
        has_plus = any(m == "+++" for m in markers)
        has_hunk = any(m == "@@" for m in markers)
        score = sum([has_minus, has_plus, has_hunk]) / 3.0
        return score

    # --- Reward function 2: verifier subprocess ---
    # Closure captures expanded_repo_cache, timeout, verifier_script.
    # The answer blob carries all metadata the verifier needs, so we write
    # a single-row JSONL to the temp dir — no dependency on the original
    # dataset path at reward time (fixes HuggingFace / remote dataset case).

    def verifier_reward(completion: Any, answer: Any, **_kwargs: Any) -> float:
        """Run the SWE-bench verifier and return the score."""
        text = _completion_to_text(completion)
        if not text.strip():
            return 0.0

        # Parse answer to get instance metadata
        try:
            meta = json.loads(answer) if isinstance(answer, str) else answer
        except (json.JSONDecodeError, TypeError):
            return 0.0

        instance_id = meta.get("instance_id", "")
        if not instance_id:
            return 0.0

        tmp_dir = tempfile.mkdtemp(prefix="helm-swebench-reward-")
        try:
            # Write a single-row JSONL so the verifier can load it
            row_file = Path(tmp_dir) / "instance.jsonl"
            row_file.write_text(json.dumps(meta) + "\n")

            # Write the model's patch where the verifier expects it
            workspace = Path(tmp_dir) / "workspace"
            workspace.mkdir()
            (workspace / "model.patch").write_text(text)

            result = subprocess.run(
                [
                    sys.executable,
                    str(verifier_script),
                    "--instance-id", instance_id,
                    "--experiment-dir", tmp_dir,
                    "--dataset-path", str(row_file),
                    "--repo-cache", str(expanded_repo_cache),
                    "--timeout", str(timeout),
                ],
                capture_output=True,
                text=True,
                timeout=timeout + 60,  # extra buffer for subprocess overhead
            )

            if result.returncode not in (0, 2):
                # Exit code 3 = verifier error, others unexpected
                return 0.0

            payload = json.loads(result.stdout.strip())
            return float(payload.get("score", 0.0))

        except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError):
            return 0.0
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    # --- Reward function 3: patch parsimony ---

    def patch_size_reward(completion: Any, **_kwargs: Any) -> float:
        """Mild reward for shorter patches. Discourages dumping entire files."""
        text = _completion_to_text(completion)
        num_lines = len(text.strip().splitlines())
        if num_lines == 0:
            return 0.0
        return max(0.0, 1.0 - (num_lines / 500))

    # --- Assemble rubric ---

    rubric = vf.Rubric(
        funcs=[
            patch_format_reward,
            verifier_reward,
            patch_size_reward,
        ],
        weights=[0.1, 0.85, 0.05],
    )

    return vf.SingleTurnEnv(
        dataset=dataset,
        system_prompt=system_prompt,
        parser=parser,
        rubric=rubric,
    )
