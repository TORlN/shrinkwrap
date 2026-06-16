"""
Tests for gaps that block shipping.
All RED until implemented.
"""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from shrinkwrap.cli import cli

ANNOTATED_SOURCE = """\
<!-- shrinkwrap: mutable compression=condense -->
## Sprint Notes
- item one
- item two
- item one

## Current Status
- ok
"""

# ---------------------------------------------------------------------------
# --version flag
# ---------------------------------------------------------------------------


class TestVersionFlag:
    def test_version_flag_exits_zero(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["--version"])
        assert result.exit_code == 0

    def test_version_flag_prints_version_number(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["--version"])
        assert "0.3.2" in result.output


# ---------------------------------------------------------------------------
# --level flag must not override per-section annotations when unset
# ---------------------------------------------------------------------------


class TestLevelFlagAnnotationRespect:
    def test_no_level_flag_preserves_condense_annotation(self, tmp_path: Path) -> None:
        """Running compress with no --level must not override compression=condense."""
        runner = CliRunner()
        src = tmp_path / "CLAUDE.md"
        src.write_text(ANNOTATED_SOURCE)

        result = runner.invoke(cli, ["compress", str(src)])
        assert result.exit_code == 0

        out = src.with_suffix(".sw.md").read_text()
        # The annotated section must still use condense, not the default normalize
        assert 'compression="condense"' in out

    def test_explicit_level_flag_overrides_annotation(self, tmp_path: Path) -> None:
        """Passing --level normalize explicitly SHOULD override all sections."""
        runner = CliRunner()
        src = tmp_path / "CLAUDE.md"
        src.write_text(ANNOTATED_SOURCE)

        result = runner.invoke(cli, ["compress", str(src), "--level", "normalize"])
        assert result.exit_code == 0

        out = src.with_suffix(".sw.md").read_text()
        assert 'compression="normalize"' in out

    def test_explicit_condense_level_applies_to_unannotated_sections(self, tmp_path: Path) -> None:
        """--level condense should apply to sections without explicit annotations."""
        runner = CliRunner()
        src = tmp_path / "CLAUDE.md"
        src.write_text("## Current Status\n- ok\n")

        runner.invoke(cli, ["compress", str(src), "--level", "condense"])
        out = src.with_suffix(".sw.md").read_text()
        assert 'compression="condense"' in out


# ---------------------------------------------------------------------------
# --dry-run flag
# ---------------------------------------------------------------------------


class TestDryRun:
    def test_dry_run_exits_zero(self, tmp_path: Path) -> None:
        runner = CliRunner()
        src = tmp_path / "CLAUDE.md"
        src.write_text("## Status\n- ok\n")

        result = runner.invoke(cli, ["compress", str(src), "--dry-run"])
        assert result.exit_code == 0

    def test_dry_run_does_not_write_file(self, tmp_path: Path) -> None:
        runner = CliRunner()
        src = tmp_path / "CLAUDE.md"
        src.write_text("## Status\n- ok\n")

        runner.invoke(cli, ["compress", str(src), "--dry-run"])
        assert not src.with_suffix(".sw.md").exists()

    def test_dry_run_prints_output_to_stdout(self, tmp_path: Path) -> None:
        runner = CliRunner()
        src = tmp_path / "CLAUDE.md"
        src.write_text("## Status\n- ok\n")

        result = runner.invoke(cli, ["compress", str(src), "--dry-run"])
        assert "shrinkwrap_schema" in result.output or "Status" in result.output

    def test_dry_run_shows_section_count_or_ratio(self, tmp_path: Path) -> None:
        runner = CliRunner()
        src = tmp_path / "CLAUDE.md"
        src.write_text("## Section One\ncontent\n## Section Two\ncontent\n")

        result = runner.invoke(cli, ["compress", str(src), "--dry-run"])
        # Should mention something about the file (ratio, token count, or sections)
        assert any(
            word in result.output.lower() for word in ("ratio", "token", "section", "%", "compress")
        )


# ---------------------------------------------------------------------------
# stats command
# ---------------------------------------------------------------------------


class TestStatsCommand:
    def test_stats_exits_zero(self, tmp_path: Path) -> None:
        runner = CliRunner()
        src = tmp_path / "CLAUDE.md"
        src.write_text("## Security Rules\nNever.\n## Status\n- ok\n")

        result = runner.invoke(cli, ["stats", str(src)])
        assert result.exit_code == 0

    def test_stats_lists_all_sections(self, tmp_path: Path) -> None:
        runner = CliRunner()
        src = tmp_path / "CLAUDE.md"
        src.write_text("## Security Rules\nNever.\n## Status\n- ok\n")

        result = runner.invoke(cli, ["stats", str(src)])
        assert "Security Rules" in result.output
        assert "Status" in result.output

    def test_stats_shows_classification(self, tmp_path: Path) -> None:
        runner = CliRunner()
        src = tmp_path / "CLAUDE.md"
        src.write_text("## Security Rules\nNever.\n## Status\n- ok\n")

        result = runner.invoke(cli, ["stats", str(src)])
        assert "immutable" in result.output
        assert "mutable" in result.output

    def test_stats_shows_token_estimates(self, tmp_path: Path) -> None:
        runner = CliRunner()
        src = tmp_path / "CLAUDE.md"
        src.write_text("## Status\n" + "content line\n" * 20)

        result = runner.invoke(cli, ["stats", str(src)])
        # Should show some numeric token estimate
        import re

        assert re.search(r"\d+", result.output)

    def test_stats_shows_total_line(self, tmp_path: Path) -> None:
        runner = CliRunner()
        src = tmp_path / "CLAUDE.md"
        src.write_text("## Alpha\ncontent\n## Beta\ncontent\n")

        result = runner.invoke(cli, ["stats", str(src)])
        assert "total" in result.output.lower() or "2" in result.output


# ---------------------------------------------------------------------------
# tiktoken not imported (dead dependency removed)
# ---------------------------------------------------------------------------


class TestNoTiktoken:
    def test_shrinkwrap_modules_do_not_import_tiktoken(self) -> None:
        import sys

        # Save existing shrinkwrap module objects so subsequent tests that hold
        # direct references (e.g. `from shrinkwrap.drift import score_commit`) are
        # not broken when we clear and reimport the package.
        saved = {k: v for k, v in sys.modules.items() if "shrinkwrap" in k}

        sys.modules.pop("tiktoken", None)
        for mod_name in list(sys.modules.keys()):
            if "shrinkwrap" in mod_name:
                sys.modules.pop(mod_name, None)

        try:
            import shrinkwrap  # noqa: F401

            assert "tiktoken" not in sys.modules, (
                "tiktoken was imported by a shrinkwrap module but it is declared as removed"
            )
        finally:
            # Restore the original module objects so monkeypatch can patch them.
            for mod_name in list(sys.modules.keys()):
                if "shrinkwrap" in mod_name:
                    sys.modules.pop(mod_name, None)
            sys.modules.update(saved)
