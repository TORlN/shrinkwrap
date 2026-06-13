"""Tests for upgrade VTBF validation and the verify --json machine-readable output flag."""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from shrinkwrap.cli import cli

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _compress(runner: CliRunner, src: Path) -> Path:
    runner.invoke(cli, ["compress", str(src)])
    return src.with_suffix(".sw.md")


# ---------------------------------------------------------------------------
# 1 — upgrade must validate that the input is a real VTBF file
# ---------------------------------------------------------------------------

class TestUpgradeValidation:
    def test_upgrade_on_plain_markdown_exits_nonzero(
        self, tmp_path: Path
    ) -> None:
        """upgrade on a plain markdown file (no VTBF front-matter) must exit non-zero."""
        src = tmp_path / "CLAUDE.md"
        src.write_text("## Status\n- ok\n")
        result = CliRunner().invoke(cli, ["upgrade", str(src)])
        assert result.exit_code != 0

    def test_upgrade_on_plain_markdown_mentions_error(
        self, tmp_path: Path
    ) -> None:
        """upgrade on non-VTBF must print a helpful error, not a success message."""
        src = tmp_path / "CLAUDE.md"
        src.write_text("## Status\n- ok\n")
        result = CliRunner().invoke(cli, ["upgrade", str(src)])
        output_lower = result.output.lower()
        assert (
            "not a vtbf" in output_lower
            or "not compressed" in output_lower
            or "shrinkwrap_schema" in output_lower
            or "compress" in output_lower
        )

    def test_upgrade_on_valid_vtbf_exits_zero(self, tmp_path: Path) -> None:
        """upgrade on a valid VTBF file must exit zero."""
        src = tmp_path / "CLAUDE.md"
        src.write_text("## Status\n- ok\n")
        runner = CliRunner()
        vtbf = _compress(runner, src)
        result = runner.invoke(cli, ["upgrade", str(vtbf)])
        assert result.exit_code == 0

    def test_upgrade_on_valid_vtbf_mentions_schema_version(
        self, tmp_path: Path
    ) -> None:
        """upgrade on a valid VTBF must mention the current schema version."""
        src = tmp_path / "CLAUDE.md"
        src.write_text("## Status\n- ok\n")
        runner = CliRunner()
        vtbf = _compress(runner, src)
        result = runner.invoke(cli, ["upgrade", str(vtbf)])
        assert "1.0" in result.output

    def test_upgrade_does_not_print_success_for_plain_file(
        self, tmp_path: Path
    ) -> None:
        """'already at latest' must NOT appear for a non-VTBF file."""
        src = tmp_path / "CLAUDE.md"
        src.write_text("## Status\n- ok\n")
        result = CliRunner().invoke(cli, ["upgrade", str(src)])
        assert "already at latest" not in result.output.lower()


# ---------------------------------------------------------------------------
# 2 — verify --json outputs machine-readable JSON
# ---------------------------------------------------------------------------

class TestVerifyJsonFlag:
    def test_verify_json_valid_file_outputs_valid_json(
        self, tmp_path: Path
    ) -> None:
        """verify --json must produce parseable JSON output."""
        src = tmp_path / "CLAUDE.md"
        src.write_text("## Status\n- ok\n")
        runner = CliRunner()
        vtbf = _compress(runner, src)
        result = runner.invoke(cli, ["verify", str(vtbf), "--json"])
        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert isinstance(parsed, dict)

    def test_verify_json_valid_file_has_valid_true(
        self, tmp_path: Path
    ) -> None:
        src = tmp_path / "CLAUDE.md"
        src.write_text("## Status\n- ok\n")
        runner = CliRunner()
        vtbf = _compress(runner, src)
        result = runner.invoke(cli, ["verify", str(vtbf), "--json"])
        parsed = json.loads(result.output)
        assert parsed["valid"] is True

    def test_verify_json_valid_file_has_empty_errors(
        self, tmp_path: Path
    ) -> None:
        src = tmp_path / "CLAUDE.md"
        src.write_text("## Status\n- ok\n")
        runner = CliRunner()
        vtbf = _compress(runner, src)
        result = runner.invoke(cli, ["verify", str(vtbf), "--json"])
        parsed = json.loads(result.output)
        assert parsed["errors"] == []

    def test_verify_json_invalid_file_has_valid_false(
        self, tmp_path: Path
    ) -> None:
        """A non-VTBF file must produce {valid: false, errors: [...]}."""
        src = tmp_path / "not_vtbf.md"
        src.write_text("## Status\n- ok\n")
        result = CliRunner().invoke(cli, ["verify", str(src), "--json"])
        parsed = json.loads(result.output)
        assert parsed["valid"] is False

    def test_verify_json_invalid_file_has_errors_list(
        self, tmp_path: Path
    ) -> None:
        src = tmp_path / "not_vtbf.md"
        src.write_text("## Status\n- ok\n")
        result = CliRunner().invoke(cli, ["verify", str(src), "--json"])
        parsed = json.loads(result.output)
        assert isinstance(parsed["errors"], list)
        assert len(parsed["errors"]) > 0

    def test_verify_json_invalid_file_exits_nonzero(
        self, tmp_path: Path
    ) -> None:
        src = tmp_path / "not_vtbf.md"
        src.write_text("## Status\n- ok\n")
        result = CliRunner().invoke(cli, ["verify", str(src), "--json"])
        assert result.exit_code != 0

    def test_verify_json_includes_warnings_key(
        self, tmp_path: Path
    ) -> None:
        src = tmp_path / "CLAUDE.md"
        src.write_text("## Status\n- ok\n")
        runner = CliRunner()
        vtbf = _compress(runner, src)
        result = runner.invoke(cli, ["verify", str(vtbf), "--json"])
        parsed = json.loads(result.output)
        assert "warnings" in parsed

    def test_verify_without_json_flag_still_works(
        self, tmp_path: Path
    ) -> None:
        """The existing human-readable output must still work without --json."""
        src = tmp_path / "CLAUDE.md"
        src.write_text("## Status\n- ok\n")
        runner = CliRunner()
        vtbf = _compress(runner, src)
        result = runner.invoke(cli, ["verify", str(vtbf)])
        assert result.exit_code == 0
        assert "Valid" in result.output

    def test_verify_json_output_is_not_rich_markup(
        self, tmp_path: Path
    ) -> None:
        """--json output must be raw JSON, not rich-decorated text."""
        src = tmp_path / "CLAUDE.md"
        src.write_text("## Status\n- ok\n")
        runner = CliRunner()
        vtbf = _compress(runner, src)
        result = runner.invoke(cli, ["verify", str(vtbf), "--json"])
        # Must not contain rich markup like [green] or ✓
        assert "[green]" not in result.output
        assert "✓" not in result.output
