"""Failing tests for the unified metrics feature (TDD Step 1).

These tests are intentionally red — they drive the implementation in Step 2.
They assert:
  - CompressionMetrics dataclass exists and has the correct fields
  - compress_with_metrics() returns (vtbf_str, CompressionMetrics)
  - consolidate_with_metrics() returns (merged_str, CompressionMetrics)
  - CLI compress prints a metrics table after --output / --in-place / --dry-run
  - CLI consolidate always prints a metrics table
"""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from shrinkwrap.cli import cli
from shrinkwrap.consolidate import consolidate_with_metrics
from shrinkwrap.metrics import CompressionMetrics
from shrinkwrap.parser import parse
from shrinkwrap.schema import compress_with_metrics

_SIMPLE_DOC = """\
## Current Sprint

- Working on OAuth2
- tests are passing on main

## Security Rules

Never commit secrets.
"""

_DUP_BULLET_DOC = """\
<!-- shrinkwrap: mutable compression=condense -->
## Section A

- shared bullet
- unique to A

<!-- shrinkwrap: mutable compression=condense -->
## Section B

- shared bullet
- unique to B
"""


# ---------------------------------------------------------------------------
# CompressionMetrics dataclass
# ---------------------------------------------------------------------------


class TestCompressionMetricsDataclass:
    def test_instantiation_with_all_fields(self) -> None:
        m = CompressionMetrics(
            files_processed=1,
            tokens_before=100,
            tokens_after=80,
            tokens_saved=20,
            compression_pct=20.0,
            duplicate_sections_removed=0,
            duplicate_bullets_removed=0,
        )
        assert m.files_processed == 1
        assert m.tokens_before == 100
        assert m.tokens_after == 80
        assert m.tokens_saved == 20
        assert m.compression_pct == 20.0
        assert m.duplicate_sections_removed == 0
        assert m.duplicate_bullets_removed == 0

    def test_tokens_saved_arithmetic(self) -> None:
        m = CompressionMetrics(
            files_processed=1,
            tokens_before=200,
            tokens_after=150,
            tokens_saved=50,
            compression_pct=25.0,
            duplicate_sections_removed=0,
            duplicate_bullets_removed=0,
        )
        assert m.tokens_saved == m.tokens_before - m.tokens_after

    def test_compression_pct_arithmetic(self) -> None:
        m = CompressionMetrics(
            files_processed=1,
            tokens_before=200,
            tokens_after=150,
            tokens_saved=50,
            compression_pct=25.0,
            duplicate_sections_removed=0,
            duplicate_bullets_removed=0,
        )
        expected = round(m.tokens_saved / m.tokens_before * 100, 1)
        assert m.compression_pct == expected


# ---------------------------------------------------------------------------
# compress_with_metrics()
# ---------------------------------------------------------------------------


class TestCompressWithMetrics:
    def test_returns_two_tuple(self) -> None:
        doc = parse(_SIMPLE_DOC)
        result = compress_with_metrics(doc, "test.md", _SIMPLE_DOC)
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_first_element_is_vtbf_string(self) -> None:
        doc = parse(_SIMPLE_DOC)
        vtbf, _ = compress_with_metrics(doc, "test.md", _SIMPLE_DOC)
        assert isinstance(vtbf, str)
        assert "shrinkwrap_schema" in vtbf

    def test_second_element_is_compression_metrics(self) -> None:
        doc = parse(_SIMPLE_DOC)
        _, metrics = compress_with_metrics(doc, "test.md", _SIMPLE_DOC)
        assert isinstance(metrics, CompressionMetrics)

    def test_files_processed_always_one(self) -> None:
        doc = parse(_SIMPLE_DOC)
        _, metrics = compress_with_metrics(doc, "test.md", _SIMPLE_DOC)
        assert metrics.files_processed == 1

    def test_tokens_before_positive(self) -> None:
        doc = parse(_SIMPLE_DOC)
        _, metrics = compress_with_metrics(doc, "test.md", _SIMPLE_DOC)
        assert metrics.tokens_before > 0

    def test_tokens_after_positive(self) -> None:
        doc = parse(_SIMPLE_DOC)
        _, metrics = compress_with_metrics(doc, "test.md", _SIMPLE_DOC)
        assert metrics.tokens_after > 0

    def test_tokens_saved_equals_difference(self) -> None:
        doc = parse(_SIMPLE_DOC)
        _, metrics = compress_with_metrics(doc, "test.md", _SIMPLE_DOC)
        assert metrics.tokens_saved == metrics.tokens_before - metrics.tokens_after

    def test_compression_pct_equals_derived_value(self) -> None:
        doc = parse(_SIMPLE_DOC)
        _, metrics = compress_with_metrics(doc, "test.md", _SIMPLE_DOC)
        expected = round(metrics.tokens_saved / max(metrics.tokens_before, 1) * 100, 1)
        assert metrics.compression_pct == expected

    def test_no_duplicate_sections_for_single_file(self) -> None:
        doc = parse(_SIMPLE_DOC)
        _, metrics = compress_with_metrics(doc, "test.md", _SIMPLE_DOC)
        assert metrics.duplicate_sections_removed == 0

    def test_duplicate_bullets_removed_counted(self) -> None:
        doc = parse(_DUP_BULLET_DOC)
        _, metrics = compress_with_metrics(doc, "test.md", _DUP_BULLET_DOC)
        # "shared bullet" appears in both sections; cross-section dedup removes it from B
        assert metrics.duplicate_bullets_removed >= 1

    def test_no_duplicate_bullets_when_none_shared(self) -> None:
        doc = parse(_SIMPLE_DOC)
        _, metrics = compress_with_metrics(doc, "test.md", _SIMPLE_DOC)
        assert metrics.duplicate_bullets_removed == 0


