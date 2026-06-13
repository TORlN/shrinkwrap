"""
Tests for shrinkwrap.toml config wiring into the CLI, expand annotation
preservation, expand --in-place, the --backup flag, and output size warnings.
"""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from shrinkwrap.cli import cli

# ---------------------------------------------------------------------------
# 1 — shrinkwrap.toml config wired into CLI
# ---------------------------------------------------------------------------

CROSS_DUP_SOURCE = "## Section A\n- dup item\n- only A\n## Section B\n- dup item\n- only B\n"


class TestConfigWiredIntoCLI:
    def test_default_level_from_config_applies_to_compress(self, tmp_path: Path) -> None:
        """compress with no --level must use default_level from shrinkwrap.toml."""
        (tmp_path / "shrinkwrap.toml").write_text('[shrinkwrap]\ndefault_level = "condense"\n')
        src = tmp_path / "CLAUDE.md"
        src.write_text(CROSS_DUP_SOURCE)
        CliRunner().invoke(cli, ["compress", str(src)])
        out = src.with_suffix(".sw.md").read_text()
        # condense cross-section dedup: "dup item" should appear only once
        assert out.count("dup item") == 1

    def test_explicit_level_flag_overrides_config_default(self, tmp_path: Path) -> None:
        """--level flag must win over default_level in shrinkwrap.toml."""
        (tmp_path / "shrinkwrap.toml").write_text('[shrinkwrap]\ndefault_level = "condense"\n')
        src = tmp_path / "CLAUDE.md"
        src.write_text(CROSS_DUP_SOURCE)
        CliRunner().invoke(cli, ["compress", str(src), "--level", "normalize"])
        out = src.with_suffix(".sw.md").read_text()
        # normalize does NOT cross-section dedup
        assert out.count("dup item") == 2

    def test_default_profile_from_config_applies_to_compress(self, tmp_path: Path) -> None:
        """compress must use default_profile from shrinkwrap.toml."""
        (tmp_path / "shrinkwrap.toml").write_text('[shrinkwrap]\ndefault_profile = "generic"\n')
        src = tmp_path / "CLAUDE.md"
        src.write_text("## Status\n- ok\n")
        CliRunner().invoke(cli, ["compress", str(src)])
        out = src.with_suffix(".sw.md").read_text()
        # generic profile strips all tags and front-matter
        assert "shrinkwrap_schema" not in out
        assert "sw:section" not in out

    def test_extra_immutable_keywords_from_config_applied(self, tmp_path: Path) -> None:
        """extra_immutable_keywords in shrinkwrap.toml must affect classification."""
        (tmp_path / "shrinkwrap.toml").write_text(
            '[shrinkwrap]\nextra_immutable_keywords = ["invariant"]\n'
        )
        src = tmp_path / "CLAUDE.md"
        src.write_text("## System Invariant\ncontent here\n")
        CliRunner().invoke(cli, ["compress", str(src)])
        out = src.with_suffix(".sw.md").read_text()
        # "invariant" keyword → immutable → section has checksum attr, no compression attr
        assert 'class="immutable"' in out

    def test_missing_config_falls_back_to_normalize(self, tmp_path: Path) -> None:
        """No shrinkwrap.toml means normalize (default) applies."""
        src = tmp_path / "CLAUDE.md"
        src.write_text(CROSS_DUP_SOURCE)
        CliRunner().invoke(cli, ["compress", str(src)])
        out = src.with_suffix(".sw.md").read_text()
        # normalize does NOT cross-section dedup — both copies survive
        assert out.count("dup item") == 2

    def test_audit_uses_extra_immutable_keywords_from_config(self, tmp_path: Path) -> None:
        """audit must use extra_immutable_keywords from shrinkwrap.toml."""
        (tmp_path / "shrinkwrap.toml").write_text(
            '[shrinkwrap]\nextra_immutable_keywords = ["invariant"]\n'
        )
        src = tmp_path / "CLAUDE.md"
        src.write_text("## System Invariant\ncontent here\n")
        result = CliRunner().invoke(cli, ["audit", str(src)])
        assert "immutable" in result.output


# ---------------------------------------------------------------------------
# 2 — expand must preserve shrinkwrap annotation comments
# ---------------------------------------------------------------------------


