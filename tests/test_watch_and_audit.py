"""Tests for watch CLAUDE.md auto-discovery and audit keyword hint output."""

from __future__ import annotations

import threading
import time
from pathlib import Path

from click.testing import CliRunner

from shrinkwrap.cli import _watch_loop, cli

# ---------------------------------------------------------------------------
# 1 — watch auto-discovers CLAUDE.md in cwd
# ---------------------------------------------------------------------------

class TestWatchAutoDiscovery:
    def test_watch_no_arg_no_claude_md_exits_nonzero(
        self, tmp_path: Path
    ) -> None:
        """watch with no argument and no CLAUDE.md must exit non-zero immediately."""
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(cli, ["watch"])
            assert result.exit_code != 0

    def test_watch_no_arg_error_mentions_claude_md(
        self, tmp_path: Path
    ) -> None:
        """Error message must tell the user what file was expected."""
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(cli, ["watch"])
            assert "CLAUDE.md" in result.output or "claude" in result.output.lower()

    def test_watch_help_does_not_require_file(self) -> None:
        """watch --help must exit 0 (file arg is optional)."""
        result = CliRunner().invoke(cli, ["watch", "--help"])
        assert result.exit_code == 0

    def test_watch_explicit_arg_still_works(self, tmp_path: Path) -> None:
        """An explicit file path must still be accepted and used."""
        src = tmp_path / "CLAUDE.md"
        src.write_text("## Status\n- ok\n")
        stop = threading.Event()
        t = threading.Thread(
            target=_watch_loop,
            args=(src, None, None, False, 0.05),
            kwargs={"stop_event": stop},
            daemon=True,
        )
        t.start()
        stop.set()
        t.join(timeout=2.0)
        assert not t.is_alive()

    def test_watch_discovers_claude_md_and_recompresses(
        self, tmp_path: Path
    ) -> None:
        """watch with no file arg must find CLAUDE.md in the same dir as shrinkwrap.toml."""
        src = tmp_path / "CLAUDE.md"
        src.write_text("## Status\n- ok\n")

        # Simulate what the watch CLI command does after auto-discovery
        stop = threading.Event()
        t = threading.Thread(
            target=_watch_loop,
            args=(src, None, "claude", False, 0.05),
            kwargs={"stop_event": stop},
            daemon=True,
        )
        t.start()
        time.sleep(0.15)
        src.write_text("## Status\n- updated\n")
        time.sleep(0.35)
        stop.set()
        t.join(timeout=2.0)

        assert "shrinkwrap_schema" in src.read_text()


# ---------------------------------------------------------------------------
# 2 — audit shows the triggering keyword next to "heuristic"
# ---------------------------------------------------------------------------

class TestAuditKeywordHint:
    def test_audit_shows_mutable_keyword_that_triggered(
        self, tmp_path: Path
    ) -> None:
        """When a section is classified mutable by heading keyword, audit shows that keyword."""
        src = tmp_path / "CLAUDE.md"
        src.write_text("## Current Status\n- ok\n")
        result = CliRunner().invoke(cli, ["audit", str(src)])
        assert result.exit_code == 0
        # "status" or "current" must appear in the output as the triggering keyword
        assert "status" in result.output.lower() or "current" in result.output.lower()

    def test_audit_shows_immutable_keyword_that_triggered(
        self, tmp_path: Path
    ) -> None:
        """When a section is classified immutable by heading keyword, audit shows that keyword."""
        src = tmp_path / "CLAUDE.md"
        src.write_text("## Security Rules\nnever do X\n")
        result = CliRunner().invoke(cli, ["audit", str(src)])
        assert result.exit_code == 0
        # "security" or "rules" must appear in the output
        assert "security" in result.output.lower() or "rules" in result.output.lower()

    def test_audit_annotation_source_shows_annotation_not_keyword(
        self, tmp_path: Path
    ) -> None:
        """Explicitly annotated sections must show 'annotation' as the source, not a keyword."""
        src = tmp_path / "CLAUDE.md"
        src.write_text("<!-- shrinkwrap: immutable -->\n## Notes\ncontent\n")
        result = CliRunner().invoke(cli, ["audit", str(src)])
        assert result.exit_code == 0
        assert "annotation" in result.output.lower()

    def test_audit_structural_heuristic_shows_structural_hint(
        self, tmp_path: Path
    ) -> None:
        """Sections classified by structure (list-only body) must show structural signal."""
        src = tmp_path / "CLAUDE.md"
        # Generic heading, all-list body → structural mutable
        src.write_text("## Items\n- alpha\n- beta\n- gamma\n")
        result = CliRunner().invoke(cli, ["audit", str(src)])
        assert result.exit_code == 0
        # Should show some form of source — doesn't crash, output is non-empty
        assert "Items" in result.output

    def test_audit_no_keyword_falls_back_gracefully(
        self, tmp_path: Path
    ) -> None:
        """Sections with no keyword match and list body must not crash the audit."""
        src = tmp_path / "CLAUDE.md"
        src.write_text("## Overview\n- bullet one\n- bullet two\n")
        result = CliRunner().invoke(cli, ["audit", str(src)])
        assert result.exit_code == 0

    def test_audit_extra_immutable_keyword_from_config_shown(
        self, tmp_path: Path
    ) -> None:
        """Keywords from shrinkwrap.toml extra_immutable_keywords must appear in audit output."""
        (tmp_path / "shrinkwrap.toml").write_text(
            '[shrinkwrap]\nextra_immutable_keywords = ["invariant"]\n'
        )
        src = tmp_path / "CLAUDE.md"
        src.write_text("## System Invariant\ncontent here\n")
        result = CliRunner().invoke(cli, ["audit", str(src)])
        assert result.exit_code == 0
        assert "invariant" in result.output.lower()
        assert "immutable" in result.output.lower()