# ---------------------------------------------------------------------------
# consolidate_with_metrics()
# ---------------------------------------------------------------------------


class TestConsolidateWithMetrics:
    def test_returns_two_tuple(self, tmp_path: Path) -> None:
        f1 = tmp_path / "CLAUDE.md"
        f1.write_text("## Section A\n\n- item 1\n")
        result = consolidate_with_metrics([f1])
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_first_element_is_merged_string(self, tmp_path: Path) -> None:
        f1 = tmp_path / "CLAUDE.md"
        f1.write_text("## Section A\n\n- item 1\n")
        merged, _ = consolidate_with_metrics([f1])
        assert isinstance(merged, str)
        assert "Section A" in merged

    def test_second_element_is_compression_metrics(self, tmp_path: Path) -> None:
        f1 = tmp_path / "CLAUDE.md"
        f1.write_text("## Section A\n\n- item 1\n")
        _, metrics = consolidate_with_metrics([f1])
        assert isinstance(metrics, CompressionMetrics)

    def test_files_processed_reflects_input_count(self, tmp_path: Path) -> None:
        f1 = tmp_path / "CLAUDE.md"
        f1.write_text("## Section A\n\n- item 1\n")
        f2 = tmp_path / "AGENTS.md"
        f2.write_text("## Section B\n\n- item 2\n")
        _, metrics = consolidate_with_metrics([f1, f2])
        assert metrics.files_processed == 2

    def test_duplicate_sections_counted_when_headings_clash(self, tmp_path: Path) -> None:
        f1 = tmp_path / "CLAUDE.md"
        f1.write_text("## Security Rules\n\nNever commit secrets.\n")
        f2 = tmp_path / "AGENTS.md"
        f2.write_text("## Security Rules\n\nDo not do bad things.\n")
        _, metrics = consolidate_with_metrics([f1, f2])
        assert metrics.duplicate_sections_removed == 1

    def test_no_duplicate_sections_when_headings_unique(self, tmp_path: Path) -> None:
        f1 = tmp_path / "CLAUDE.md"
        f1.write_text("## Section A\n\n- item 1\n")
        f2 = tmp_path / "AGENTS.md"
        f2.write_text("## Section B\n\n- item 2\n")
        _, metrics = consolidate_with_metrics([f1, f2])
        assert metrics.duplicate_sections_removed == 0

    def test_duplicate_bullets_counted_across_files(self, tmp_path: Path) -> None:
        f1 = tmp_path / "CLAUDE.md"
        f1.write_text("## Section A\n\n- shared bullet\n- unique to A\n")
        f2 = tmp_path / "AGENTS.md"
        f2.write_text("## Section B\n\n- shared bullet\n- unique to B\n")
        _, metrics = consolidate_with_metrics([f1, f2])
        assert metrics.duplicate_bullets_removed >= 1

    def test_tokens_before_positive(self, tmp_path: Path) -> None:
        f1 = tmp_path / "CLAUDE.md"
        f1.write_text("## Section A\n\n- item 1\n")
        _, metrics = consolidate_with_metrics([f1])
        assert metrics.tokens_before > 0

    def test_tokens_saved_non_negative(self, tmp_path: Path) -> None:
        f1 = tmp_path / "CLAUDE.md"
        f1.write_text("## Security Rules\n\nNever commit secrets.\n")
        f2 = tmp_path / "AGENTS.md"
        f2.write_text("## Security Rules\n\nDo not do bad things.\n")
        _, metrics = consolidate_with_metrics([f1, f2])
        assert metrics.tokens_saved >= 0
        assert metrics.tokens_saved == metrics.tokens_before - metrics.tokens_after

    def test_empty_paths_returns_empty_metrics(self) -> None:
        merged, metrics = consolidate_with_metrics([])
        assert merged == ""
        assert metrics.files_processed == 0
        assert metrics.tokens_before == 0
        assert metrics.tokens_after == 0


# ---------------------------------------------------------------------------
# CLI: compress metrics table
# ---------------------------------------------------------------------------


