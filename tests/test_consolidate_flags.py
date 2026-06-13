"""Failing tests for consolidate --level and --delete-sources flags (TDD Step 1)."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from shrinkwrap.cli import cli
from shrinkwrap.consolidate import consolidate_with_metrics

# ---------------------------------------------------------------------------
# Library: consolidate_with_metrics level parameter
# ---------------------------------------------------------------------------


class TestConsolidateWithMetricsLevel:
    def test_accepts_level_param(self, tmp_path: Path) -> None:
        f1 = tmp_path / "CLAUDE.md"
        f1.write_text("## Section A\n\n- item one\n- item two\n")
        merged, metrics = consolidate_with_metrics([f1], level="normalize")
        assert isinstance(merged, str)
        assert "Section A" in merged

    def test_level_none_is_default(self, tmp_path: Path) -> None:
        f1 = tmp_path / "CLAUDE.md"
        f1.write_text("## Section A\n\n- item one\n")
        merged_default, _ = consolidate_with_metrics([f1])
        merged_explicit, _ = consolidate_with_metrics([f1], level=None)
        assert merged_default == merged_explicit

    def test_level_condense_output_no_larger_than_no_level(self, tmp_path: Path) -> None:
        f1 = tmp_path / "CLAUDE.md"
        f1.write_text(
            "## Section A\n\n- shared bullet\n- unique to A\n\n"
            "## Section B\n\n- shared bullet\n- unique to B\n\n"
        )
        merged_no_level, _ = consolidate_with_metrics([f1])
        merged_condense, _ = consolidate_with_metrics([f1], level="condense")
        assert len(merged_condense) <= len(merged_no_level)

    def test_level_condense_cross_dedup_bullets(self, tmp_path: Path) -> None:
        """condense routes through compress pipeline which does cross-section bullet dedup."""
        f1 = tmp_path / "CLAUDE.md"
        f2 = tmp_path / "AGENTS.md"
        f1.write_text("## Section A\n\n- shared bullet\n- unique to A\n")
        f2.write_text("## Section B\n\n- shared bullet\n- unique to B\n")
        _, metrics = consolidate_with_metrics([f1, f2], level="condense")
        assert metrics.duplicate_bullets_removed >= 1

    def test_level_aggressive_without_allow_lossy_raises(self, tmp_path: Path) -> None:
        f1 = tmp_path / "CLAUDE.md"
        f1.write_text("## Section A\n\nSome descriptive prose goes here.\n")
        with pytest.raises(ValueError, match="aggressive"):
            consolidate_with_metrics([f1], level="aggressive")

    def test_level_aggressive_with_allow_lossy(self, tmp_path: Path) -> None:
        f1 = tmp_path / "CLAUDE.md"
        f1.write_text("## Section A\n\nSome descriptive prose goes here.\n")
        merged, metrics = consolidate_with_metrics([f1], level="aggressive", allow_lossy=True)
        assert isinstance(merged, str)
        assert isinstance(metrics.tokens_after, int)

    def test_level_condense_metrics_tokens_after_le_no_level(self, tmp_path: Path) -> None:
        f1 = tmp_path / "CLAUDE.md"
        f1.write_text(
            "## Section A\n\n- shared\n- unique A\n\n"
            "## Section B\n\n- shared\n- unique B\n\n"
        )
        _, m_default = consolidate_with_metrics([f1])
        _, m_condense = consolidate_with_metrics([f1], level="condense")
        assert m_condense.tokens_after <= m_default.tokens_after

    def test_level_immutable_sections_never_compressed(self, tmp_path: Path) -> None:
        """Sections classified immutable must survive --level unchanged."""
        f1 = tmp_path / "CLAUDE.md"
        f1.write_text(
            "<!-- shrinkwrap: immutable -->\n"
            "## Security Rules\n\n"
            "Never commit secrets.\n"
            "Never use eval().\n"
        )
        merged_none, _ = consolidate_with_metrics([f1])
        merged_agg, _ = consolidate_with_metrics([f1], level="aggressive", allow_lossy=True)
        # Immutable content must be identical regardless of level
        assert "Never commit secrets." in merged_agg
        assert "Never use eval()." in merged_agg

    def test_level_empty_paths_returns_empty(self) -> None:
        merged, metrics = consolidate_with_metrics([], level="condense")
        assert merged == ""
        assert metrics.tokens_before == 0


# ---------------------------------------------------------------------------
# CLI: --level flag
# ---------------------------------------------------------------------------


class TestCLIConsolidateLevelFlag:
    def test_level_flag_accepted(self, tmp_path: Path) -> None:
        (tmp_path / "CLAUDE.md").write_text("## Section A\n\n- item one\n")
        result = CliRunner().invoke(
            cli, ["consolidate", str(tmp_path), "--level", "condense"]
        )
        assert result.exit_code == 0

    def test_level_normalize_accepted(self, tmp_path: Path) -> None:
        (tmp_path / "CLAUDE.md").write_text("## Section A\n\n- item one\n")
        result = CliRunner().invoke(
            cli, ["consolidate", str(tmp_path), "--level", "normalize"]
        )
        assert result.exit_code == 0

    def test_level_invalid_value_rejected(self, tmp_path: Path) -> None:
        (tmp_path / "CLAUDE.md").write_text("## Section A\n\n- item one\n")
        result = CliRunner().invoke(
            cli, ["consolidate", str(tmp_path), "--level", "turbo"]
        )
        assert result.exit_code != 0

    def test_level_aggressive_without_allow_lossy_fails(self, tmp_path: Path) -> None:
        (tmp_path / "CLAUDE.md").write_text("## Section A\n\nSome prose.\n")
        result = CliRunner().invoke(
            cli, ["consolidate", str(tmp_path), "--level", "aggressive"]
        )
        assert result.exit_code != 0
        assert "allow-lossy" in result.output.lower()

    def test_level_aggressive_with_allow_lossy(self, tmp_path: Path) -> None:
        (tmp_path / "CLAUDE.md").write_text("## Section A\n\nSome prose.\n")
        result = CliRunner().invoke(
            cli,
            ["consolidate", str(tmp_path), "--level", "aggressive", "--allow-lossy"],
        )
        assert result.exit_code == 0

    def test_level_dry_run_combined(self, tmp_path: Path) -> None:
        (tmp_path / "CLAUDE.md").write_text("## Section A\n\n- item one\n")
        result = CliRunner().invoke(
            cli, ["consolidate", str(tmp_path), "--level", "condense", "--dry-run"]
        )
        assert result.exit_code == 0
        assert "Section A" in result.output


# ---------------------------------------------------------------------------
# CLI: --delete-sources flag
# ---------------------------------------------------------------------------


class TestCLIConsolidateDeleteSources:
    def test_delete_sources_removes_input_files(self, tmp_path: Path) -> None:
        f1 = tmp_path / "CLAUDE.md"
        f1.write_text("## Section A\n\n- item one\n")
        f2 = tmp_path / "AGENTS.md"
        f2.write_text("## Section B\n\n- item two\n")
        result = CliRunner().invoke(
            cli, ["consolidate", str(tmp_path), "--delete-sources"]
        )
        assert result.exit_code == 0
        assert not f1.exists()
        assert not f2.exists()

    def test_delete_sources_output_file_preserved(self, tmp_path: Path) -> None:
        """The output file must not be deleted even if it was a discovered source."""
        f1 = tmp_path / "CLAUDE.md"
        f1.write_text("## Section A\n\n- item one\n")
        out = tmp_path / "CONSOLIDATED.md"

        result = CliRunner().invoke(
            cli, ["consolidate", str(tmp_path), "--delete-sources"]
        )
        assert result.exit_code == 0
        assert not f1.exists()
        assert out.exists()

    def test_delete_sources_custom_output_preserved(self, tmp_path: Path) -> None:
        f1 = tmp_path / "CLAUDE.md"
        f1.write_text("## Section A\n\n- item one\n")
        custom = tmp_path / "MASTER.md"

        result = CliRunner().invoke(
            cli,
            ["consolidate", str(tmp_path), "--output", str(custom), "--delete-sources"],
        )
        assert result.exit_code == 0
        assert not f1.exists()
        assert custom.exists()

    def test_delete_sources_dry_run_does_not_delete(self, tmp_path: Path) -> None:
        f1 = tmp_path / "CLAUDE.md"
        f1.write_text("## Section A\n\n- item one\n")
        result = CliRunner().invoke(
            cli, ["consolidate", str(tmp_path), "--dry-run", "--delete-sources"]
        )
        assert result.exit_code == 0
        assert f1.exists()

    def test_delete_sources_output_mentions_deletion(self, tmp_path: Path) -> None:
        f1 = tmp_path / "CLAUDE.md"
        f1.write_text("## Section A\n\n- item one\n")
        result = CliRunner().invoke(
            cli, ["consolidate", str(tmp_path), "--delete-sources"]
        )
        assert result.exit_code == 0
        assert "delet" in result.output.lower()

    def test_delete_sources_no_files_found_exits_cleanly(self, tmp_path: Path) -> None:
        result = CliRunner().invoke(
            cli, ["consolidate", str(tmp_path), "--delete-sources"]
        )
        assert result.exit_code == 0

    def test_delete_sources_combined_with_level(self, tmp_path: Path) -> None:
        f1 = tmp_path / "CLAUDE.md"
        f1.write_text("## Section A\n\n- item one\n")
        result = CliRunner().invoke(
            cli,
            ["consolidate", str(tmp_path), "--level", "condense", "--delete-sources"],
        )
        assert result.exit_code == 0
        assert not f1.exists()
        assert (tmp_path / "CONSOLIDATED.md").exists()
