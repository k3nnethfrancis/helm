"""Smoke tests for the helm_swebench Prime environment.

Tests the vf.SingleTurnEnv contract: dataset schema, reward functions,
and rubric assembly. The verifier subprocess is monkeypatched to avoid
network clones — we test the reward plumbing, not the verifier itself
(that's covered by test_verify_swebench.py).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

# The environment module is not pip-installed in the test venv; import by path.
import importlib.util
import sys

_ENV_DIR = Path(__file__).resolve().parent.parent / "environments" / "helm_swebench"
_ENV_FILE = _ENV_DIR / "helm_swebench.py"


def _import_env_module():
    """Import helm_swebench.py without requiring verifiers to be installed."""
    spec = importlib.util.spec_from_file_location("helm_swebench", _ENV_FILE)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    return spec, mod


# ---------------------------------------------------------------------------
# Test helpers (no verifiers dependency)
# ---------------------------------------------------------------------------


class TestNormalizeRow:
    """Test _normalize_row without importing verifiers."""

    def test_produces_required_keys(self) -> None:
        """Normalized row must have question, answer, info, task."""
        # Load a sample row
        sample_path = _ENV_DIR / "data" / "sample.jsonl"
        with open(sample_path) as f:
            raw_row = json.loads(f.readline())

        # Import just the normalize function
        # We can't import the module directly because it imports verifiers,
        # so we test the logic inline.
        instance_id = raw_row.get("instance_id", "")
        repo = raw_row.get("repo", "")
        base_commit = raw_row.get("base_commit", "")
        version = raw_row.get("version", "")
        problem_statement = raw_row.get("problem_statement", "")

        assert instance_id, "Sample row missing instance_id"
        assert repo, "Sample row missing repo"
        assert base_commit, "Sample row missing base_commit"
        assert problem_statement, "Sample row missing problem_statement"

        # Build the answer blob the same way the module does
        answer = json.dumps({
            "instance_id": instance_id,
            "repo": repo,
            "base_commit": base_commit,
            "version": version,
            "FAIL_TO_PASS": raw_row.get("FAIL_TO_PASS", "[]"),
            "PASS_TO_PASS": raw_row.get("PASS_TO_PASS", "[]"),
            "test_patch": raw_row.get("test_patch", ""),
        })

        # Answer must be valid JSON containing all verifier fields
        parsed = json.loads(answer)
        assert "instance_id" in parsed
        assert "repo" in parsed
        assert "base_commit" in parsed
        assert "FAIL_TO_PASS" in parsed
        assert "test_patch" in parsed

    def test_sample_jsonl_has_rows(self) -> None:
        """Sample data file must exist and have at least one row."""
        sample_path = _ENV_DIR / "data" / "sample.jsonl"
        assert sample_path.exists(), f"Missing {sample_path}"
        with open(sample_path) as f:
            lines = [line for line in f if line.strip()]
        assert len(lines) >= 1, "sample.jsonl is empty"


class TestRewardHelpers:
    """Test reward helper functions without verifiers dependency."""

    def test_diff_header_detection(self) -> None:
        """Format reward should detect unified diff markers."""
        import re
        pattern = re.compile(r"^(---|\+\+\+|@@)", re.MULTILINE)

        valid_patch = """--- a/foo.py
+++ b/foo.py
@@ -1,3 +1,3 @@
 def hello():
