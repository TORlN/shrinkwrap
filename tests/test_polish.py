"""
TDD tests for four polish items:

  5  watch --profile ignores shrinkwrap.toml default_profile
  6  size warning suggests --profile generic even when that profile is already active
  7  stats command shows no projection — users can't decide on a level without estimates
  8  compress/stats with no argument don't discover CLAUDE.md in cwd
"""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from shrinkwrap.cli import cli

# ---------------------------------------------------------------------------
# 5 — watch respects default_profile from shrinkwrap.toml
# ---------------------------------------------------------------------------

class TestWatchRespectsConfigProfile:
    def test_watch_uses_generic_profile_from_config(self, tmp_path: Path) -> None:
        """watch must apply default_profile = generic from shrinkwrap.toml."""
        import threading
        import time

        from shrinkwrap.cli import _watch_loop

        (tmp_path / "shrinkwrap.toml").write_text(
            '[shrinkwrap]\ndefault_profile = "generic"\n'
        )
        src = tmp_path / "CLAUDE.md"
        src.write_text("## Status\n- ok\n")

        stop = threading.Event()
        t = threading.Thread(
            target=_watch_loop,
            args=(src, None, None, False, 0.05),  # profile=None → use config
            kwargs={"stop_event": stop},
            daemon=True,
        )
        t.start()
        time.sleep(0.15)
        src.write_text("## Status\n- updated\n")
        time.sleep(0.35)
        stop.set()
        t.join(timeout=2.0)

        content = src.read_text()
        # generic profile strips all tags and front-matter
        assert "shrinkwrap_schema" not in content
        assert "sw:section" not in content
        assert "## Status" in content

    def test_watch_explicit_profile_overrides_config(self, tmp_path: Path) -> None:
        """An explicit --profile on the CLI must override default_profile in config."""
        import threading
        import time

        from shrinkwrap.cli import _watch_loop

        (tmp_path / "shrinkwrap.toml").write_text(
            '[shrinkwrap]\ndefault_profile = "generic"\n'
        )
        src = tmp_path / "CLAUDE.md"
        src.write_text("## Status\n- ok\n")

        stop = threading.Event()
        t = threading.Thread(
            target=_watch_loop,
            args=(src, None, "claude", False, 0.05),  # explicit claude overrides config
            kwargs={"stop_event": stop},
            daemon=True,
        )
        t.start()
        time.sleep(0.15)
        src.write_text("## Status\n- updated\n")
        time.sleep(0.35)
        stop.set()
        t.join(timeout=2.0)

        content = src.read_text()
        # claude profile keeps full VTBF
        assert "shrinkwrap_schema" in content


# ---------------------------------------------------------------------------
# 6 — size warning must not suggest --profile generic when already using it
# ---------------------------------------------------------------------------

class TestSizeWarningSuggestion:
    def test_generic_profile_does_not_trigger_size_warning(
        self, tmp_path: Path
    ) -> None:
        """--profile generic strips all tags; no overhead warning should fire."""
        src = tmp_path / "CLAUDE.md"
        src.write_text("## A\n- x\n")  # tiny file
        result = CliRunner().invoke(
            cli, ["compress", str(src), "--profile", "generic"]
        )
        assert result.exit_code == 0
        assert "larger" not in result.output.lower()

    def test_cursor_profile_warning_does_not_suggest_generic_when_cursor(
        self, tmp_path: Path
    ) -> None:
        """When already using cursor profile the suggestion should not say generic."""
        src = tmp_path / "CLAUDE.md"
        src.write_text("## A\n- x\n")
        result = CliRunner().invoke(
            cli, ["compress", str(src), "--profile", "cursor"]
        )
        # If warning fires it must not suggest switching to a profile already in use
        if "larger" in result.output.lower():
            assert "--profile generic" not in result.output
            assert "--profile cursor" not in result.output

    def test_claude_profile_warning_suggests_generic(self, tmp_path: Path) -> None:
        """With the default claude profile the warning should suggest --profile generic."""
        src = tmp_path / "CLAUDE.md"
        src.write_text("## A\n- x\n")
        result = CliRunner().invoke(cli, ["compress", str(src)])
        assert "larger" in result.output.lower()
        assert "generic" in result.output.lower()


# ---------------------------------------------------------------------------
# 7 — stats shows token projection at each compression level
# ---------------------------------------------------------------------------

STATS_SOURCE = (
    "## Section A\n"
    + "- shared bullet\n" * 10
    + "- unique to A\n"
    + "## Section B\n"
    + "- shared bullet\n" * 10
    + "- unique to B\n"
)


