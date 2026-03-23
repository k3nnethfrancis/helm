"""Unit tests for verify_swebench.py pure logic (no repo cloning)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

# Add scripts dir so we can import verify_swebench as a module
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import verify_swebench  # noqa: E402


# ---------------------------------------------------------------------------
# parse_test_ids
# ---------------------------------------------------------------------------


def test_parse_test_ids_from_json_string() -> None:
    raw = '["tests.test_foo.TestBar.test_baz", "tests.test_foo.TestBar.test_qux"]'
    result = verify_swebench.parse_test_ids(raw)
    assert result == [
        "tests.test_foo.TestBar.test_baz",
        "tests.test_foo.TestBar.test_qux",
    ]


def test_parse_test_ids_from_list() -> None:
    raw = ["test_a", "test_b", "test_c"]
    result = verify_swebench.parse_test_ids(raw)
    assert result == ["test_a", "test_b", "test_c"]


def test_parse_test_ids_from_single_string() -> None:
    # Not JSON — just a bare test ID
    result = verify_swebench.parse_test_ids("test_module.TestClass.test_method")
    assert result == ["test_module.TestClass.test_method"]


def test_parse_test_ids_empty_string() -> None:
    assert verify_swebench.parse_test_ids("") == []


def test_parse_test_ids_empty_list() -> None:
    assert verify_swebench.parse_test_ids([]) == []


def test_parse_test_ids_none() -> None:
    assert verify_swebench.parse_test_ids(None) == []


def test_parse_test_ids_filters_falsy_items() -> None:
    assert verify_swebench.parse_test_ids(["test_a", "", "test_b"]) == [
        "test_a",
        "test_b",
    ]


# ---------------------------------------------------------------------------
# compute_verification
# ---------------------------------------------------------------------------


def test_compute_verification_full_pass() -> None:
    result = verify_swebench.compute_verification(
        fail_to_pass_results={"test_a": True, "test_b": True},
        pass_to_pass_results={"test_c": True, "test_d": True},
    )
    assert result["status"] == "pass"
    assert result["score"] == 1.0
    assert result["details"]["swebench_resolved"] is True
    assert result["details"]["fail_to_pass_passed"] == 2
    assert result["details"]["fail_to_pass_total"] == 2
    assert result["details"]["pass_to_pass_passed"] == 2
    assert result["details"]["pass_to_pass_total"] == 2


def test_compute_verification_partial() -> None:
    result = verify_swebench.compute_verification(
        fail_to_pass_results={
            "test_a": True,
            "test_b": True,
            "test_c": True,
            "test_d": False,
        },
        pass_to_pass_results={"test_e": True},
    )
    assert result["status"] == "partial"
    assert result["details"]["swebench_resolved"] is False
    assert result["details"]["fail_to_pass_passed"] == 3
    assert result["details"]["fail_to_pass_total"] == 4
    assert result["score"] == 0.75


def test_compute_verification_regression() -> None:
    """PASS_TO_PASS failure prevents resolved even if all FAIL_TO_PASS pass."""
    result = verify_swebench.compute_verification(
        fail_to_pass_results={"test_a": True, "test_b": True},
        pass_to_pass_results={"test_c": True, "test_d": False},
    )
    assert result["status"] != "pass"
    assert result["details"]["swebench_resolved"] is False
    assert result["details"]["pass_to_pass_passed"] == 1
    assert result["details"]["pass_to_pass_total"] == 2


def test_compute_verification_total_fail() -> None:
    result = verify_swebench.compute_verification(
        fail_to_pass_results={"test_a": False, "test_b": False},
        pass_to_pass_results={"test_c": True},
    )
    assert result["status"] == "fail"
    assert result["score"] == 0.0
    assert result["details"]["swebench_resolved"] is False


def test_compute_verification_no_pass_to_pass() -> None:
    """Works when there are no PASS_TO_PASS tests."""
    result = verify_swebench.compute_verification(
        fail_to_pass_results={"test_a": True},
        pass_to_pass_results={},
    )
    assert result["status"] == "pass"
    assert result["score"] == 1.0
    assert result["details"]["swebench_resolved"] is True


def test_compute_verification_setup_error() -> None:
    result = verify_swebench.compute_verification(
        fail_to_pass_results={},
        pass_to_pass_results={},
        setup_error="uv venv failed",
    )
    assert result["status"] == "fail"
    assert result["score"] == 0.0
    assert "Setup error" in result["reason"]
    assert result["details"]["setup_error"] == "uv venv failed"


def test_compute_verification_includes_warnings() -> None:
    result = verify_swebench.compute_verification(
        fail_to_pass_results={"test_a": True},
        pass_to_pass_results={},
        warnings=["ignored benchmark-owned test edits"],
    )
    assert result["details"]["warnings"] == ["ignored benchmark-owned test edits"]


def test_sanitize_test_id_allows_parameterized_pytest_nodes() -> None:
    test_id = "lib/matplotlib/tests/test_patches.py::test_boxstyle_errors[Round,foo-Incorrect]"
    assert verify_swebench._sanitize_test_id(test_id) == test_id


def test_sanitize_test_id_rejects_control_characters() -> None:
    with pytest.raises(ValueError):
        verify_swebench._sanitize_test_id("tests/test_example.py::test_bad\nrm -rf /")


def test_resolve_descriptive_test_id_tolerates_non_utf8_files(tmp_path: Path) -> None:
    test_file = tmp_path / "tests" / "test_weird.py"
    test_file.parent.mkdir()
    test_file.write_bytes(
        b"def test_ascii():\n"
        b"    pass\n\n"
        b"# \xff\xd5 non-utf8 bytes\n"
        b"def test_target():\n"
        b"    \"\"\"Human readable label\"\"\"\n"
        b"    pass\n"
    )

    result = verify_swebench._resolve_descriptive_test_id(
        "Human readable label",
        ["tests/test_weird.py"],
        tmp_path,
    )

    assert result == "tests.test_weird.test_target"


# ---------------------------------------------------------------------------
# _load_row
# ---------------------------------------------------------------------------


def test_load_row(tmp_path: Path) -> None:
    dataset = tmp_path / "data.jsonl"
    rows = [
        {"instance_id": "django__django-12345", "repo": "django/django"},
        {"instance_id": "flask__flask-6789", "repo": "pallets/flask"},
    ]
    with open(dataset, "w") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")

    result = verify_swebench._load_row(dataset, "instance_id", "flask__flask-6789")
    assert result["repo"] == "pallets/flask"


def test_load_row_not_found(tmp_path: Path) -> None:
    dataset = tmp_path / "data.jsonl"
    dataset.write_text('{"instance_id": "abc"}\n')

    with pytest.raises(ValueError, match="not found"):
        verify_swebench._load_row(dataset, "instance_id", "nonexistent")


# ---------------------------------------------------------------------------
# find_agent_patch
# ---------------------------------------------------------------------------


def test_find_agent_patch_from_patch_file(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    patch = workspace / "solution.patch"
    patch.write_text("diff --git a/foo.py b/foo.py\n--- a/foo.py\n+++ b/foo.py\n")

    result = verify_swebench.find_agent_patch(tmp_path)
    assert result is not None
    assert "foo.py" in result


def test_find_agent_patch_from_diff_file(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    diff = workspace / "changes.diff"
    diff.write_text("--- a/bar.py\n+++ b/bar.py\n")

    result = verify_swebench.find_agent_patch(tmp_path)
    assert result is not None
    assert "bar.py" in result


def test_find_agent_patch_no_workspace(tmp_path: Path) -> None:
    result = verify_swebench.find_agent_patch(tmp_path)
    assert result is None


def test_find_agent_patch_empty_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    result = verify_swebench.find_agent_patch(tmp_path)
    assert result is None


def test_find_agent_patch_falls_back_to_workspace_git_diff(tmp_path: Path) -> None:
    workspace_repo = tmp_path / "workspace" / "repo"
    workspace_repo.mkdir(parents=True)

    subprocess.run(["git", "init"], cwd=workspace_repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.name", "Helm Test"],
        cwd=workspace_repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "helm@example.com"],
        cwd=workspace_repo,
        check=True,
        capture_output=True,
    )

    tracked = workspace_repo / "tracked.py"
    tracked.write_text("value = 1\n")
    subprocess.run(
        ["git", "add", "tracked.py"],
        cwd=workspace_repo,
        check=True,
        capture_output=True,
    )
    env = dict(
        os.environ,
        GIT_AUTHOR_DATE="2026-03-08T00:00:00+0000",
        GIT_COMMITTER_DATE="2026-03-08T00:00:00+0000",
    )
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=workspace_repo,
        check=True,
        capture_output=True,
        env=env,
    )

    tracked.write_text("value = 2\n")
    new_file = workspace_repo / "new_file.py"
    new_file.write_text("created = True\n")

    result = verify_swebench.find_agent_patch(tmp_path)

    assert result is not None
    assert "tracked.py" in result
    assert "new_file.py" in result


def test_find_agent_patch_prefers_newest(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    old = workspace / "old.patch"
    old.write_text("old content")
    new = workspace / "new.patch"
    new.write_text("new content")
    # Touch new to ensure it's newer
    import time

    time.sleep(0.01)
    new.write_text("new content")

    result = verify_swebench.find_agent_patch(tmp_path)
    assert result == "new content"


def test_strip_patch_for_paths_removes_hidden_test_overlap() -> None:
    patch_text = (
        "diff --git a/tests.py b/tests.py\n"
        "--- a/tests.py\n"
        "+++ b/tests.py\n"
        "@@ -1,2 +1,5 @@\n"
        " def test_existing():\n"
        "     assert True\n"
        "+\n"
        "+def test_agent_added():\n"
        "+    assert 1 == 1\n"
        "diff --git a/app.py b/app.py\n"
        "--- a/app.py\n"
        "+++ b/app.py\n"
        "@@ -1 +1 @@\n"
        "-value = 1\n"
        "+value = 2\n"
    )

    filtered = verify_swebench.strip_patch_for_paths(patch_text, {"tests.py"})

    assert "tests.py" not in filtered
    assert "app.py" in filtered


# ---------------------------------------------------------------------------
# get_test_command
# ---------------------------------------------------------------------------


def test_get_test_command_default() -> None:
    cmd = verify_swebench.get_test_command("pallets/flask")
    assert "pytest" in cmd


def test_get_test_command_django() -> None:
    cmd = verify_swebench.get_test_command("django/django")
    assert "runtests.py" in cmd


def test_get_test_command_sympy() -> None:
    cmd = verify_swebench.get_test_command("sympy/sympy")
    assert "bin/test" in cmd


# ---------------------------------------------------------------------------
# get_python_version
# ---------------------------------------------------------------------------


def test_get_python_version_known() -> None:
    assert verify_swebench.get_python_version("sympy/sympy", "1.4") == "3.9"
    assert verify_swebench.get_python_version("django/django", "5.0") == "3.11"
    assert verify_swebench.get_python_version("django/django", "3.0") == "3.6"
    assert verify_swebench.get_python_version("matplotlib/matplotlib", "3.5") == "3.11"


def test_get_python_version_unknown_falls_back() -> None:
    assert verify_swebench.get_python_version("unknown/repo", "1.0") == "3.9"


def test_requires_docker_fallback_for_legacy_python() -> None:
    assert verify_swebench._requires_docker_fallback("3.5") is True
    assert verify_swebench._requires_docker_fallback("3.6") is True
    assert verify_swebench._requires_docker_fallback("3.7") is False
    assert verify_swebench._requires_docker_fallback("3.11") is False


def test_setup_test_env_legacy_python_without_docker(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(verify_swebench, "_conda_executable", lambda: None)
    monkeypatch.setattr(verify_swebench, "_docker_available", lambda: False)

    env, error = verify_swebench.setup_test_env(
        tmp_path,
        "django/django",
        "3.0",
        timeout=30,
    )

    assert env is None
    assert error is not None
    assert "fallback" in error


def test_setup_test_env_legacy_python_uses_conda_first(tmp_path: Path, monkeypatch) -> None:
    calls: list[tuple[list[str], dict[str, str] | None]] = []

    def _fake_run(args, **kwargs):
        calls.append((list(args), kwargs.get("env")))
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(verify_swebench, "_conda_executable", lambda: "/usr/bin/conda")
    monkeypatch.setattr(verify_swebench.platform, "machine", lambda: "arm64")
    monkeypatch.setattr(verify_swebench.sys, "platform", "darwin")
    monkeypatch.delenv("CONDA_SUBDIR", raising=False)
    monkeypatch.setattr(verify_swebench.subprocess, "run", _fake_run)

    env, error = verify_swebench.setup_test_env(
        tmp_path,
        "django/django",
        "3.0",
        timeout=30,
    )

    assert error is None
    assert env is not None
    assert env.kind == "conda"
    assert env.python_version == "3.6"
    assert calls[0][0][:8] == [
        "/usr/bin/conda",
        "create",
        "-p",
        str(tmp_path / ".venv"),
        "-c",
        "conda-forge",
        "--override-channels",
        "python=3.6",
    ]
    assert calls[0][0][8] == "pip"
    assert calls[0][1] is not None
    assert calls[0][1]["CONDA_SUBDIR"] == "osx-64"


def test_conda_create_env_vars_legacy_python_on_arm64_darwin(monkeypatch) -> None:
    monkeypatch.setattr(verify_swebench.platform, "machine", lambda: "arm64")
    monkeypatch.setattr(verify_swebench.sys, "platform", "darwin")
    monkeypatch.delenv("CONDA_SUBDIR", raising=False)

    env = verify_swebench._conda_create_env_vars("3.6")

    assert env["CONDA_SUBDIR"] == "osx-64"


def test_conda_create_env_vars_modern_python_has_no_platform_override(monkeypatch) -> None:
    monkeypatch.setattr(verify_swebench.platform, "machine", lambda: "arm64")
    monkeypatch.setattr(verify_swebench.sys, "platform", "darwin")
    monkeypatch.delenv("CONDA_SUBDIR", raising=False)

    env = verify_swebench._conda_create_env_vars("3.9")

    assert "CONDA_SUBDIR" not in env or env["CONDA_SUBDIR"] != "osx-64"


def test_setup_test_env_legacy_python_uses_docker(tmp_path: Path, monkeypatch) -> None:
    calls: list[tuple[str, bool]] = []

    def _fake_run_docker_shell(repo_path, image, shell_command, *, timeout, use_venv=False):
        calls.append((shell_command, use_venv))
        return subprocess.CompletedProcess(args=["docker"], returncode=0, stdout="", stderr="")

    monkeypatch.setattr(verify_swebench, "_setup_conda_test_env", lambda *args, **kwargs: (None, "conda unavailable"))
    monkeypatch.setattr(verify_swebench, "_docker_available", lambda: True)
    monkeypatch.setattr(verify_swebench, "_docker_image_for_python", lambda version: f"python:{version}")
    monkeypatch.setattr(verify_swebench, "_run_docker_shell", _fake_run_docker_shell)

    env, error = verify_swebench.setup_test_env(
        tmp_path,
        "django/django",
        "3.0",
        timeout=30,
    )

    assert error is None
    assert env is not None
    assert env.kind == "docker"
    assert env.python_version == "3.6"
    assert env.docker_image == "python:3.6"
    assert calls[0] == (f"python -m venv {verify_swebench.shlex.quote(str(tmp_path / '.venv'))}", False)
    assert any("python -m pip install --quiet --upgrade" in command for command, _ in calls)
    assert any("python -m pip install -e ." in command for command, _ in calls)


def test_setup_test_env_local_returns_local_environment(tmp_path: Path, monkeypatch) -> None:
    recorded: list[list[str]] = []

    def _fake_run(args, **kwargs):
        recorded.append(list(args))
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(verify_swebench.subprocess, "run", _fake_run)

    env, error = verify_swebench.setup_test_env(
        tmp_path,
        "sympy/sympy",
        "1.4",
        timeout=30,
    )

    assert error is None
    assert env is not None
    assert env.kind == "local"
    assert env.python_version == "3.9"
    assert recorded[0][:4] == ["uv", "venv", str(tmp_path / ".venv"), "--python"]
    assert recorded[1][:4] == ["uv", "pip", "install", "--upgrade"]
    assert recorded[2][:4] == ["uv", "pip", "install", "-e"]


def test_setup_test_env_local_uses_repo_specific_bootstrap_for_astropy(tmp_path: Path, monkeypatch) -> None:
    recorded: list[list[str]] = []

    def _fake_run(args, **kwargs):
        recorded.append(list(args))
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(verify_swebench.subprocess, "run", _fake_run)

    env, error = verify_swebench.setup_test_env(
        tmp_path,
        "astropy/astropy",
        "5.2",
        timeout=30,
    )

    assert error is None
    assert env is not None
    assert env.kind == "local"
    assert "setuptools<70" in recorded[1]
    assert "extension-helpers" in recorded[1]
    assert "--no-build-isolation" in recorded[2]


# ---------------------------------------------------------------------------
# extract_test_files_from_patch
# ---------------------------------------------------------------------------


def test_extract_test_files_from_patch() -> None:
    patch = (
        "diff --git a/sympy/physics/vector/tests/test_vector.py "
        "b/sympy/physics/vector/tests/test_vector.py\n"
        "--- a/sympy/physics/vector/tests/test_vector.py\n"
        "+++ b/sympy/physics/vector/tests/test_vector.py\n"
        "@@ -13,6 +13,8 @@\n"
        "+    assert A.x + 0 == A.x\n"
    )
    result = verify_swebench.extract_test_files_from_patch(patch)
    assert result == ["sympy/physics/vector/tests/test_vector.py"]


def test_extract_test_files_ignores_non_test_files() -> None:
    patch = (
        "diff --git a/src/main.py b/src/main.py\n"
        "--- a/src/main.py\n"
        "+++ b/src/main.py\n"
    )
    result = verify_swebench.extract_test_files_from_patch(patch)
    assert result == []


# ---------------------------------------------------------------------------
# resolve_test_ids
# ---------------------------------------------------------------------------


def test_resolve_test_ids_bare_name_matched(tmp_path: Path) -> None:
    """Bare function name is resolved to file::func when found in test files."""
    test_file = tmp_path / "tests" / "test_foo.py"
    test_file.parent.mkdir(parents=True)
    test_file.write_text("def test_bar():\n    pass\n")

    result = verify_swebench.resolve_test_ids(
        ["test_bar"],
        ["tests/test_foo.py"],
        tmp_path,
    )
    assert result == ["tests/test_foo.py::test_bar"]


def test_resolve_test_ids_already_node_id() -> None:
    """Node IDs with :: pass through unchanged."""
    result = verify_swebench.resolve_test_ids(
        ["tests/test_foo.py::TestClass::test_method"],
        [],
        Path("/fake"),
    )
    assert result == ["tests/test_foo.py::TestClass::test_method"]


def test_resolve_test_ids_dotted_path_resolved(tmp_path: Path) -> None:
    """Dotted module paths are converted to file::node format."""
    test_file = tmp_path / "tests" / "test_foo.py"
    test_file.parent.mkdir(parents=True)
    test_file.write_text("class TestBar:\n    def test_baz(self): pass\n")

    result = verify_swebench.resolve_test_ids(
        ["tests.test_foo.TestBar.test_baz"],
        [],
        tmp_path,
    )
    assert result == ["tests/test_foo.py::TestBar::test_baz"]


def test_resolve_test_ids_unittest_style_label_normalized() -> None:
    result = verify_swebench.resolve_test_ids(
        ["test_baz (tests.test_foo.TestBar)"],
        [],
        Path("/fake"),
    )
    assert result == ["tests.test_foo.TestBar.test_baz"]


def test_resolve_test_ids_descriptive_label_maps_to_enclosing_test(
    tmp_path: Path,
) -> None:
    test_file = tmp_path / "tests" / "test_foo.py"
    test_file.parent.mkdir(parents=True)
    test_file.write_text(
        "class TestBar:\n"
        "    def test_baz(self):\n"
        "        \"\"\"\n"
        "        Human readable scenario label\n"
        "        \"\"\"\n"
        "        pass\n"
    )

    result = verify_swebench.resolve_test_ids(
        ["Human readable scenario label"],
        ["tests/test_foo.py"],
        tmp_path,
    )
    assert result == ["tests.test_foo.TestBar.test_baz"]


def test_resolve_test_ids_descriptive_label_falls_back_to_repo_test_scan(
    tmp_path: Path,
) -> None:
    patched_test = tmp_path / "tests" / "test_patched.py"
    patched_test.parent.mkdir(parents=True)
    patched_test.write_text("def test_patched():\n    pass\n")

    unpatched_test = tmp_path / "tests" / "sessions_tests.py"
    unpatched_test.write_text(
        "class SessionTests:\n"
        "    def test_cookie_expiry(self):\n"
        "        \"\"\"\n"
        "        Human readable scenario label\n"
        "        \"\"\"\n"
        "        pass\n"
    )

    result = verify_swebench.resolve_test_ids(
        ["Human readable scenario label"],
        ["tests/test_patched.py"],
        tmp_path,
    )
    assert result == ["tests.sessions_tests.SessionTests.test_cookie_expiry"]


def test_resolve_test_ids_bare_name_unmatched() -> None:
    """Bare names with no matching file fall through as-is (for -k matching)."""
    result = verify_swebench.resolve_test_ids(
        ["test_something"],
        [],
        Path("/fake"),
    )
    assert result == ["test_something"]