class TestCLICompressMetricsTable:
    def test_compress_output_flag_shows_metrics_table(self, tmp_path: Path) -> None:
        src = tmp_path / "CLAUDE.md"
        src.write_text(_SIMPLE_DOC)
        out = tmp_path / "out.sw.md"
        result = CliRunner().invoke(cli, ["compress", str(src), "--output", str(out)])
        assert result.exit_code == 0
        output_lower = result.output.lower()
        assert "token" in output_lower

    def test_compress_in_place_shows_metrics_table(self, tmp_path: Path) -> None:
        src = tmp_path / "CLAUDE.md"
        src.write_text(_SIMPLE_DOC)
        result = CliRunner().invoke(cli, ["compress", str(src), "--in-place"])
        assert result.exit_code == 0
        output_lower = result.output.lower()
        assert "token" in output_lower

    def test_compress_dry_run_shows_metrics_after_content(self, tmp_path: Path) -> None:
        src = tmp_path / "CLAUDE.md"
        src.write_text(_SIMPLE_DOC)
        result = CliRunner().invoke(cli, ["compress", str(src), "--dry-run"])
        assert result.exit_code == 0
        output = result.output
        # VTBF content must appear before the metrics table
        schema_pos = output.find("shrinkwrap_schema")
        token_pos = output.lower().find("token")
        assert schema_pos != -1
        assert token_pos != -1
        assert schema_pos < token_pos, "metrics table must appear after the VTBF content"

    def test_compress_metrics_shows_tokens_before(self, tmp_path: Path) -> None:
        src = tmp_path / "CLAUDE.md"
        src.write_text(_SIMPLE_DOC)
        out = tmp_path / "out.sw.md"
        result = CliRunner().invoke(cli, ["compress", str(src), "--output", str(out)])
        assert result.exit_code == 0
        assert "Before" in result.output or "before" in result.output.lower()

    def test_compress_metrics_shows_tokens_after(self, tmp_path: Path) -> None:
        src = tmp_path / "CLAUDE.md"
        src.write_text(_SIMPLE_DOC)
        out = tmp_path / "out.sw.md"
        result = CliRunner().invoke(cli, ["compress", str(src), "--output", str(out)])
        assert result.exit_code == 0
        assert "After" in result.output or "after" in result.output.lower()

    def test_compress_metrics_shows_savings(self, tmp_path: Path) -> None:
        src = tmp_path / "CLAUDE.md"
        src.write_text(_SIMPLE_DOC)
        out = tmp_path / "out.sw.md"
        result = CliRunner().invoke(cli, ["compress", str(src), "--output", str(out)])
        assert result.exit_code == 0
        assert "saved" in result.output.lower() or "saving" in result.output.lower()


# ---------------------------------------------------------------------------
# CLI: consolidate metrics table
# ---------------------------------------------------------------------------


class TestCLIConsolidateMetricsTable:
    def test_consolidate_shows_metrics_table(self, tmp_path: Path) -> None:
        (tmp_path / "CLAUDE.md").write_text("## Section A\n\n- item 1\n")
        (tmp_path / "AGENTS.md").write_text("## Section B\n\n- item 2\n")
        result = CliRunner().invoke(cli, ["consolidate", str(tmp_path)])
        assert result.exit_code == 0
        assert "token" in result.output.lower()

    def test_consolidate_dry_run_shows_metrics_table(self, tmp_path: Path) -> None:
        (tmp_path / "CLAUDE.md").write_text("## Section A\n\n- item 1\n")
        result = CliRunner().invoke(cli, ["consolidate", str(tmp_path), "--dry-run"])
        assert result.exit_code == 0
        assert "token" in result.output.lower()

    def test_consolidate_shows_files_processed(self, tmp_path: Path) -> None:
        (tmp_path / "CLAUDE.md").write_text("## Section A\n\n- item 1\n")
        (tmp_path / "AGENTS.md").write_text("## Section B\n\n- item 2\n")
        result = CliRunner().invoke(cli, ["consolidate", str(tmp_path)])
        assert result.exit_code == 0
        assert "files" in result.output.lower() or "Files" in result.output

    def test_consolidate_shows_sections_removed_count(self, tmp_path: Path) -> None:
        (tmp_path / "CLAUDE.md").write_text("## Security Rules\n\nNever commit secrets.\n")
        (tmp_path / "AGENTS.md").write_text("## Security Rules\n\nDo not do bad things.\n")
        result = CliRunner().invoke(cli, ["consolidate", str(tmp_path)])
        assert result.exit_code == 0
        assert "section" in result.output.lower()

    def test_consolidate_metrics_savings_pct(self, tmp_path: Path) -> None:
        (tmp_path / "CLAUDE.md").write_text("## Section A\n\n- shared\n- unique\n")
        (tmp_path / "AGENTS.md").write_text("## Section A\n\n- shared\n- other\n")
        result = CliRunner().invoke(cli, ["consolidate", str(tmp_path)])
        assert result.exit_code == 0
        # Some percentage sign should appear in the metrics output
        assert "%" in result.output