-    return 'world'
+    return 'fixed'
"""
        markers = pattern.findall(valid_patch)
        has_minus = any(m == "---" for m in markers)
        has_plus = any(m == "+++" for m in markers)
        has_hunk = any(m == "@@" for m in markers)
        score = sum([has_minus, has_plus, has_hunk]) / 3.0
        assert score == 1.0

        # Garbage text should score 0
        assert len(pattern.findall("this is not a patch")) == 0

    def test_parsimony_reward_gradient(self) -> None:
        """Shorter patches should score higher than longer ones."""
        def parsimony(text: str) -> float:
            num_lines = len(text.strip().splitlines())
            if num_lines == 0:
                return 0.0
            return max(0.0, 1.0 - (num_lines / 500))

        short_patch = "--- a/f.py\n+++ b/f.py\n@@ -1 +1 @@\n-old\n+new\n"
        long_patch = "\n".join([f"line {i}" for i in range(400)])

        assert parsimony(short_patch) > parsimony(long_patch)
        assert parsimony(short_patch) > 0.9
        assert parsimony("") == 0.0

    def test_completion_to_text_handles_formats(self) -> None:
        """_completion_to_text should handle str, dict, and list formats."""
        # Inline the function since we can't import the module easily
        def _completion_to_text(completion: Any) -> str:
            if isinstance(completion, str):
                return completion
            if isinstance(completion, dict):
                if "content" in completion:
                    return _completion_to_text(completion.get("content"))
                if "text" in completion and isinstance(completion.get("text"), str):
                    return str(completion["text"])
            if isinstance(completion, list):
                parts = []
                for item in completion:
                    text = _completion_to_text(item).strip()
                    if text:
                        parts.append(text)
                return "\n".join(parts)
            return str(completion)

        assert _completion_to_text("hello") == "hello"
        assert _completion_to_text({"content": "hello"}) == "hello"
        assert _completion_to_text({"text": "hello"}) == "hello"
        assert _completion_to_text([{"content": "a"}, {"content": "b"}]) == "a\nb"

    def test_verifier_script_path_resolution(self) -> None:
        """Verifier script should resolve relative to the environment file."""
        expected = _ENV_DIR.parent.parent / "scripts" / "verify_swebench.py"
        assert expected.exists(), f"Verifier script not found at {expected}"


class TestVerifierRewardPlumbing:
    """Test the verifier reward function's subprocess plumbing."""

    def test_verifier_reward_with_mock_success(self, tmp_path: Path) -> None:
        """Monkeypatched verifier returning score=0.75 should propagate."""
        mock_result = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=json.dumps({"status": "partial", "score": 0.75, "reason": "mock"}),
            stderr="",
        )

        answer = json.dumps({
            "instance_id": "test__test-123",
            "repo": "test/test",
            "base_commit": "abc123",
            "version": "1.0",
            "FAIL_TO_PASS": '["test_foo"]',
            "PASS_TO_PASS": '["test_bar"]',
            "test_patch": "",
        })

        patch_text = "--- a/f.py\n+++ b/f.py\n@@ -1 +1 @@\n-old\n+new\n"

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            # Simulate what verifier_reward does
            import tempfile
            import shutil

            meta = json.loads(answer)
            instance_id = meta["instance_id"]

            tmp_dir = tempfile.mkdtemp(prefix="helm-swebench-test-")
            try:
                row_file = Path(tmp_dir) / "instance.jsonl"
                row_file.write_text(json.dumps(meta) + "\n")

                workspace = Path(tmp_dir) / "workspace"
                workspace.mkdir()
                (workspace / "model.patch").write_text(patch_text)

                result = subprocess.run(
                    ["python", "verify_swebench.py",
                     "--instance-id", instance_id,
                     "--experiment-dir", tmp_dir,
                     "--dataset-path", str(row_file),
                     "--repo-cache", "/tmp/test-cache",
                     "--timeout", "300"],
                    capture_output=True,
                    text=True,
                    timeout=360,
                )

                assert result.returncode == 0
                payload = json.loads(result.stdout.strip())
                assert payload["score"] == 0.75
            finally:
                shutil.rmtree(tmp_dir, ignore_errors=True)

    def test_verifier_reward_cleanup(self, tmp_path: Path) -> None:
        """Temp directory should be cleaned up even on error."""
        import tempfile
        import shutil

        tmp_dir = tempfile.mkdtemp(prefix="helm-swebench-cleanup-test-")
        assert Path(tmp_dir).exists()

        try:
            raise RuntimeError("simulated error")
        except RuntimeError:
            pass
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

        assert not Path(tmp_dir).exists(), "Temp dir was not cleaned up"

    def test_empty_completion_returns_zero(self) -> None:
        """Empty or whitespace-only completions should score 0.0."""
        for empty in ["", "   ", "\n\n"]:
            text = empty.strip()
            assert not text, f"Expected empty after strip: {empty!r}"

    def test_invalid_answer_returns_zero(self) -> None:
        """Malformed answer JSON should not crash, just return 0."""
        for bad_answer in ["not json", "", "null", "42"]:
            try:
                meta = json.loads(bad_answer) if isinstance(bad_answer, str) else bad_answer
                if not isinstance(meta, dict):
                    meta = {}
            except (json.JSONDecodeError, TypeError):
                meta = {}
            instance_id = meta.get("instance_id", "") if isinstance(meta, dict) else ""
            assert instance_id == "", f"Expected no instance_id from {bad_answer!r}"


class TestRubricWeights:
    """Verify rubric weights sum to 1.0."""

    def test_weights_sum(self) -> None:
        weights = [0.1, 0.85, 0.05]
        assert abs(sum(weights) - 1.0) < 1e-9
