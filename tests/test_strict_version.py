"""Tests for verify --strict source-hash checking, watched_paths drift filtering, and CLI version metadata."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from shrinkwrap.cli import cli
from shrinkwrap.drift import DriftResult, score_commit


# ---------------------------------------------------------------------------
# B1 — --strict must actually check source-file hash
# ---------------------------------------------------------------------------

class TestStrictVerifyChecksSourceHash:
    def _compress(self, runner: CliRunner, src: Path) -> Path:
        runner.invoke(cli, ["compress", str(src)])
        return src.with_suffix(".sw.md")

    def test_strict_passes_when_source_unchanged(self, tmp_path: Path) -> None:
        runner = CliRunner()
        src = tmp_path / "CLAUDE.md"
        src.write_text(
            "<!-- shrinkwrap: immutable -->\n## Rules\nNever.\n## Status\n- ok\n"
        )
        vtbf = self._compress(runner, src)
        result = runner.invoke(cli, ["verify", str(vtbf), "--strict"])
        assert result.exit_code == 0

    def test_strict_fails_when_source_changed_after_compress(
        self, tmp_path: Path
    ) -> None:
        runner = CliRunner()
        src = tmp_path / "CLAUDE.md"
        src.write_text("## Status\n- original content\n")
        vtbf = self._compress(runner, src)
        src.write_text("## Status\n- completely different content\n")
        result = runner.invoke(cli, ["verify", str(vtbf), "--strict"])
        assert result.exit_code != 0

    def test_strict_error_mentions_source_change(self, tmp_path: Path) -> None:
        runner = CliRunner()
        src = tmp_path / "CLAUDE.md"
        src.write_text("## Status\n- original\n")
        vtbf = self._compress(runner, src)
        src.write_text("## Status\n- changed\n")
        result = runner.invoke(cli, ["verify", str(vtbf), "--strict"])
        out = result.output.lower()
        assert "source" in out or "changed" in out or "hash" in out or "sha" in out

    def test_strict_warns_and_skips_when_source_not_found(
        self, tmp_path: Path
    ) -> None:
        runner = CliRunner()
        src = tmp_path / "CLAUDE.md"
        src.write_text("## Status\n- ok\n")
        vtbf = self._compress(runner, src)
        src.unlink()
        result = runner.invoke(cli, ["verify", str(vtbf), "--strict"])
        # Must warn about missing source, but must not crash
        assert result.exit_code == 0
        out = result.output.lower()
        assert "warning" in out or "not found" in out or "missing" in out

    def test_non_strict_ignores_source_change(self, tmp_path: Path) -> None:
        runner = CliRunner()
        src = tmp_path / "CLAUDE.md"
        src.write_text("## Status\n- original\n")
        vtbf = self._compress(runner, src)
        src.write_text("## Status\n- completely different\n")
        result = runner.invoke(cli, ["verify", str(vtbf)])
        assert result.exit_code == 0

    def test_strict_json_mode_reports_error_in_json(self, tmp_path: Path) -> None:
        import json as _json
        runner = CliRunner()
        src = tmp_path / "CLAUDE.md"
        src.write_text("## Status\n- original\n")
        vtbf = self._compress(runner, src)
        src.write_text("## Status\n- changed\n")
        result = runner.invoke(cli, ["verify", str(vtbf), "--strict", "--json"])
        parsed = _json.loads(result.output)
        assert parsed["valid"] is False
        assert len(parsed["errors"]) > 0


# ---------------------------------------------------------------------------
# B2 — watched_paths must be applied when scoring drift
# ---------------------------------------------------------------------------

class TestWatchedPathsFiltersScoreCommit:
    def test_score_commit_accepts_watched_paths_kwarg(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """score_commit must accept a watched_paths parameter without TypeError."""
        def mock_git_run(args: list[str], cwd: Path) -> str:
            if "--name-only" in args:
                return "src/main.py\n"
            return ""

        monkeypatch.setattr("shrinkwrap.drift._git_run", mock_git_run)
        result = score_commit(tmp_path, watched_paths=["src/"])
        assert isinstance(result, DriftResult)

    def test_files_outside_watched_paths_not_analyzed(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Files whose paths do not start with any watched path must be excluded."""
        def mock_git_run(args: list[str], cwd: Path) -> str:
            if "--name-only" in args:
                return "outside/module.py\nother/utils.py\n"
            return ""

        monkeypatch.setattr("shrinkwrap.drift._git_run", mock_git_run)
        result = score_commit(tmp_path, watched_paths=["src/"])
        # No files inside src/ → no Python symbol analysis
        assert result.changed_public_symbols == []

    def test_files_inside_watched_paths_are_analyzed(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Files whose paths start with a watched path must be processed."""
        fetched: list[str] = []

        def mock_git_run(args: list[str], cwd: Path) -> str:
            if "--name-only" in args:
                return "src/module.py\n"
            if "show" in args:
                fetched.append(str(args))
                return "def old_func(): pass\n"
            return ""

        monkeypatch.setattr("shrinkwrap.drift._git_run", mock_git_run)
        score_commit(tmp_path, watched_paths=["src/"])
        assert len(fetched) > 0

    def test_empty_watched_paths_processes_all_files(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """watched_paths=[] must not filter anything — all files are processed."""
        fetched: list[str] = []

        def mock_git_run(args: list[str], cwd: Path) -> str:
            if "--name-only" in args:
                return "src/foo.py\nlib/bar.py\n"
            if "show" in args:
                fetched.append(str(args))
                return "def func(): pass\n"
            return ""

        monkeypatch.setattr("shrinkwrap.drift._git_run", mock_git_run)
        score_commit(tmp_path, watched_paths=[])
        assert len(fetched) > 0

    def test_drift_check_cli_passes_watched_paths_from_config(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """drift-check must pass cfg.watched_paths to score_commit."""
        (tmp_path / "shrinkwrap.toml").write_text(
            '[shrinkwrap]\nwatched_paths = ["src/"]\n'
        )
        received: dict[str, object] = {}

        def capture(
            repo_root: Path,
            commit_sha: str = "HEAD",
            watched_paths: list[str] | None = None,
        ) -> DriftResult:
            received["watched_paths"] = watched_paths
            return DriftResult(score=0.0, changed_public_symbols=[], structure_changes=[])

        monkeypatch.setattr("shrinkwrap.drift.score_commit", capture)
        CliRunner().invoke(cli, ["drift-check", "--repo", str(tmp_path)])
        assert received.get("watched_paths") == ["src/"]


# ---------------------------------------------------------------------------
# B3 — CLI --version must come from package metadata, not a hardcoded string
# ---------------------------------------------------------------------------

class TestVersionFromPackageMetadata:
    def test_version_flag_shows_package_version(self) -> None:
        """--version output must match importlib.metadata, not a stale literal."""
        from importlib.metadata import PackageNotFoundError
        from importlib.metadata import version as pkg_version

        try:
            expected = pkg_version("shrinkwrap")
        except PackageNotFoundError:
            pytest.skip("shrinkwrap package not installed")

        result = CliRunner().invoke(cli, ["--version"])
        assert result.exit_code == 0
        assert expected in result.output
