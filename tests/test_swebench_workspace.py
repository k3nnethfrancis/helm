from __future__ import annotations

import os
import subprocess
from pathlib import Path

from helm.benchmarks.swebench_workspace import ensure_repo, workspace_dirty_patch


def test_workspace_dirty_patch_tolerates_non_utf8_diff_content(tmp_path: Path) -> None:
    experiment_dir = tmp_path / "experiment"
    repo = experiment_dir / "workspace" / "repo"
    repo.mkdir(parents=True)

    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Helm Test"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "helm@example.com"], cwd=repo, check=True, capture_output=True)

    binary_file = repo / "data.bin"
    binary_file.write_bytes(b"\xff\xd5\x00\x01")
    subprocess.run(["git", "add", "data.bin"], cwd=repo, check=True, capture_output=True)
    env = dict(
        os.environ,
        GIT_AUTHOR_DATE="2026-03-08T00:00:00+0000",
        GIT_COMMITTER_DATE="2026-03-08T00:00:00+0000",
    )
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True, env=env)

    binary_file.write_bytes(b"\xff\xd5\x02\x03")

    patch = workspace_dirty_patch(experiment_dir)

    assert patch is not None
    assert "data.bin" in patch


def test_ensure_repo_uses_cached_commit_when_fetch_times_out(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    repo_path = cache_dir / "django__django"
    repo_path.mkdir(parents=True)
    (repo_path / ".git").mkdir()

    real_run = subprocess.run

    def fake_run(args, **kwargs):
        cmd = list(args)
        if cmd[:3] == ["git", "fetch", "--all"]:
            return subprocess.CompletedProcess(cmd, 128, "", "fatal: timed out")
        if cmd[:3] == ["git", "rev-parse", "--verify"]:
            return subprocess.CompletedProcess(cmd, 0, "abc123\n", "")
        return real_run(args, **kwargs)

    from helm.benchmarks import swebench_workspace

    original_run = swebench_workspace.subprocess.run
    swebench_workspace.subprocess.run = fake_run
    try:
        resolved = ensure_repo("django/django", cache_dir, required_commit="abc123")
    finally:
        swebench_workspace.subprocess.run = original_run

    assert resolved == repo_path