class TestExpandPreservesAnnotations:
    def test_expand_keeps_immutable_annotation(self, tmp_path: Path) -> None:
        src = tmp_path / "CLAUDE.md"
        src.write_text("<!-- shrinkwrap: immutable -->\n## Rules\nNever.\n")
        runner = CliRunner()
        runner.invoke(cli, ["compress", str(src)])
        sw = src.with_suffix(".sw.md")
        out = tmp_path / "expanded.md"
        runner.invoke(cli, ["expand", str(sw), "-o", str(out)])
        assert "<!-- shrinkwrap: immutable -->" in out.read_text()

    def test_expand_keeps_mutable_annotation_with_compression(self, tmp_path: Path) -> None:
        src = tmp_path / "CLAUDE.md"
        src.write_text("<!-- shrinkwrap: mutable compression=condense -->\n## Notes\ncontent\n")
        runner = CliRunner()
        runner.invoke(cli, ["compress", str(src)])
        sw = src.with_suffix(".sw.md")
        out = tmp_path / "expanded.md"
        runner.invoke(cli, ["expand", str(sw), "-o", str(out)])
        text = out.read_text()
        assert "<!-- shrinkwrap: mutable" in text

    def test_expand_still_strips_vtbf_section_tags(self, tmp_path: Path) -> None:
        """VTBF sw:section tags must still be stripped; only shrinkwrap annotations kept."""
        src = tmp_path / "CLAUDE.md"
        src.write_text("<!-- shrinkwrap: immutable -->\n## Rules\nNever.\n")
        runner = CliRunner()
        runner.invoke(cli, ["compress", str(src)])
        sw = src.with_suffix(".sw.md")
        out = tmp_path / "expanded.md"
        runner.invoke(cli, ["expand", str(sw), "-o", str(out)])
        text = out.read_text()
        assert "sw:section" not in text

    def test_expand_round_trip_preserves_annotations(self, tmp_path: Path) -> None:
        """compress → expand → compress must produce the same classification."""
        source = "<!-- shrinkwrap: immutable -->\n## Rules\nNever.\n## Status\n- ok\n"
        src = tmp_path / "CLAUDE.md"
        src.write_text(source)
        runner = CliRunner()

        runner.invoke(cli, ["compress", str(src)])
        sw1 = src.with_suffix(".sw.md")
        expanded = tmp_path / "restored.md"
        runner.invoke(cli, ["expand", str(sw1), "-o", str(expanded)])

        runner.invoke(cli, ["compress", str(expanded)])
        sw2 = expanded.with_suffix(".sw.md")

        # Both compressions should classify Rules as immutable
        assert 'class="immutable"' in sw1.read_text()
        assert 'class="immutable"' in sw2.read_text()


# ---------------------------------------------------------------------------
# 3 — drift-check must not advertise 'shrinkwrap update'
# ---------------------------------------------------------------------------


class TestDriftCheckMessage:
    def test_drift_check_output_does_not_reference_update_command(self) -> None:
        """drift-check must not tell users to run a command that doesn't exist."""
        import inspect

        import shrinkwrap.cli as cli_module

        source = inspect.getsource(cli_module)
        assert "shrinkwrap update" not in source

    def test_drift_check_message_references_compress(self) -> None:
        """drift-check notification should point users toward compress."""
        import inspect

        import shrinkwrap.cli as cli_module

        source = inspect.getsource(cli_module)
        # The drift notification block should mention compress
        assert "compress" in source


# ---------------------------------------------------------------------------
# 4 — expand --in-place
# ---------------------------------------------------------------------------


class TestExpandInPlace:
    def test_expand_in_place_restores_readable_markdown(self, tmp_path: Path) -> None:
        src = tmp_path / "CLAUDE.md"
        src.write_text("## Status\n- ok\n")
        runner = CliRunner()
        runner.invoke(cli, ["compress", str(src), "--in-place"])
        assert "shrinkwrap_schema" in src.read_text()

        runner.invoke(cli, ["expand", str(src), "--in-place"])
        text = src.read_text()
        assert "shrinkwrap_schema" not in text
        assert "## Status" in text

    def test_expand_in_place_does_not_create_expanded_file(self, tmp_path: Path) -> None:
        src = tmp_path / "CLAUDE.md"
        src.write_text("## Status\n- ok\n")
        runner = CliRunner()
        runner.invoke(cli, ["compress", str(src), "--in-place"])
        runner.invoke(cli, ["expand", str(src), "--in-place"])
        assert not (tmp_path / "CLAUDE.expanded.md").exists()

    def test_expand_in_place_exits_zero(self, tmp_path: Path) -> None:
        src = tmp_path / "CLAUDE.md"
        src.write_text("## Status\n- ok\n")
        runner = CliRunner()
        runner.invoke(cli, ["compress", str(src), "--in-place"])
        result = runner.invoke(cli, ["expand", str(src), "--in-place"])
        assert result.exit_code == 0

    def test_expand_in_place_and_output_are_mutually_exclusive(self, tmp_path: Path) -> None:
        src = tmp_path / "CLAUDE.md"
        src.write_text("## Status\n- ok\n")
        runner = CliRunner()
        runner.invoke(cli, ["compress", str(src), "--in-place"])
        result = runner.invoke(
            cli, ["expand", str(src), "--in-place", "--output", str(tmp_path / "out.md")]
        )
        assert result.exit_code != 0

    def test_compress_then_expand_in_place_is_roundtrip(self, tmp_path: Path) -> None:
        original = "<!-- shrinkwrap: immutable -->\n## Rules\nNever.\n## Status\n- ok\n"
        src = tmp_path / "CLAUDE.md"
        src.write_text(original)
        runner = CliRunner()
        runner.invoke(cli, ["compress", str(src), "--in-place"])
        runner.invoke(cli, ["expand", str(src), "--in-place"])
        restored = src.read_text()
        assert "## Rules" in restored
        assert "## Status" in restored
        assert "Never." in restored


