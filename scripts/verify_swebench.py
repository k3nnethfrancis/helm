#!/usr/bin/env python3
"""SWE-bench ground truth verifier.

Clones the repo at base_commit, applies test_patch (adds FAIL_TO_PASS tests),
applies the agent's patch, installs, runs tests, and reports results.

Exit codes:
- 0: resolved (all FAIL_TO_PASS pass, no PASS_TO_PASS regressions)
- 2: fail or partial
- 3: verifier error (setup failure, missing data, etc.)

Output contract matches verify_dataset_contract.py — JSON on stdout:
{
  "status": "pass|fail|partial",
  "score": 0.0-1.0,
  "reason": "...",
  "details": { ... }
}
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from helm.benchmarks.swebench_workspace import (
    DEFAULT_REPO_CACHE,
    checkout_base,
    ensure_repo,
    workspace_dirty_patch,
)


# ---------------------------------------------------------------------------
# SWE-bench environment specs
# ---------------------------------------------------------------------------
# Source: https://github.com/princeton-nlp/SWE-bench/blob/main/swebench/harness/constants/python.py

# (repo, version) → Python version required
PYTHON_VERSIONS: dict[tuple[str, str], str] = {
    # django/django
    ("django/django", "1.4"): "3.5", ("django/django", "1.5"): "3.5",
    ("django/django", "1.6"): "3.5", ("django/django", "1.7"): "3.5",
    ("django/django", "1.8"): "3.5", ("django/django", "1.9"): "3.5",
    ("django/django", "1.10"): "3.5", ("django/django", "1.11"): "3.5",
    ("django/django", "2.0"): "3.5", ("django/django", "2.1"): "3.5",
    ("django/django", "2.2"): "3.5",
    ("django/django", "3.0"): "3.6", ("django/django", "3.1"): "3.6",
    ("django/django", "3.2"): "3.6",
    ("django/django", "4.0"): "3.8",
    ("django/django", "4.1"): "3.9", ("django/django", "4.2"): "3.9",
    ("django/django", "5.0"): "3.11", ("django/django", "5.1"): "3.11",
    ("django/django", "5.2"): "3.11",
    # sympy/sympy — all versions use 3.9
    **{("sympy/sympy", v): "3.9" for v in
       ["0.7", "1.0", "1.1", "1.2", "1.4", "1.5", "1.6", "1.7", "1.8",
        "1.9", "1.10", "1.11", "1.12", "1.13", "1.14"]},
    # pytest-dev/pytest — all versions use 3.9
    **{("pytest-dev/pytest", v): "3.9" for v in
       ["4.4", "4.5", "4.6", "5.0", "5.1", "5.2", "5.3", "5.4",
        "6.0", "6.2", "6.3", "7.0", "7.1", "7.2", "7.4",
        "8.0", "8.1", "8.2", "8.3", "8.4"]},
    # scikit-learn/scikit-learn
    ("scikit-learn/scikit-learn", "0.20"): "3.6",
    ("scikit-learn/scikit-learn", "0.21"): "3.6",
    ("scikit-learn/scikit-learn", "0.22"): "3.6",
    **{("scikit-learn/scikit-learn", v): "3.9" for v in
       ["1.3", "1.4", "1.5", "1.6"]},
    # matplotlib/matplotlib
    **{("matplotlib/matplotlib", v): "3.5" for v in
       ["1.0", "1.1", "1.2", "1.3", "1.4", "1.5", "2.0", "2.1", "2.2"]},
    ("matplotlib/matplotlib", "3.0"): "3.7",
    **{("matplotlib/matplotlib", v): "3.8" for v in
       ["3.1", "3.2", "3.3", "3.4"]},
    **{("matplotlib/matplotlib", v): "3.11" for v in
       ["3.5", "3.6", "3.7", "3.8", "3.9"]},
    # sphinx-doc/sphinx — most versions use 3.9
    **{("sphinx-doc/sphinx", v): "3.9" for v in
       ["1.5", "1.6", "1.7", "1.8", "2.0", "2.1", "2.2", "2.3", "2.4",
        "3.0", "3.1", "3.2", "3.3", "3.4", "3.5",
        "4.0", "4.1", "4.2", "4.3", "4.4", "4.5",
        "5.0", "5.1", "5.2", "5.3", "6.0", "6.2",
        "7.0", "7.1", "7.2", "7.3", "7.4"]},
    ("sphinx-doc/sphinx", "8.0"): "3.10",
    ("sphinx-doc/sphinx", "8.1"): "3.10",
    # astropy/astropy
    **{("astropy/astropy", v): "3.6" for v in
       ["0.1", "0.2", "0.3", "0.4", "1.1", "1.2", "1.3"]},
    **{("astropy/astropy", v): "3.9" for v in
       ["3.0", "3.1", "3.2", "4.1", "4.2", "4.3", "5.0", "5.1", "5.2"]},
    ("astropy/astropy", "v5.3"): "3.10",
    # pydata/xarray — all 3.10
    **{("pydata/xarray", v): "3.10" for v in
       ["0.12", "0.18", "0.19", "0.20", "2022.03", "2022.06",
        "2022.09", "2023.07", "2024.05"]},
    # mwaskom/seaborn — all 3.9
    **{("mwaskom/seaborn", v): "3.9" for v in
       ["0.11", "0.12", "0.13", "0.14"]},
    # psf/requests — all 3.9
    **{("psf/requests", v): "3.9" for v in
       ["0.7", "0.8", "0.9", "0.11", "0.13", "0.14",
        "1.1", "1.2", "2.0", "2.2", "2.3", "2.4", "2.5",
        "2.7", "2.8", "2.9", "2.10", "2.11", "2.12",
        "2.17", "2.18", "2.19", "2.22", "2.25", "2.26",
        "2.27", "2.31", "3.0"]},
    # pallets/flask
    ("pallets/flask", "2.0"): "3.9",
    ("pallets/flask", "2.1"): "3.10",
    **{("pallets/flask", v): "3.11" for v in
       ["2.2", "2.3", "3.0", "3.1"]},
    # pylint-dev/pylint — all 3.9
    **{("pylint-dev/pylint", v): "3.9" for v in
       ["2.8", "2.9", "2.10", "2.11", "2.13", "2.14", "2.15",
        "2.16", "2.17", "3.0", "3.1", "3.2", "3.3", "4.0"]},
}

DEFAULT_PYTHON = "3.9"

# Repo-specific test commands.
# {test_ids} is replaced with the test specifiers.
REPO_TEST_COMMANDS: dict[str, str] = {
    "django/django": "./tests/runtests.py --verbosity 2 --settings=test_sqlite --parallel 1 {test_ids}",
    "sympy/sympy": "PYTHONWARNINGS='ignore::UserWarning,ignore::SyntaxWarning' bin/test -C --verbose {test_ids}",
    "matplotlib/matplotlib": "python -m pytest -rA {test_ids}",
    "sphinx-doc/sphinx": "python -m pytest -rA {test_ids}",
    "astropy/astropy": "python -m pytest -rA -vv -o console_output_style=classic --tb=no {test_ids}",
    "mwaskom/seaborn": "python -m pytest --no-header -rA {test_ids}",
}

DEFAULT_TEST_COMMAND = "python -m pytest -xvs {test_ids}"

# Extra pip packages needed per repo (beyond the repo itself).
REPO_EXTRA_PACKAGES: dict[str, list[str]] = {
    "sympy/sympy": ["mpmath", "flake8"],
    "pytest-dev/pytest": ["xmlschema"],
    "pylint-dev/pylint": ["astroid", "toml"],
    "sphinx-doc/sphinx": ["Jinja2"],
}

REPO_BOOTSTRAP_PACKAGES: dict[str, list[str]] = {
    # Older astropy releases still import setuptools.dep_util during editable builds.
    "astropy/astropy": ["pip<24", "setuptools<70", "wheel", "extension-helpers"],
}

REPO_EDITABLE_INSTALL_ARGS: dict[str, list[str]] = {
    # Use the bootstrapped setuptools from the env instead of an isolated latest build backend.
    "astropy/astropy": ["--no-build-isolation"],
}


# ---------------------------------------------------------------------------
# Row loading
# ---------------------------------------------------------------------------

def _load_row(dataset_path: Path, id_field: str, example_id: str) -> dict[str, Any]:
    """Load a single JSONL row by ID field."""
    with open(dataset_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                continue
            value = row.get(id_field)
            if isinstance(value, str) and value == example_id:
                return row
    raise ValueError(
        f"Example id '{example_id}' not found using field '{id_field}' in {dataset_path}"
    )


# ---------------------------------------------------------------------------
# Test ID parsing
# ---------------------------------------------------------------------------

def parse_test_ids(raw: Any) -> list[str]:
    """Parse test IDs from a JSON-encoded string or a list.

    SWE-bench stores FAIL_TO_PASS and PASS_TO_PASS as JSON strings inside
    the JSONL row, e.g. '["test_foo.TestBar.test_baz"]'. Handle both that
    and native lists.
    """
    if isinstance(raw, str):
        raw = raw.strip()
        if not raw:
            return []
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            # Treat as a single test ID
            return [raw]
        if isinstance(parsed, list):
            return [str(t) for t in parsed if t]
        if isinstance(parsed, str):
            return [parsed] if parsed else []
        return []
    if isinstance(raw, list):
        return [str(t) for t in raw if t]
    return []


def extract_test_files_from_patch(patch_text: str) -> list[str]:
    """Extract file paths from a git diff that look like test files."""
    files: list[str] = []
    for line in patch_text.split("\n"):
        if line.startswith("diff --git"):
            # e.g. "diff --git a/tests/foo.py b/tests/foo.py"
            parts = line.split()
            if len(parts) >= 4:
                path = parts[-1].lstrip("b/")
                if "test" in path.lower():
                    files.append(path)
    return files


def extract_files_from_patch(patch_text: str) -> list[str]:
    """Extract file paths touched by a git diff."""
    files: list[str] = []
    for line in patch_text.split("\n"):
        if not line.startswith("diff --git "):
            continue
        parts = line.split()
        if len(parts) < 4:
            continue
        path = parts[-1].removeprefix("b/")
        files.append(path)
    return files


def strip_patch_for_paths(patch_text: str, excluded_paths: set[str]) -> str:
    """Return a patch with file sections for excluded paths removed."""
    if not excluded_paths:
        return patch_text

    kept_sections: list[str] = []
    current: list[str] = []
    keep_current = True

    def flush() -> None:
        if current and keep_current:
            kept_sections.append("\n".join(current))

    for line in patch_text.splitlines():
        if line.startswith("diff --git "):
            flush()
            current = [line]
            parts = line.split()
            if len(parts) >= 4:
                path = parts[-1].removeprefix("b/")
                keep_current = path not in excluded_paths
            else:
                keep_current = True
            continue
        current.append(line)

    flush()

    if not kept_sections:
        return ""
    return "\n".join(kept_sections) + "\n"


def resolve_test_ids(
    test_ids: list[str],
    test_files: list[str],
    repo_path: Path,
) -> list[str]:
    """Resolve bare test function names to pytest node IDs.

    SWE-bench test IDs come in several formats:
    - Bare function name: "test_Vector"
    - Dotted module path: "tests.test_foo.TestClass.test_method"
    - Already a file path: "tests/test_foo.py::test_method"

    We use test_patch file paths to map bare names to file::function format.
    """
    resolved: list[str] = []
    for tid in test_ids:
        normalized = _normalize_unittest_style_test_id(tid)
        if normalized is not None:
            resolved.append(normalized)
            continue

        if test_files:
            descriptive = _resolve_descriptive_test_id(tid, test_files, repo_path)
            if descriptive is not None:
                resolved.append(descriptive)
                continue

        if "::" in tid:
            # Already a pytest node ID
            resolved.append(tid)
            continue

        if "/" in tid:
            # Already a file-based path
            resolved.append(tid)
            continue

        # Dotted path like "tests.models.test_foo.TestBar.test_method"
        # or bare name like "test_Vector"
        if "." in tid:
            # Try to split into file path + test node
            # Convention: dots before the test class/function are module path
            parts = tid.split(".")
            # Try progressively longer file paths
            found = False
            for i in range(len(parts) - 1, 0, -1):
                candidate_path = "/".join(parts[:i]) + ".py"
                if (repo_path / candidate_path).exists():
                    test_node = "::".join(parts[i:])
                    resolved.append(f"{candidate_path}::{test_node}")
                    found = True
                    break
            if not found:
                # Fall back: use -k matching via the full dotted name
                resolved.append(tid)
            continue

        # Bare function name — find it in test_patch files
        if test_files:
            # Search for the function in known test files
            matched = False
            for tf in test_files:
                tf_path = repo_path / tf
                if tf_path.exists():
                    try:
                        content = tf_path.read_text(errors="replace")
                        if f"def {tid}(" in content:
                            resolved.append(f"{tf}::{tid}")
                            matched = True
                            break
                    except OSError:
                        continue
            if matched:
                continue

        # Last resort: use pytest -k for pattern matching
        resolved.append(tid)

    return resolved


_UNITTEST_STYLE_RE = re.compile(
    r"^(?P<test_name>test_[\w]+)\s+\((?P<qualname>[\w.]+)\)$"
)


def _normalize_unittest_style_test_id(test_id: str) -> str | None:
    """Convert unittest-style labels into dotted test paths.

    Example:
        ``test_name (pkg.module.ClassName)`` →
        ``pkg.module.ClassName.test_name``
    """
    match = _UNITTEST_STYLE_RE.match(test_id.strip())
    if match is None:
        return None
    return f"{match.group('qualname')}.{match.group('test_name')}"


def _resolve_descriptive_test_id(
    test_id: str,
    test_files: list[str],
    repo_path: Path,
) -> str | None:
    """Map descriptive labels back to the nearest test function.

    Some Django SWE-bench rows contain docstring-style descriptions instead of
    executable test labels. Search the patched test files and return the
    nearest enclosing dotted test path when possible.
    """
    needle = test_id.strip()
    if not needle:
        return None
    if needle.startswith("test_"):
        return None

    for tf_path in _descriptive_test_search_paths(test_files, repo_path):
        try:
            lines = tf_path.read_text(errors="replace").splitlines()
        except OSError:
            continue

        current_class: str | None = None
        current_test: str | None = None
        for line in lines:
            class_match = re.match(r"^class\s+(\w+)\b", line)
            if class_match:
                current_class = class_match.group(1)
                current_test = None
                continue

            test_match = re.match(r"^\s*def\s+(test_[\w]+)\s*\(", line)
            if test_match:
                current_test = test_match.group(1)

            if needle in line and current_test:
                module = tf_path.relative_to(repo_path).as_posix().replace("/", ".")
                if module.endswith(".py"):
                    module = module[:-3]
                if current_class:
                    return f"{module}.{current_class}.{current_test}"
                return f"{module}.{current_test}"

    return None


def _descriptive_test_search_paths(
    test_files: list[str],
    repo_path: Path,
) -> list[Path]:
    """Return patched test files first, then broader repo test files.

    Some SWE-bench rows include human-readable labels in PASS_TO_PASS that do
    not live in the patched test files. Search those patched files first for
    precision, then fall back to a broader test-file scan so Django-style
    descriptive labels can still be mapped back to executable test IDs.
    """
    candidates: list[Path] = []
    seen: set[Path] = set()

    def _add(path: Path) -> None:
        if path in seen or not path.exists() or not path.is_file():
            return
        seen.add(path)
        candidates.append(path)

    for tf in test_files:
        _add(repo_path / tf)

    tests_root = repo_path / "tests"
    if tests_root.exists():
        for path in tests_root.rglob("*.py"):
            _add(path)
        return candidates

    for path in repo_path.rglob("*.py"):
        rel_parts = path.relative_to(repo_path).parts
        if "test" in path.name.lower() or any("test" in part.lower() for part in rel_parts):
            _add(path)

    return candidates


def make_working_copy(repo_path: Path) -> Path:
    """Copy cached repo to a temp dir for safe modification."""
    tmp = tempfile.mkdtemp(prefix="helm-swebench-")
    working = Path(tmp) / repo_path.name
    shutil.copytree(repo_path, working, symlinks=True)
    return working


# ---------------------------------------------------------------------------
# Patch application
# ---------------------------------------------------------------------------

def apply_patch(
    repo_path: Path,
    patch_text: str,
    label: str = "patch",
    *,
    allow_three_way: bool = False,
) -> None:
    """Apply a patch via git apply, optionally retrying with a 3-way merge."""
    result = subprocess.run(
        ["git", "apply", "--verbose", "-"],
        input=patch_text,
        cwd=repo_path,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return

    if allow_three_way:
        three_way = subprocess.run(
            ["git", "apply", "--3way", "--verbose", "-"],
            input=patch_text,
            cwd=repo_path,
            capture_output=True,
            text=True,
        )
        if three_way.returncode == 0:
            return
        raise RuntimeError(
            f"git apply ({label}) failed. "
            f"plain stderr: {result.stderr.strip()} "
            f"three-way stderr: {three_way.stderr.strip()}"
        )

    raise RuntimeError(f"git apply ({label}) failed: {result.stderr}")


def find_agent_patch(experiment_dir: Path) -> str | None:
    """Find and read the agent's patch from the experiment workspace.

    Looks for .patch or .diff files in workspace/, or a file named 'patch'.
    If no artifact exists, fall back to a git diff from a dirty workspace repo.
    """
    workspace = experiment_dir / "workspace"
    if not workspace.exists():
        return None

    # Look for patch files
    candidates = (
        list(workspace.glob("*.patch"))
        + list(workspace.glob("*.diff"))
    )
    # Also check for a plain file named 'patch'
    plain_patch = workspace / "patch"
    if plain_patch.is_file() and plain_patch not in candidates:
        candidates.append(plain_patch)

    if not candidates:
        return workspace_dirty_patch(experiment_dir)

    # Use the most recently modified one
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0].read_text(errors="replace")


# ---------------------------------------------------------------------------
# Test environment setup
# ---------------------------------------------------------------------------

def get_python_version(repo: str, version: str) -> str:
    """Look up the required Python version for a (repo, version) pair."""
    return PYTHON_VERSIONS.get((repo, version), DEFAULT_PYTHON)


@dataclass(frozen=True)
class TestEnvironment:
    """Execution environment for SWE-bench setup and test commands."""

    kind: str
    python_version: str
    venv_path: Path
    docker_image: str | None = None


def _python_version_tuple(version: str) -> tuple[int, ...]:
    parts = []
    for piece in version.split("."):
        if piece.isdigit():
            parts.append(int(piece))
        else:
            break
    return tuple(parts)


def _requires_docker_fallback(python_version: str) -> bool:
    """Return True when the requested Python version is too old for local uv."""
    version_tuple = _python_version_tuple(python_version)
    return version_tuple != () and version_tuple < (3, 7)


def _docker_available() -> bool:
    return shutil.which("docker") is not None


def _conda_executable() -> str | None:
    for candidate in ("mamba", "conda"):
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    return None


def _conda_create_env_vars(python_version: str) -> dict[str, str]:
    env = dict(os.environ)
    version_tuple = _python_version_tuple(python_version)
    if (
        sys.platform == "darwin"
        and platform.machine() in {"arm64", "aarch64"}
        and version_tuple != ()
        and version_tuple < (3, 8)
    ):
        env["CONDA_SUBDIR"] = "osx-64"
    return env


def _docker_image_for_python(python_version: str) -> str:
    override = os.environ.get("HELM_SWEBENCH_DOCKER_IMAGE")
    if override:
        return override
    return f"python:{python_version}"


def _docker_command(
    repo_path: Path,
    image: str,
    shell_command: str,
) -> list[str]:
    command = [
        "docker",
        "run",
        "--rm",
        "-v",
        f"{repo_path}:{repo_path}",
        "-w",
        str(repo_path),
    ]

    if hasattr(os, "getuid") and hasattr(os, "getgid"):
        command.extend(["--user", f"{os.getuid()}:{os.getgid()}"])

    command.extend([image, "/bin/sh", "-lc", shell_command])
    return command


def _docker_shell_prefix(venv_path: Path) -> str:
    venv = shlex.quote(str(venv_path))
    venv_bin = shlex.quote(str(venv_path / "bin"))
    return f"export VIRTUAL_ENV={venv}; export PATH={venv_bin}:$PATH; "


def _run_docker_shell(
    repo_path: Path,
    image: str,
    shell_command: str,
    *,
    timeout: int,
    use_venv: bool = False,
) -> subprocess.CompletedProcess[str]:
    command = shell_command
    if use_venv:
        command = _docker_shell_prefix(repo_path / ".venv") + shell_command
    return subprocess.run(
        _docker_command(repo_path, image, command),
        cwd=repo_path,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _legacy_bootstrap_packages(python_version: str) -> list[str]:
    version_tuple = _python_version_tuple(python_version)
    if version_tuple != () and version_tuple < (3, 7):
        return ["pip<22", "setuptools<60", "wheel<0.38"]
    if version_tuple != () and version_tuple < (3, 8):
        return ["pip<24", "setuptools<70", "wheel"]
    return ["pip", "setuptools", "wheel"]


def _bootstrap_packages(repo: str, python_version: str) -> list[str]:
    return REPO_BOOTSTRAP_PACKAGES.get(repo, _legacy_bootstrap_packages(python_version))


def _editable_install_command(prefix: list[str], repo: str) -> list[str]:
    command = [*prefix, "install", "-e", "."]
    command.extend(REPO_EDITABLE_INSTALL_ARGS.get(repo, []))
    command.append("--quiet")
    return command


def _local_test_env_vars(venv_path: Path) -> dict[str, str]:
    env = dict(os.environ)
    env["VIRTUAL_ENV"] = str(venv_path)
    env["PATH"] = f"{venv_path / 'bin'}:{env.get('PATH', '')}"
    return env


def _setup_conda_test_env(
    repo_path: Path,
    repo: str,
    python_version: str,
    timeout: int,
) -> tuple[TestEnvironment | None, str | None]:
    conda_exe = _conda_executable()
    if conda_exe is None:
        return None, f"Conda fallback unavailable for Python {python_version}."

    venv_path = repo_path / ".venv"
    result = subprocess.run(
        [
            conda_exe,
            "create",
            "-p",
            str(venv_path),
            "-c",
            "conda-forge",
            "--override-channels",
            f"python={python_version}",
            "pip",
            "-y",
            "-q",
        ],
        cwd=repo_path,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=_conda_create_env_vars(python_version),
    )
    if result.returncode != 0:
        return None, f"{Path(conda_exe).name} create python={python_version} failed: {result.stderr or result.stdout}"

    pip_env = _local_test_env_vars(venv_path)
    bootstrap = _bootstrap_packages(repo, python_version)
    setup_steps: list[tuple[str, list[str]]] = [
        ("bootstrap packaging", ["python", "-m", "pip", "install", "--quiet", "--upgrade", *bootstrap]),
        ("install editable repo", _editable_install_command(["python", "-m", "pip"], repo)),
        ("install pytest", ["python", "-m", "pip", "install", "--quiet", "pytest"]),
    ]

    extras = REPO_EXTRA_PACKAGES.get(repo, [])
    if extras:
        setup_steps.append(
            ("install repo extras", ["python", "-m", "pip", "install", "--quiet", *extras])
        )

    for label, command in setup_steps:
        result = subprocess.run(
            command,
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=pip_env,
        )
        if result.returncode != 0:
            return None, f"{Path(conda_exe).name} setup ({label}) failed for python {python_version}: {result.stderr or result.stdout}"

    return (
        TestEnvironment(
            kind="conda",
            python_version=python_version,
            venv_path=venv_path,
        ),
        None,
    )


def _setup_docker_test_env(
    repo_path: Path,
    repo: str,
    python_version: str,
    timeout: int,
) -> tuple[TestEnvironment | None, str | None]:
    if not _docker_available():
        return (
            None,
            f"Python {python_version} requires Docker fallback, but docker is not available.",
        )

    image = _docker_image_for_python(python_version)
    venv_path = repo_path / ".venv"
    test_env = TestEnvironment(
        kind="docker",
        python_version=python_version,
        venv_path=venv_path,
        docker_image=image,
    )

    setup_steps: list[tuple[str, str, bool]] = [
        ("create venv", f"python -m venv {shlex.quote(str(venv_path))}", False),
        (
            "bootstrap packaging",
            "python -m pip install --quiet --upgrade "
            + " ".join(shlex.quote(pkg) for pkg in _bootstrap_packages(repo, python_version)),
            True,
        ),
        (
            "install editable repo",
            " ".join(shlex.quote(part) for part in _editable_install_command(["python", "-m", "pip"], repo)),
            True,
        ),
        ("install pytest", "python -m pip install --quiet pytest", True),
    ]

    extras = REPO_EXTRA_PACKAGES.get(repo, [])
    if extras:
        setup_steps.append(
            (
                "install repo extras",
                "python -m pip install --quiet "
                + " ".join(shlex.quote(pkg) for pkg in extras),
                True,
            )
        )

    for label, command, use_venv in setup_steps:
        result = _run_docker_shell(
            repo_path,
            image,
            command,
            timeout=timeout,
            use_venv=use_venv,
        )
        if result.returncode != 0:
            stderr = result.stderr.strip()
            stdout = result.stdout.strip()
            detail = stderr or stdout or "unknown docker setup error"
            return (
                None,
                f"docker setup ({label}) failed for python {python_version}: {detail}",
            )

    return test_env, None


def setup_test_env(
    repo_path: Path,
    repo: str,
    version: str,
    timeout: int,
) -> tuple[TestEnvironment | None, str | None]:
    """Create a test env and install repo/test deps. Returns env + error."""
    python_version = get_python_version(repo, version)
    venv_path = repo_path / ".venv"

    if _requires_docker_fallback(python_version):
        conda_env, conda_err = _setup_conda_test_env(
            repo_path,
            repo,
            python_version,
            timeout,
        )
        if conda_env is not None:
            return conda_env, None

        docker_env, docker_err = _setup_docker_test_env(
            repo_path,
            repo,
            python_version,
            timeout,
        )
        if docker_env is not None:
            return docker_env, None

        combined_errors = [err for err in (conda_err, docker_err) if err]
        return None, " ".join(combined_errors) if combined_errors else (
            f"No legacy Python fallback succeeded for Python {python_version}."
        )

    # Create venv with the correct Python version
    result = subprocess.run(
        ["uv", "venv", str(venv_path), "--python", python_version],
        cwd=repo_path,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        return None, f"uv venv --python {python_version} failed: {result.stderr}"

    pip_env = _local_test_env_vars(venv_path)

    bootstrap = _bootstrap_packages(repo, python_version)

    result = subprocess.run(
        ["uv", "pip", "install", "--upgrade", *bootstrap, "--quiet"],
        cwd=repo_path,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=pip_env,
    )
    if result.returncode != 0:
        return None, f"uv pip bootstrap failed: {result.stderr}"

    # Install the project in editable mode
    result = subprocess.run(
        _editable_install_command(["uv", "pip"], repo),
        cwd=repo_path,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=pip_env,
    )
    if result.returncode != 0:
        return None, f"uv pip install -e . failed: {result.stderr}"

    # Install pytest (needed by most repos)
    result = subprocess.run(
        ["uv", "pip", "install", "pytest", "--quiet"],
        cwd=repo_path,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=pip_env,
    )
    if result.returncode != 0:
        return None, f"uv pip install pytest failed: {result.stderr}"

    # Install repo-specific extra packages
    extras = REPO_EXTRA_PACKAGES.get(repo, [])
    if extras:
        result = subprocess.run(
            ["uv", "pip", "install", *extras, "--quiet"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=pip_env,
        )
        if result.returncode != 0:
            return None, f"uv pip install extras {extras} failed: {result.stderr}"

    return (
        TestEnvironment(
            kind="local",
            python_version=python_version,
            venv_path=venv_path,
        ),
        None,
    )


# ---------------------------------------------------------------------------
# Test execution
# ---------------------------------------------------------------------------

def get_test_command(repo: str) -> str:
    """Return the test command template for a repo."""
    return REPO_TEST_COMMANDS.get(repo, DEFAULT_TEST_COMMAND)


def _pytest_arg_for_id(test_id: str) -> tuple[str, bool]:
    """Return (pytest argument, uses_keyword_match).

    If test_id is a proper node (file::func), return it directly.
    If it's a bare name, use -k matching.
    """
    if "::" in test_id or "/" in test_id or test_id.endswith(".py"):
        return test_id, False
    # Bare name or unresolved — use -k
    return test_id, True


# Characters allowed in test IDs: alphanumeric, underscore, dot, slash,
# colon, hyphen, square brackets (pytest parameterize). Reject anything
# else to prevent shell injection via dataset-controlled strings.
_UNSAFE_TEST_ID_RE = re.compile(r"[\x00-\x1f\x7f\r\n]")


def _sanitize_test_id(test_id: str) -> str:
    """Reject control characters before shell-quoting the test identifier."""
    if _UNSAFE_TEST_ID_RE.search(test_id):
        raise ValueError(
            f"Test ID contains disallowed characters (possible injection): {test_id!r}"
        )
    return test_id


def run_tests(
    repo_path: Path,
    test_ids: list[str],
    repo: str,
    test_env: TestEnvironment,
    timeout: int,
) -> dict[str, bool]:
    """Run test IDs and return {test_id: passed}."""
    if not test_ids:
        return {}

    command_template = get_test_command(repo)
    venv_bin = test_env.venv_path / "bin"

    env = {**os.environ, "VIRTUAL_ENV": str(test_env.venv_path)}
    env["PATH"] = f"{venv_bin}:{env.get('PATH', '')}"

    results: dict[str, bool] = {}

    # Run each test individually for granular results
    for test_id in test_ids:
        safe_id = _sanitize_test_id(test_id)
        arg, uses_keyword = _pytest_arg_for_id(safe_id)
        quoted_arg = shlex.quote(arg)

        if uses_keyword and "pytest" in command_template:
            # Use -k for keyword matching on bare names
            command = command_template.replace("{test_ids}", f"-k {quoted_arg}")
        else:
            command = command_template.replace("{test_ids}", quoted_arg)

        try:
            # shell=True is required for repo-specific commands that use
            # shell syntax (e.g. sympy's PYTHONWARNINGS='...' env prefix).
            # Test IDs are sanitized above to prevent injection.
            if test_env.kind == "docker":
                proc = _run_docker_shell(
                    repo_path,
                    test_env.docker_image or _docker_image_for_python(test_env.python_version),
                    command,
                    timeout=timeout,
                    use_venv=True,
                )
            else:
                proc = subprocess.run(
                    command,
                    shell=True,
                    cwd=repo_path,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    env=env,
                )
            results[test_id] = proc.returncode == 0
        except subprocess.TimeoutExpired:
            results[test_id] = False

    return results


# ---------------------------------------------------------------------------
# Verification computation
# ---------------------------------------------------------------------------

def compute_verification(
    fail_to_pass_results: dict[str, bool],
    pass_to_pass_results: dict[str, bool],
    setup_error: str | None = None,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    """Compute the final verification payload from test results."""
    warning_list = warnings or []
    if setup_error is not None:
        return {
            "status": "fail",
            "score": 0.0,
            "reason": f"Setup error: {setup_error}",
            "details": {
                "fail_to_pass_passed": 0,
                "fail_to_pass_total": 0,
                "pass_to_pass_passed": 0,
                "pass_to_pass_total": 0,
                "swebench_resolved": False,
                "partial_score": 0.0,
                "setup_error": setup_error,
                "warnings": warning_list,
            },
        }

    f2p_total = len(fail_to_pass_results)
    f2p_passed = sum(1 for v in fail_to_pass_results.values() if v)

    p2p_total = len(pass_to_pass_results)
    p2p_passed = sum(1 for v in pass_to_pass_results.values() if v)

    has_regressions = p2p_passed < p2p_total
    all_f2p_pass = f2p_total > 0 and f2p_passed == f2p_total
    resolved = all_f2p_pass and not has_regressions

    # Score: weighted average — FAIL_TO_PASS is primary, regressions penalize
    if f2p_total == 0:
        partial_score = 0.0
    else:
        f2p_score = f2p_passed / f2p_total
        regression_penalty = (1.0 - p2p_passed / p2p_total) if p2p_total > 0 else 0.0
        partial_score = max(0.0, f2p_score - regression_penalty)

    if resolved:
        status = "pass"
        score = 1.0
        reason = f"Resolved: {f2p_passed}/{f2p_total} FAIL_TO_PASS pass, 0 regressions"
    elif f2p_passed > 0:
        status = "partial"
        score = round(partial_score, 4)
        regressions = p2p_total - p2p_passed
        reason = f"{f2p_passed}/{f2p_total} FAIL_TO_PASS pass, {regressions} regressions"
    else:
        status = "fail"
        score = 0.0
        reason = f"0/{f2p_total} FAIL_TO_PASS pass"

    return {
        "status": status,
        "score": score,
        "reason": reason,
        "details": {
            "fail_to_pass_passed": f2p_passed,
            "fail_to_pass_total": f2p_total,
            "pass_to_pass_passed": p2p_passed,
            "pass_to_pass_total": p2p_total,
            "swebench_resolved": resolved,
            "partial_score": round(partial_score, 4),
            "setup_error": None,
            "warnings": warning_list,
        },
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="SWE-bench ground truth verifier"
    )
    parser.add_argument("--instance-id", required=True, help="SWE-bench instance ID")
    parser.add_argument("--experiment-dir", required=True, type=Path)
    parser.add_argument("--dataset-path", required=True, type=Path)
    parser.add_argument(
        "--repo-cache",
        type=Path,
        default=DEFAULT_REPO_CACHE,
    )
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--id-field", default="instance_id")
    args = parser.parse_args()

    def _emit_error(msg: str) -> int:
        payload = {
            "status": "fail",
            "score": 0.0,
            "reason": f"Verifier error: {msg}",
            "details": {"setup_error": msg},
        }
        print(json.dumps(payload))
        return 3

    working_copy: Path | None = None
    warnings: list[str] = []

    try:
        # 1. Load the dataset row
        row = _load_row(args.dataset_path, args.id_field, args.instance_id)

        # 2. Parse test IDs
        fail_to_pass = parse_test_ids(row.get("FAIL_TO_PASS", []))
        pass_to_pass = parse_test_ids(row.get("PASS_TO_PASS", []))

        if not fail_to_pass:
            return _emit_error("No FAIL_TO_PASS tests found in dataset row")

        repo = row.get("repo", "")
        base_commit = row.get("base_commit", "")
        version = row.get("version", "")
        test_patch = row.get("test_patch", "")

        if not repo or not base_commit:
            return _emit_error(f"Missing repo ({repo!r}) or base_commit ({base_commit!r})")

        # 3. Ensure repo is cached
        args.repo_cache.mkdir(parents=True, exist_ok=True)
        repo_path = ensure_repo(repo, args.repo_cache)

        # 4. Make a working copy for safe modification
        working_copy = make_working_copy(repo_path)

        # 5. Checkout base commit
        checkout_base(working_copy, base_commit)

        # 6. Apply test_patch (adds FAIL_TO_PASS test definitions)
        test_files: list[str] = []
        if test_patch:
            test_files = extract_test_files_from_patch(test_patch)
            apply_patch(working_copy, test_patch, label="test_patch")

        # 7. Apply agent's changes
        agent_patch = find_agent_patch(args.experiment_dir)
        if agent_patch:
            try:
                apply_patch(
                    working_copy,
                    agent_patch,
                    label="agent_patch",
                    allow_three_way=True,
                )
            except RuntimeError:
                overlapping_test_files = set(test_files) & set(extract_files_from_patch(agent_patch))
                filtered_patch = strip_patch_for_paths(agent_patch, set(test_files))
                if overlapping_test_files and filtered_patch.strip():
                    apply_patch(
                        working_copy,
                        filtered_patch,
                        label="agent_patch_without_benchmark_tests",
                        allow_three_way=True,
                    )
                    warnings.append(
                        "Ignored agent edits to benchmark-owned test files during verification: "
                        + ", ".join(sorted(overlapping_test_files))
                    )
                elif overlapping_test_files:
                    warnings.append(
                        "Ignored agent patch because it only modified benchmark-owned test files: "
                        + ", ".join(sorted(overlapping_test_files))
                    )
                else:
                    raise

        # 8. Resolve bare test IDs to pytest node IDs
        fail_to_pass = resolve_test_ids(fail_to_pass, test_files, working_copy)
        pass_to_pass = resolve_test_ids(pass_to_pass, test_files, working_copy)

        # 9. Setup test environment
        test_env, setup_err = setup_test_env(
            working_copy,
            repo,
            version,
            timeout=args.timeout,
        )
        if setup_err:
            result = compute_verification({}, {}, setup_error=setup_err, warnings=warnings)
            print(json.dumps(result))
            return 2
        if test_env is None:
            return _emit_error("setup_test_env returned no environment and no error")

        # 10. Run tests
        f2p_results = run_tests(
            working_copy,
            fail_to_pass,
            repo,
            test_env=test_env,
            timeout=args.timeout,
        )
        p2p_results = run_tests(
            working_copy,
            pass_to_pass,
            repo,
            test_env=test_env,
            timeout=args.timeout,
        )

        # 11. Compute and emit result
        result = compute_verification(f2p_results, p2p_results, warnings=warnings)
        print(json.dumps(result))

        if result["status"] == "pass":
            return 0
        return 2

    except Exception as e:
        return _emit_error(str(e))

    finally:
        # Clean up working copy
        if working_copy is not None and working_copy.exists():
            shutil.rmtree(working_copy, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
