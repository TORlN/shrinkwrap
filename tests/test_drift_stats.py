"""Tests for drift-check error visibility and the stats --json machine-readable output flag."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from shrinkwrap.cli import cli

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

STATS_SOURCE = (
    "## Section A\n"
    + "- shared bullet\n" * 5
    + "- unique to A\n"
    + "## Section B\n"
    + "- shared bullet\n" * 5
    + "- unique to B\n"
)


# ---------------------------------------------------------------------------
# 2 — drift-check must warn when score_commit raises, not just swallow it
# ---------------------------------------------------------------------------


class TestDriftCheckErrorVisibility:
    def test_drift_check_warns_when_score_commit_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If score_commit raises an exception (not a timeout), a warning must be printed."""

        def boom(
            repo_root: Path, commit_sha: str = "HEAD", watched_paths: list[str] | None = None
        ) -> None:
            raise RuntimeError("git: not a git repository")

        monkeypatch.setattr("shrinkwrap.drift.score_commit", boom)
        result = CliRunner().invoke(cli, ["drift-check", "--repo", str(tmp_path)])
        output_lower = result.output.lower()
        assert (
            "warning" in output_lower
            or "error" in output_lower
            or "failed" in output_lower
            or "could not" in output_lower
        )

    def test_drift_check_exits_zero_even_when_score_commit_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An error in drift scoring must not block the developer's workflow."""

        def boom(
            repo_root: Path, commit_sha: str = "HEAD", watched_paths: list[str] | None = None
        ) -> None:
            raise RuntimeError("fatal: not a git repository")

        monkeypatch.setattr("shrinkwrap.drift.score_commit", boom)
        result = CliRunner().invoke(cli, ["drift-check", "--repo", str(tmp_path)])
        assert result.exit_code == 0

    def test_drift_check_error_message_includes_exception_info(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The warning must include enough context to diagnose the problem."""

        def boom(
            repo_root: Path, commit_sha: str = "HEAD", watched_paths: list[str] | None = None
        ) -> None:
            raise RuntimeError("git: not a git repository")

        monkeypatch.setattr("shrinkwrap.drift.score_commit", boom)
        result = CliRunner().invoke(cli, ["drift-check", "--repo", str(tmp_path)])
        # Should mention "drift" or "scoring" so the user knows what failed
        assert (
            "drift" in result.output.lower()
            or "scoring" in result.output.lower()
            or "git" in result.output.lower()
        )

    def test_drift_check_normal_below_threshold_still_silent(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When score_commit succeeds with a low score, output must remain silent."""
        from shrinkwrap.drift import DriftResult

        def low_score(
            repo_root: Path, commit_sha: str = "HEAD", watched_paths: list[str] | None = None
        ) -> DriftResult:
            return DriftResult(score=0.1, changed_public_symbols=[], structure_changes=[])

        monkeypatch.setattr("shrinkwrap.drift.score_commit", low_score)
        result = CliRunner().invoke(cli, ["drift-check", "--repo", str(tmp_path)])
        assert result.exit_code == 0
        assert "drift" not in result.output.lower()

    def test_drift_check_hook_mode_also_warns_on_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """--hook-mode must also emit the warning so post-commit logs capture it."""

        def boom(
            repo_root: Path, commit_sha: str = "HEAD", watched_paths: list[str] | None = None
        ) -> None:
            raise RuntimeError("permission denied")

        monkeypatch.setattr("shrinkwrap.drift.score_commit", boom)
        result = CliRunner().invoke(cli, ["drift-check", "--repo", str(tmp_path), "--hook-mode"])
        assert result.exit_code == 0
        output_lower = result.output.lower()
        assert (
            "warning" in output_lower
            or "error" in output_lower
            or "failed" in output_lower
            or "could not" in output_lower
        )


# ---------------------------------------------------------------------------
# 4 — stats --json outputs machine-readable token counts
# ---------------------------------------------------------------------------


class TestStatsJsonFlag:
    def test_stats_json_exits_zero(self, tmp_path: Path) -> None:
        src = tmp_path / "CLAUDE.md"
        src.write_text(STATS_SOURCE)
        result = CliRunner().invoke(cli, ["stats", str(src), "--json"])
        assert result.exit_code == 0

    def test_stats_json_outputs_valid_json(self, tmp_path: Path) -> None:
        src = tmp_path / "CLAUDE.md"
        src.write_text(STATS_SOURCE)
        result = CliRunner().invoke(cli, ["stats", str(src), "--json"])
        parsed = json.loads(result.output)
        assert isinstance(parsed, dict)

    def test_stats_json_has_sections_list(self, tmp_path: Path) -> None:
        src = tmp_path / "CLAUDE.md"
        src.write_text(STATS_SOURCE)
        result = CliRunner().invoke(cli, ["stats", str(src), "--json"])
        parsed = json.loads(result.output)
        assert "sections" in parsed
        assert isinstance(parsed["sections"], list)

    def test_stats_json_sections_have_expected_fields(self, tmp_path: Path) -> None:
        src = tmp_path / "CLAUDE.md"
        src.write_text(STATS_SOURCE)
        result = CliRunner().invoke(cli, ["stats", str(src), "--json"])
        parsed = json.loads(result.output)
        section = parsed["sections"][0]
        assert "heading" in section
        assert "classification" in section
        assert "tokens" in section

    def test_stats_json_has_total_tokens(self, tmp_path: Path) -> None:
        src = tmp_path / "CLAUDE.md"
        src.write_text(STATS_SOURCE)
        result = CliRunner().invoke(cli, ["stats", str(src), "--json"])
        parsed = json.loads(result.output)
        assert "total_tokens" in parsed
        assert isinstance(parsed["total_tokens"], int)
        assert parsed["total_tokens"] > 0

    def test_stats_json_has_projections(self, tmp_path: Path) -> None:
        src = tmp_path / "CLAUDE.md"
        src.write_text(STATS_SOURCE)
        result = CliRunner().invoke(cli, ["stats", str(src), "--json"])
        parsed = json.loads(result.output)
        assert "projections" in parsed
        assert "normalize" in parsed["projections"]
        assert "condense" in parsed["projections"]

    def test_stats_json_projection_values_are_ints(self, tmp_path: Path) -> None:
        src = tmp_path / "CLAUDE.md"
        src.write_text(STATS_SOURCE)
        result = CliRunner().invoke(cli, ["stats", str(src), "--json"])
        parsed = json.loads(result.output)
        assert isinstance(parsed["projections"]["normalize"], int)
        assert isinstance(parsed["projections"]["condense"], int)

    def test_stats_json_section_count_matches_source(self, tmp_path: Path) -> None:
        src = tmp_path / "CLAUDE.md"
        src.write_text(STATS_SOURCE)
        result = CliRunner().invoke(cli, ["stats", str(src), "--json"])
        parsed = json.loads(result.output)
        assert len(parsed["sections"]) == 2

    def test_stats_without_json_still_shows_table(self, tmp_path: Path) -> None:
        src = tmp_path / "CLAUDE.md"
        src.write_text(STATS_SOURCE)
        result = CliRunner().invoke(cli, ["stats", str(src)])
        assert result.exit_code == 0
        assert "Section" in result.output or "section" in result.output.lower()

    def test_stats_json_output_has_no_rich_markup(self, tmp_path: Path) -> None:
        src = tmp_path / "CLAUDE.md"
        src.write_text(STATS_SOURCE)
        result = CliRunner().invoke(cli, ["stats", str(src), "--json"])
        assert "[green]" not in result.output
        assert "[bold]" not in result.output

    def test_stats_json_auto_discovery_works(self, tmp_path: Path) -> None:
        """--json must work with auto-discovered CLAUDE.md too."""
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            Path("CLAUDE.md").write_text(STATS_SOURCE)
            result = runner.invoke(cli, ["stats", "--json"])
            assert result.exit_code == 0
            parsed = json.loads(result.output)
            assert parsed["total_tokens"] > 0
