"""Tests for drift.py — all should be RED until implemented."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from shrinkwrap.drift import (
    DriftResult,
    compute_symbol_drift,
    extract_public_symbols,
    score_commit,
)

# ---------------------------------------------------------------------------
# extract_public_symbols
# ---------------------------------------------------------------------------


class TestExtractPublicSymbols:
    def test_top_level_function(self) -> None:
        source = "def my_function():\n    pass\n"
        assert "my_function" in extract_public_symbols(source)

    def test_top_level_class(self) -> None:
        source = "class MyClass:\n    pass\n"
        assert "MyClass" in extract_public_symbols(source)

    def test_private_function_excluded(self) -> None:
        source = "def _private():\n    pass\ndef public():\n    pass\n"
        symbols = extract_public_symbols(source)
        assert "_private" not in symbols
        assert "public" in symbols

    def test_dunder_excluded(self) -> None:
        source = "def __init__(self):\n    pass\n"
        assert "__init__" not in extract_public_symbols(source)

    def test_nested_function_excluded(self) -> None:
        source = "def outer():\n    def inner():\n        pass\n"
        symbols = extract_public_symbols(source)
        assert "outer" in symbols
        assert "inner" not in symbols

    def test_async_function_included(self) -> None:
        source = "async def fetch_data():\n    pass\n"
        assert "fetch_data" in extract_public_symbols(source)

    def test_empty_source_returns_empty(self) -> None:
        assert extract_public_symbols("") == set()

    def test_syntax_error_returns_empty(self) -> None:
        assert extract_public_symbols("def broken(:\n    pass\n") == set()

    def test_multiple_symbols(self) -> None:
        source = "def alpha(): pass\ndef beta(): pass\nclass Gamma: pass\n"
        symbols = extract_public_symbols(source)
        assert symbols == {"alpha", "beta", "Gamma"}


# ---------------------------------------------------------------------------
# compute_symbol_drift
# ---------------------------------------------------------------------------


class TestComputeSymbolDrift:
    def test_new_function_is_added(self) -> None:
        before = "def alpha(): pass\n"
        after = "def alpha(): pass\ndef beta(): pass\n"
        added, removed, renamed = compute_symbol_drift(before, after)
        assert "beta" in added
        assert removed == []

    def test_removed_function_detected(self) -> None:
        before = "def alpha(): pass\ndef beta(): pass\n"
        after = "def alpha(): pass\n"
        added, removed, renamed = compute_symbol_drift(before, after)
        assert "beta" in removed
        assert added == []

    def test_no_change_returns_empty(self) -> None:
        source = "def alpha(): pass\n"
        added, removed, renamed = compute_symbol_drift(source, source)
        assert added == []
        assert removed == []
        assert renamed == []

    def test_implementation_only_change_no_drift(self) -> None:
        before = "def alpha():\n    return 1\n"
        after = "def alpha():\n    return 2\n"
        added, removed, renamed = compute_symbol_drift(before, after)
        assert added == []
        assert removed == []
        assert renamed == []

    def test_class_added(self) -> None:
        before = "def alpha(): pass\n"
        after = "def alpha(): pass\nclass NewService: pass\n"
        added, removed, _ = compute_symbol_drift(before, after)
        assert "NewService" in added

    def test_both_added_and_removed(self) -> None:
        before = "def old_func(): pass\n"
        after = "def new_func(): pass\n"
        added, removed, _ = compute_symbol_drift(before, after)
        assert "new_func" in added
        assert "old_func" in removed


# ---------------------------------------------------------------------------
# DriftResult
# ---------------------------------------------------------------------------


class TestDriftResult:
    def test_threshold_exceeded_above_0_35(self) -> None:
        result = DriftResult(score=0.5, changed_public_symbols=[], structure_changes=[])
        assert result.threshold_exceeded is True

    def test_threshold_not_exceeded_below_0_35(self) -> None:
        result = DriftResult(score=0.2, changed_public_symbols=[], structure_changes=[])
        assert result.threshold_exceeded is False

    def test_threshold_exactly_at_boundary(self) -> None:
        result = DriftResult(score=0.35, changed_public_symbols=[], structure_changes=[])
        assert result.threshold_exceeded is True


# ---------------------------------------------------------------------------
# Step 1 — non-Python file skip & SyntaxError warning (RED until implemented)
# ---------------------------------------------------------------------------


def _make_git_repo(root: Path) -> None:
    """Initialize a minimal git repo suitable for score_commit tests."""
    subprocess.run(["git", "init", "--initial-branch=main"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True, capture_output=True)


class TestScoreCommitNonPythonSkip:
    """score_commit must never pass non-Python content to the AST engine."""

    def test_markdown_only_diff_no_python_symbols(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        def mock_run(args: list[str], cwd: Path) -> str:
            joined = " ".join(args)
            if "--name-only" in joined:
                return "README.md\nCHANGELOG.md\n"
            return "\n"

        monkeypatch.setattr("shrinkwrap.drift._git_run", mock_run)
        monkeypatch.setattr("shrinkwrap.drift._git_file_at", lambda *a: "")
        result = score_commit(tmp_path, "HEAD")
        assert result.changed_public_symbols == []

    def test_json_and_css_diff_no_python_symbols(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        def mock_run(args: list[str], cwd: Path) -> str:
            if "--name-only" in " ".join(args):
                return "package.json\nstyle.css\nconfig.yaml\n"
            return "\n"

        monkeypatch.setattr("shrinkwrap.drift._git_run", mock_run)
        monkeypatch.setattr("shrinkwrap.drift._git_file_at", lambda *a: "")
        result = score_commit(tmp_path, "HEAD")
        assert result.changed_public_symbols == []

    def test_typescript_diff_no_python_symbols(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """TypeScript IS in _SOURCE_EXTS but must never hit ast.parse."""
        def mock_run(args: list[str], cwd: Path) -> str:
            if "--name-only" in " ".join(args):
                return "src/app.ts\nlib/utils.js\n"
            return "\n"

        monkeypatch.setattr("shrinkwrap.drift._git_run", mock_run)
        monkeypatch.setattr("shrinkwrap.drift._git_file_at", lambda *a: "export function hello(): void {}")
        result = score_commit(tmp_path, "HEAD")
        assert result.changed_public_symbols == []

    def test_mixed_language_diff_only_py_symbols_detected(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        def mock_run(args: list[str], cwd: Path) -> str:
            if "--name-only" in " ".join(args):
                return "README.md\napp.ts\nsrc/module.py\n"
            return "\n"

        def mock_file_at(commit: str, path: str, cwd: Path) -> str:
            if path.endswith(".py"):
                return "" if "~1" in commit else "def new_symbol(): pass\n"
            return "export function tsFunc(): void {}"

        monkeypatch.setattr("shrinkwrap.drift._git_run", mock_run)
        monkeypatch.setattr("shrinkwrap.drift._git_file_at", mock_file_at)
        # Index returns the same "after" content as the commit tree for .py; "" for others.
        monkeypatch.setattr(
            "shrinkwrap.drift._git_index_file",
            lambda path, cwd: "def new_symbol(): pass\n" if path.endswith(".py") else "",
        )
        result = score_commit(tmp_path, "HEAD")
        assert "new_symbol" in result.changed_public_symbols
        assert "tsFunc" not in result.changed_public_symbols


class TestScoreCommitSyntaxErrorWarning:
    """score_commit must log a warning and continue when a .py file has a syntax error."""

    def test_syntax_error_in_after_state_logs_warning(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        def mock_run(args: list[str], cwd: Path) -> str:
            if "--name-only" in " ".join(args):
                return "broken.py\n"
            return "\n"

        def mock_file_at(commit: str, path: str, cwd: Path) -> str:
            if "~1" in commit:
                return "def valid(): pass\n"
            return "def broken(:\n    pass\n"  # syntax error

        monkeypatch.setattr("shrinkwrap.drift._git_run", mock_run)
        monkeypatch.setattr("shrinkwrap.drift._git_file_at", mock_file_at)
        # Index (after state) returns the broken version.
        monkeypatch.setattr(
            "shrinkwrap.drift._git_index_file",
            lambda path, cwd: "def broken(:\n    pass\n",
        )

        score_commit(tmp_path, "HEAD")

        captured = capsys.readouterr()
        assert "broken.py" in captured.err
        assert any(word in captured.err.lower() for word in ("syntax", "warning", "skip"))

    def test_syntax_error_does_not_crash_score_commit(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """score_commit must return a valid DriftResult even if a .py file is malformed."""
        def mock_run(args: list[str], cwd: Path) -> str:
            if "--name-only" in " ".join(args):
                return "bad.py\n"
            return "\n"

        monkeypatch.setattr("shrinkwrap.drift._git_run", mock_run)
        monkeypatch.setattr("shrinkwrap.drift._git_file_at", lambda *a: "def (\n")
        result = score_commit(tmp_path, "HEAD")
        assert isinstance(result, DriftResult)
        assert result.score >= 0.0

    def test_syntax_error_in_one_file_does_not_skip_other_files(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """After a syntax error in broken.py, good.py must still be analyzed."""
        def mock_run(args: list[str], cwd: Path) -> str:
            if "--name-only" in " ".join(args):
                return "broken.py\ngood.py\n"
            return "\n"

        def mock_file_at(commit: str, path: str, cwd: Path) -> str:
            if "broken" in path:
                return "def broken(:\n    pass\n"
            return "" if "~1" in commit else "def new_func(): pass\n"

        def mock_index_file(path: str, cwd: Path) -> str:
            if "broken" in path:
                return "def broken(:\n    pass\n"
            return "def new_func(): pass\n"

        monkeypatch.setattr("shrinkwrap.drift._git_run", mock_run)
        monkeypatch.setattr("shrinkwrap.drift._git_file_at", mock_file_at)
        monkeypatch.setattr("shrinkwrap.drift._git_index_file", mock_index_file)

        result = score_commit(tmp_path, "HEAD")
        assert "new_func" in result.changed_public_symbols


class TestScoreCommitGitIndexIsolation:
    """score_commit must read the 'after' state from the git index (:0:), not the commit tree."""

    def test_after_state_read_from_git_index_not_commit_tree(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """FAILS currently: score_commit uses 'HEAD:path' not ':0:path' for the after state."""
        git_show_calls: list[str] = []

        def mock_run(args: list[str], cwd: Path) -> str:
            joined = " ".join(args)
            if "show" in args:
                git_show_calls.append(joined)
            if "--name-only" in joined:
                return "mod.py\n"
            return "\n"

        monkeypatch.setattr("shrinkwrap.drift._git_run", mock_run)
        score_commit(tmp_path, "HEAD")

        # The "after" read for the staged version must use the index (:0:) syntax.
        show_calls_for_file = [c for c in git_show_calls if "mod.py" in c]
        assert any(":0:" in call for call in show_calls_for_file), (
            f"Expected a 'git show :0:mod.py' call for index isolation; "
            f"got calls: {show_calls_for_file}"
        )


class TestScoreCommitDirtyWorkingTree:
    """score_commit must read from git, not the dirty working tree on disk."""

    def test_dirty_disk_does_not_affect_symbol_analysis(self, tmp_path: Path) -> None:
        """Integration test: create a real git repo, dirty the disk, verify git state is used."""
        _make_git_repo(tmp_path)

        py_file = tmp_path / "mod.py"

        # First commit: baseline
        py_file.write_text("def func_a(): pass\n")
        subprocess.run(["git", "add", "mod.py"], cwd=tmp_path, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "v1"], cwd=tmp_path, check=True, capture_output=True)

        # Second commit: adds func_b
        py_file.write_text("def func_a(): pass\ndef func_b(): pass\n")
        subprocess.run(["git", "add", "mod.py"], cwd=tmp_path, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "v2"], cwd=tmp_path, check=True, capture_output=True)

        # Dirty the disk with a completely different (syntax-broken) version
        py_file.write_text("def broken(:\n    pass\n")

        result = score_commit(tmp_path, "HEAD")

        # func_b comes from git (v2 vs v1); disk content is irrelevant
        assert "func_b" in result.changed_public_symbols
        # Disk's broken version must NOT have been used (no crash, no missing symbols)
        assert isinstance(result, DriftResult)
