"""Unit tests for verify_swebench.py pure logic (no repo cloning)."""

from __future__ import annotations

import json
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


def test_resolve_test_ids_bare_name_unmatched() -> None:
    """Bare names with no matching file fall through as-is (for -k matching)."""
    result = verify_swebench.resolve_test_ids(
        ["test_something"],
        [],
        Path("/fake"),
    )
    assert result == ["test_something"]
