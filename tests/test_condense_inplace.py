"""Tests for condense cross-section deduplication and the compress --in-place flag."""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from shrinkwrap.cli import cli
from shrinkwrap.parser import parse
from shrinkwrap.schema import serialize

# ---------------------------------------------------------------------------
# BUG-1 — condense must actually remove cross-section duplicate bullets
# ---------------------------------------------------------------------------

CROSS_SECTION_SOURCE = (
    "## Section A\n"
    "- shared item\n"
    "- unique to A\n"
    "## Section B\n"
    "- shared item\n"
    "- unique to B\n"
)


class TestCondenseCrossSectionDedup:
    def test_condense_via_serialize_removes_cross_section_duplicate(self) -> None:
        """serialize() with condense must deduplicate bullets shared across sections."""
        doc = parse(CROSS_SECTION_SOURCE)
        for s in doc.sections:
            s.compression = "condense"
        vtbf = serialize(doc, "test.md", CROSS_SECTION_SOURCE)
        # Front-matter won't contain "shared item" — safe to count across full output.
        assert vtbf.count("shared item") == 1, (
            "condense should remove the duplicate 'shared item' bullet from the second section"
        )

    def test_condense_via_cli_removes_cross_section_duplicate(
        self, tmp_path: Path
    ) -> None:
        """CLI compress --level condense must deduplicate across sections."""
        runner = CliRunner()
        src = tmp_path / "CLAUDE.md"
        src.write_text(CROSS_SECTION_SOURCE)
        runner.invoke(cli, ["compress", str(src), "--level", "condense"])
        out = src.with_suffix(".sw.md").read_text()
        assert out.count("shared item") == 1

    def test_condense_unique_bullets_preserved(self, tmp_path: Path) -> None:
        """condense must not remove bullets that are only in one section."""
        runner = CliRunner()
        src = tmp_path / "CLAUDE.md"
        src.write_text(CROSS_SECTION_SOURCE)
        runner.invoke(cli, ["compress", str(src), "--level", "condense"])
        out = src.with_suffix(".sw.md").read_text()
        assert "unique to A" in out
        assert "unique to B" in out

    def test_normalize_does_not_dedup_cross_section(self, tmp_path: Path) -> None:
        """normalize must NOT apply cross-section dedup — both bullets should survive."""
        runner = CliRunner()
        src = tmp_path / "CLAUDE.md"
        src.write_text(CROSS_SECTION_SOURCE)
        runner.invoke(cli, ["compress", str(src), "--level", "normalize"])
        out = src.with_suffix(".sw.md").read_text()
        assert out.count("shared item") == 2

    def test_condense_verify_passes_after_cross_dedup(self, tmp_path: Path) -> None:
        """VTBF output after condense cross-section dedup must still verify clean."""
        runner = CliRunner()
        src = tmp_path / "CLAUDE.md"
        src.write_text(
            "<!-- shrinkwrap: immutable -->\n## Rules\nNever.\n"
            + CROSS_SECTION_SOURCE
        )
        runner.invoke(cli, ["compress", str(src), "--level", "condense"])
        vtbf = src.with_suffix(".sw.md")
        result = runner.invoke(cli, ["verify", str(vtbf)])
        assert result.exit_code == 0

    def test_condense_immutable_sections_not_deduped(self, tmp_path: Path) -> None:
        """Immutable section bullets must never be removed by cross-section dedup."""
        runner = CliRunner()
        src = tmp_path / "CLAUDE.md"
        src.write_text(
            "<!-- shrinkwrap: immutable -->\n## Rules\n- shared item\nNever.\n"
            "## Status\n- shared item\n- other\n"
        )
        runner.invoke(cli, ["compress", str(src), "--level", "condense"])
        out = src.with_suffix(".sw.md").read_text()
        # Both sections contain "shared item"; immutable must keep its copy
        assert out.count("shared item") >= 1


# ---------------------------------------------------------------------------
# BUG-2 — --in-place flag: compress overwrites the source file
# ---------------------------------------------------------------------------

class TestInPlaceFlag:
    def test_in_place_exits_zero(self, tmp_path: Path) -> None:
        runner = CliRunner()
        src = tmp_path / "CLAUDE.md"
        src.write_text("## Status\n- ok\n")
        result = runner.invoke(cli, ["compress", str(src), "--in-place"])
        assert result.exit_code == 0

    def test_in_place_writes_vtbf_to_source_file(self, tmp_path: Path) -> None:
        runner = CliRunner()
        src = tmp_path / "CLAUDE.md"
        src.write_text("## Status\n- ok\n")
        runner.invoke(cli, ["compress", str(src), "--in-place"])
        assert "shrinkwrap_schema" in src.read_text()

    def test_in_place_does_not_create_sw_md_file(self, tmp_path: Path) -> None:
        runner = CliRunner()
        src = tmp_path / "CLAUDE.md"
        src.write_text("## Status\n- ok\n")
        runner.invoke(cli, ["compress", str(src), "--in-place"])
        assert not src.with_suffix(".sw.md").exists()

    def test_in_place_output_passes_verify(self, tmp_path: Path) -> None:
        runner = CliRunner()
        src = tmp_path / "CLAUDE.md"
        src.write_text(
            "<!-- shrinkwrap: immutable -->\n## Rules\nNever.\n## Status\n- ok\n"
        )
        runner.invoke(cli, ["compress", str(src), "--in-place"])
        result = runner.invoke(cli, ["verify", str(src)])
        assert result.exit_code == 0

    def test_in_place_dry_run_does_not_modify_source(self, tmp_path: Path) -> None:
        runner = CliRunner()
        src = tmp_path / "CLAUDE.md"
        original = "## Status\n- ok\n"
        src.write_text(original)
        runner.invoke(cli, ["compress", str(src), "--in-place", "--dry-run"])
        assert src.read_text() == original

    def test_in_place_and_output_are_mutually_exclusive(self, tmp_path: Path) -> None:
        """--in-place and --output together must produce a non-zero exit."""
        runner = CliRunner()
        src = tmp_path / "CLAUDE.md"
        src.write_text("## Status\n- ok\n")
        result = runner.invoke(
            cli,
            ["compress", str(src), "--in-place", "--output", str(tmp_path / "out.md")],
        )
        assert result.exit_code != 0

    def test_in_place_compress_twice_is_idempotent(self, tmp_path: Path) -> None:
        """Compressing in-place twice must produce the same section count."""
        runner = CliRunner()
        src = tmp_path / "CLAUDE.md"
        src.write_text("## Security Rules\nNever eval.\n## Status\n- ok\n")
        runner.invoke(cli, ["compress", str(src), "--in-place"])
        count_after_first = src.read_text().count("<!-- sw:section")
        runner.invoke(cli, ["compress", str(src), "--in-place"])
        count_after_second = src.read_text().count("<!-- sw:section")
        assert count_after_first == count_after_second

    def test_in_place_preserves_immutable_content(self, tmp_path: Path) -> None:
        runner = CliRunner()
        src = tmp_path / "CLAUDE.md"
        src.write_text(
            "<!-- shrinkwrap: immutable -->\n## Rules\nNever use eval().\n"
        )
        runner.invoke(cli, ["compress", str(src), "--in-place"])
        assert "Never use eval()." in src.read_text()