class TestStatsProjection:
    def test_stats_shows_condense_projection(self, tmp_path: Path) -> None:
        src = tmp_path / "CLAUDE.md"
        src.write_text(STATS_SOURCE)
        result = CliRunner().invoke(cli, ["stats", str(src)])
        assert result.exit_code == 0
        assert "condense" in result.output.lower()

    def test_stats_shows_normalize_projection(self, tmp_path: Path) -> None:
        src = tmp_path / "CLAUDE.md"
        src.write_text(STATS_SOURCE)
        result = CliRunner().invoke(cli, ["stats", str(src)])
        assert "normalize" in result.output.lower()

    def test_stats_projection_shows_token_estimate(self, tmp_path: Path) -> None:
        """Projection line must contain a numeric token estimate."""
        import re
        src = tmp_path / "CLAUDE.md"
        src.write_text(STATS_SOURCE)
        result = CliRunner().invoke(cli, ["stats", str(src)])
        assert re.search(r"\d+", result.output)

    def test_stats_condense_estimate_lower_than_current_for_dup_content(
        self, tmp_path: Path
    ) -> None:
        """With heavy duplication, projected condense tokens < current tokens."""
        import re
        src = tmp_path / "CLAUDE.md"
        src.write_text(STATS_SOURCE)
        result = CliRunner().invoke(cli, ["stats", str(src)])
        # Extract all numbers from the projection section
        numbers = [int(n) for n in re.findall(r"\b(\d+)\b", result.output)]
        assert len(numbers) >= 2, "Expected at least current and projected counts"
        # The minimum projected count should be less than the maximum (current)
        assert min(numbers) < max(numbers)

    def test_stats_immutable_sections_not_projected_for_compression(
        self, tmp_path: Path
    ) -> None:
        """Immutable section tokens should be excluded from mutable projection."""
        src = tmp_path / "CLAUDE.md"
        src.write_text(
            "<!-- shrinkwrap: immutable -->\n## Rules\n" + "- rule\n" * 20
            + "## Status\n" + "- item\n" * 20
        )
        result = CliRunner().invoke(cli, ["stats", str(src)])
        assert result.exit_code == 0
        # Should note that immutable sections are not compressed
        assert "immutable" in result.output.lower()


# ---------------------------------------------------------------------------
# 8 — compress and stats discover CLAUDE.md in cwd when no argument given
# ---------------------------------------------------------------------------

class TestAutoDiscovery:
    def test_compress_discovers_claude_md_in_cwd(self, tmp_path: Path) -> None:
        """compress with no argument must find and compress CLAUDE.md in cwd."""
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            Path("CLAUDE.md").write_text("## Status\n- ok\n")
            result = runner.invoke(cli, ["compress"])
            assert result.exit_code == 0
            any_vtbf = any(
                p.suffix == ".md" and "shrinkwrap_schema" in p.read_text()
                for p in Path(".").iterdir()
            )
            assert any_vtbf

    def test_compress_auto_discovery_creates_sw_file(self, tmp_path: Path) -> None:
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            Path("CLAUDE.md").write_text("## Status\n- ok\n")
            runner.invoke(cli, ["compress"])
            assert Path("CLAUDE.md").with_suffix(".sw.md").exists()

    def test_compress_no_arg_no_claude_md_exits_nonzero(
        self, tmp_path: Path
    ) -> None:
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(cli, ["compress"])
            assert result.exit_code != 0

    def test_compress_no_arg_error_mentions_claude_md(
        self, tmp_path: Path
    ) -> None:
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(cli, ["compress"])
            assert "CLAUDE.md" in result.output or "claude" in result.output.lower()

    def test_stats_discovers_claude_md_in_cwd(self, tmp_path: Path) -> None:
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            Path("CLAUDE.md").write_text("## Status\n- ok\n")
            result = runner.invoke(cli, ["stats"])
            assert result.exit_code == 0
            assert "Status" in result.output

    def test_stats_no_arg_no_claude_md_exits_nonzero(
        self, tmp_path: Path
    ) -> None:
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(cli, ["stats"])
            assert result.exit_code != 0

    def test_explicit_file_arg_still_works(self, tmp_path: Path) -> None:
        """Explicit argument must still work normally — auto-discovery is fallback only."""
        src = tmp_path / "myfile.md"
        src.write_text("## Status\n- ok\n")
        result = CliRunner().invoke(cli, ["compress", str(src)])
        assert result.exit_code == 0
        assert src.with_suffix(".sw.md").exists()
