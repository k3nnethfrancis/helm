"""Workspace helpers for SWE-bench-backed Helm runs."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

DEFAULT_REPO_CACHE = Path(
    os.environ.get("HELM_SWEBENCH_REPO_CACHE", "~/.cache/helm/swebench-repos")
).expanduser()


def canonical_workspace_repo(experiment_dir: Path) -> Path:
    """Return the canonical staged repo path inside an experiment workspace."""
    return experiment_dir / "workspace" / "repo"


def _has_commit(repo_path: Path, commit: str) -> bool:
    result = subprocess.run(
        ["git", "rev-parse", "--verify", f"{commit}^{{commit}}"],
        cwd=repo_path,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def ensure_repo(repo: str, cache_dir: Path, *, required_commit: str | None = None) -> Path:
    """Clone repo to cache or return existing path."""
    safe_name = repo.replace("/", "__")
    repo_path = cache_dir / safe_name

    if repo_path.exists() and (repo_path / ".git").exists():
        result = subprocess.run(
            ["git", "fetch", "--all", "--quiet"],
            cwd=repo_path,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            if required_commit and _has_commit(repo_path, required_commit):
                return repo_path
            raise RuntimeError(
                f"git fetch failed for cached repo {repo_path}. "
                f"Try deleting the cache entry and re-running: rm -rf {repo_path}\n"
                f"stderr: {result.stderr}"
            )
        return repo_path

    repo_path.mkdir(parents=True, exist_ok=True)
    url = f"https://github.com/{repo}.git"
    result = subprocess.run(
        ["git", "clone", "--quiet", url, str(repo_path)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git clone failed for {url}: {result.stderr}")
    return repo_path


def checkout_base(repo_path: Path, base_commit: str) -> None:
    """Hard checkout to base_commit and clean."""
    result = subprocess.run(
        ["git", "checkout", base_commit, "--force"],
        cwd=repo_path,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git checkout failed: {result.stderr}")
    subprocess.run(
        ["git", "clean", "-fdx"],
        cwd=repo_path,
        capture_output=True,
    )


def stage_repo_in_workspace(
    repo: str,
    base_commit: str,
    experiment_dir: Path,
    *,
    cache_dir: Path | None = None,
) -> Path:
    """Populate the canonical workspace repo with the requested base commit."""
    resolved_cache = (cache_dir or DEFAULT_REPO_CACHE).expanduser()
    resolved_cache.mkdir(parents=True, exist_ok=True)

    cached_repo = ensure_repo(repo, resolved_cache, required_commit=base_commit)
    destination = canonical_workspace_repo(experiment_dir)
    if destination.exists():
        shutil.rmtree(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(cached_repo, destination, symlinks=True)
    checkout_base(destination, base_commit)
    return destination


def _is_git_repo(path: Path) -> bool:
    return path.exists() and (path / ".git").exists()


def workspace_repo_candidates(experiment_dir: Path) -> list[Path]:
    """Return candidate git repos inside the experiment workspace."""
    workspace = experiment_dir / "workspace"
    if not workspace.exists():
        return []

    candidates: list[Path] = []
    seen: set[Path] = set()

    def add(path: Path) -> None:
        if path in seen or not _is_git_repo(path):
            return
        seen.add(path)
        candidates.append(path)

    add(canonical_workspace_repo(experiment_dir))
    add(workspace)
    for git_dir in workspace.rglob(".git"):
        add(git_dir.parent)
    return candidates


def _tracked_diff(repo_path: Path) -> str:
    result = subprocess.run(
        ["git", "diff", "--binary", "--no-ext-diff", "HEAD"],
        cwd=repo_path,
        capture_output=True,
    )
    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", errors="replace")
        raise RuntimeError(f"git diff failed for {repo_path}: {stderr}")
    return result.stdout.decode("utf-8", errors="replace")


def _untracked_diff(repo_path: Path) -> str:
    result = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard", "-z"],
        cwd=repo_path,
        capture_output=True,
        text=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git ls-files failed for {repo_path}: {result.stderr.decode()}")

    patches: list[str] = []
    for raw_path in result.stdout.split(b"\x00"):
        if not raw_path:
            continue
        rel_path = raw_path.decode()
        diff = subprocess.run(
            ["git", "diff", "--binary", "--no-index", "--", "/dev/null", rel_path],
            cwd=repo_path,
            capture_output=True,
        )
        if diff.returncode not in {0, 1}:
            stderr = diff.stderr.decode("utf-8", errors="replace")
            raise RuntimeError(
                f"git diff --no-index failed for {repo_path / rel_path}: {stderr}"
            )
        if diff.stdout:
            patches.append(diff.stdout.decode("utf-8", errors="replace"))
    return "".join(patches)


def workspace_dirty_patch(experiment_dir: Path) -> str | None:
    """Build a patch from the first dirty git repo found in the workspace."""
    for repo_path in workspace_repo_candidates(experiment_dir):
        patch = _tracked_diff(repo_path) + _untracked_diff(repo_path)
        if patch.strip():
            return patch
    return None