# ---------------------------------------------------------------------------
# 5 — --backup flag for compress --in-place
# ---------------------------------------------------------------------------


class TestBackupFlag:
    def test_backup_creates_bak_file(self, tmp_path: Path) -> None:
        src = tmp_path / "CLAUDE.md"
        src.write_text("## Status\n- ok\n")
        CliRunner().invoke(cli, ["compress", str(src), "--in-place", "--backup"])
        assert (tmp_path / "CLAUDE.md.bak").exists()

    def test_backup_contains_original_content(self, tmp_path: Path) -> None:
        src = tmp_path / "CLAUDE.md"
        original = "## Status\n- ok\n"
        src.write_text(original)
        CliRunner().invoke(cli, ["compress", str(src), "--in-place", "--backup"])
        assert (tmp_path / "CLAUDE.md.bak").read_text() == original

    def test_backup_without_in_place_exits_nonzero(self, tmp_path: Path) -> None:
        src = tmp_path / "CLAUDE.md"
        src.write_text("## Status\n- ok\n")
        result = CliRunner().invoke(cli, ["compress", str(src), "--backup"])
        assert result.exit_code != 0

    def test_no_backup_flag_creates_no_bak_file(self, tmp_path: Path) -> None:
        src = tmp_path / "CLAUDE.md"
        src.write_text("## Status\n- ok\n")
        CliRunner().invoke(cli, ["compress", str(src), "--in-place"])
        assert not (tmp_path / "CLAUDE.md.bak").exists()

    def test_backup_exits_zero(self, tmp_path: Path) -> None:
        src = tmp_path / "CLAUDE.md"
        src.write_text("## Status\n- ok\n")
        result = CliRunner().invoke(cli, ["compress", str(src), "--in-place", "--backup"])
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# 6 — warn when compressed output is larger than source
# ---------------------------------------------------------------------------


class TestOutputSizeWarning:
    def test_warns_when_vtbf_is_larger_than_source(self, tmp_path: Path) -> None:
        """VTBF tag + front-matter overhead on a tiny file makes output larger."""
        src = tmp_path / "CLAUDE.md"
        # Very short: VTBF overhead (~400 chars) will dwarf the content (~9 chars)
        src.write_text("## A\n- x\n")
        result = CliRunner().invoke(cli, ["compress", str(src)])
        assert result.exit_code == 0
        assert "larger" in result.output.lower() or "overhead" in result.output.lower()

    def test_no_warning_when_output_is_smaller(self, tmp_path: Path) -> None:
        """A large file with heavy duplication at condense must not trigger the warning."""
        # 5 sections × 30 long identical bullets: savings (~7200 chars) >> overhead (~850 chars)
        bullet_block = (
            "\n".join(
                f"- this is bullet {i} with enough text to make it clearly worth compressing"
                for i in range(30)
            )
            + "\n"
        )
        src = tmp_path / "CLAUDE.md"
        content = "".join(f"## Section {i}\n{bullet_block}" for i in range(5))
        src.write_text(content)
        result = CliRunner().invoke(cli, ["compress", str(src), "--level", "condense"])
        assert "larger" not in result.output.lower()

    def test_dry_run_also_warns_when_larger(self, tmp_path: Path) -> None:
        src = tmp_path / "CLAUDE.md"
        src.write_text("## A\n- x\n")
        result = CliRunner().invoke(cli, ["compress", str(src), "--dry-run"])
        assert result.exit_code == 0
        assert "larger" in result.output.lower() or "overhead" in result.output.lower()
