"""CLI integration tests — RED until commands are fully wired."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from shrinkwrap.cli import cli

SAMPLE_MD = """\
---
shrinkwrap:
  immutable_sections:
    - Security Rules
---

<!-- shrinkwrap: immutable -->
## Security Rules
Never use eval().
Always validate input.

## Current Status
- tests passing
- deploy pending
"""


@pytest.fixture()
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture()
def sample_file(tmp_path: Path) -> Path:
    p = tmp_path / "CLAUDE.md"
    p.write_text(SAMPLE_MD)
    return p


# ---------------------------------------------------------------------------
# compress command
# ---------------------------------------------------------------------------


class TestCompressCommand:
    def test_compress_exits_zero(self, runner: CliRunner, sample_file: Path) -> None:
        result = runner.invoke(cli, ["compress", str(sample_file)])
        assert result.exit_code == 0, result.output

    def test_compress_creates_output_file(self, runner: CliRunner, sample_file: Path) -> None:
        runner.invoke(cli, ["compress", str(sample_file)])
        out = sample_file.with_suffix(".sw.md")
        assert out.exists()

    def test_compress_output_has_vtbf_front_matter(
        self, runner: CliRunner, sample_file: Path
    ) -> None:
        runner.invoke(cli, ["compress", str(sample_file)])
        out = sample_file.with_suffix(".sw.md").read_text()
        assert "shrinkwrap_schema" in out

    def test_compress_custom_output_path(
        self, runner: CliRunner, sample_file: Path, tmp_path: Path
    ) -> None:
        out = tmp_path / "custom.sw.md"
        result = runner.invoke(cli, ["compress", str(sample_file), "-o", str(out)])
        assert result.exit_code == 0
        assert out.exists()

    def test_compress_condense_level(self, runner: CliRunner, sample_file: Path) -> None:
        runner.invoke(cli, ["compress", str(sample_file), "--level", "condense"])
        out = sample_file.with_suffix(".sw.md").read_text()
        assert 'compression="condense"' in out

    def test_compress_aggressive_without_allow_lossy_fails(
        self, runner: CliRunner, sample_file: Path
    ) -> None:
        result = runner.invoke(cli, ["compress", str(sample_file), "--level", "aggressive"])
        assert result.exit_code != 0

    def test_compress_aggressive_with_allow_lossy_succeeds(
        self, runner: CliRunner, sample_file: Path
    ) -> None:
        result = runner.invoke(
            cli, ["compress", str(sample_file), "--level", "aggressive", "--allow-lossy"]
        )
        assert result.exit_code == 0

    def test_compress_cursor_profile_omits_front_matter(
        self, runner: CliRunner, sample_file: Path
    ) -> None:
        runner.invoke(cli, ["compress", str(sample_file), "--profile", "cursor"])
        out = sample_file.with_suffix(".sw.md").read_text()
        assert "shrinkwrap_schema" not in out

    def test_compress_generic_profile_omits_all_tags(
        self, runner: CliRunner, sample_file: Path
    ) -> None:
        runner.invoke(cli, ["compress", str(sample_file), "--profile", "generic"])
        out = sample_file.with_suffix(".sw.md").read_text()
        assert "sw:section" not in out
        assert "shrinkwrap_schema" not in out

    def test_compress_immutable_content_preserved(
        self, runner: CliRunner, sample_file: Path
    ) -> None:
        runner.invoke(cli, ["compress", str(sample_file)])
        out = sample_file.with_suffix(".sw.md").read_text()
        assert "Never use eval()" in out
        assert "Always validate input" in out

    def test_compress_prints_ratio(self, runner: CliRunner, sample_file: Path) -> None:
        result = runner.invoke(cli, ["compress", str(sample_file)])
        assert "%" in result.output or "ratio" in result.output.lower()


# ---------------------------------------------------------------------------
# verify command
# ---------------------------------------------------------------------------


class TestVerifyCommand:
    def _compressed(self, runner: CliRunner, sample_file: Path) -> Path:
        runner.invoke(cli, ["compress", str(sample_file)])
        return sample_file.with_suffix(".sw.md")

    def test_verify_valid_exits_zero(self, runner: CliRunner, sample_file: Path) -> None:
        vtbf = self._compressed(runner, sample_file)
        result = runner.invoke(cli, ["verify", str(vtbf)])
        assert result.exit_code == 0

    def test_verify_tampered_immutable_exits_nonzero(
        self, runner: CliRunner, sample_file: Path
    ) -> None:
        vtbf = self._compressed(runner, sample_file)
        content = vtbf.read_text()
        tampered = content.replace("Never use eval().", "Always use eval().")
        vtbf.write_text(tampered)
        result = runner.invoke(cli, ["verify", str(vtbf)])
        assert result.exit_code != 0

    def test_verify_non_vtbf_file_exits_nonzero(self, runner: CliRunner, sample_file: Path) -> None:
        result = runner.invoke(cli, ["verify", str(sample_file)])
        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# expand command
# ---------------------------------------------------------------------------


class TestExpandCommand:
    def _compressed(self, runner: CliRunner, sample_file: Path) -> Path:
        runner.invoke(cli, ["compress", str(sample_file)])
        return sample_file.with_suffix(".sw.md")

    def test_expand_exits_zero(self, runner: CliRunner, sample_file: Path) -> None:
        vtbf = self._compressed(runner, sample_file)
        result = runner.invoke(cli, ["expand", str(vtbf)])
        assert result.exit_code == 0, result.output

    def test_expand_creates_output_file(self, runner: CliRunner, sample_file: Path) -> None:
        vtbf = self._compressed(runner, sample_file)
        runner.invoke(cli, ["expand", str(vtbf)])
        out = vtbf.with_suffix("").with_suffix("")  # strip .sw.md → original name
        # also accept <name>.expanded.md
        expanded = vtbf.parent / (vtbf.stem.replace(".sw", "") + ".expanded.md")
        assert (
            expanded.exists()
            or out.exists()
            or any(
                f.name.endswith(".expanded.md") or f.name.endswith(".md")
                for f in vtbf.parent.iterdir()
                if f != vtbf and f != sample_file
            )
        )

    def test_expand_output_contains_section_headings(
        self, runner: CliRunner, sample_file: Path, tmp_path: Path
    ) -> None:
        vtbf = self._compressed(runner, sample_file)
        out = tmp_path / "expanded.md"
        runner.invoke(cli, ["expand", str(vtbf), "-o", str(out)])
        text = out.read_text()
        assert "## Security Rules" in text
        assert "## Current Status" in text

    def test_expand_output_has_no_vtbf_tags(
        self, runner: CliRunner, sample_file: Path, tmp_path: Path
    ) -> None:
        vtbf = self._compressed(runner, sample_file)
        out = tmp_path / "expanded.md"
        runner.invoke(cli, ["expand", str(vtbf), "-o", str(out)])
        text = out.read_text()
        assert "sw:section" not in text
        assert "shrinkwrap_schema" not in text

    def test_expand_output_has_no_front_matter(
        self, runner: CliRunner, sample_file: Path, tmp_path: Path
    ) -> None:
        vtbf = self._compressed(runner, sample_file)
        out = tmp_path / "expanded.md"
        runner.invoke(cli, ["expand", str(vtbf), "-o", str(out)])
        text = out.read_text()
        assert not text.startswith("---")

    def test_expand_preserves_immutable_content(
        self, runner: CliRunner, sample_file: Path, tmp_path: Path
    ) -> None:
        vtbf = self._compressed(runner, sample_file)
        out = tmp_path / "expanded.md"
        runner.invoke(cli, ["expand", str(vtbf), "-o", str(out)])
        text = out.read_text()
        assert "Never use eval()" in text


# ---------------------------------------------------------------------------
# audit command
# ---------------------------------------------------------------------------


class TestAuditCommand:
    def test_audit_exits_zero(self, runner: CliRunner, sample_file: Path) -> None:
        result = runner.invoke(cli, ["audit", str(sample_file)])
        assert result.exit_code == 0

    def test_audit_lists_sections(self, runner: CliRunner, sample_file: Path) -> None:
        result = runner.invoke(cli, ["audit", str(sample_file)])
        assert "Security Rules" in result.output
        assert "Current Status" in result.output

    def test_audit_shows_classification(self, runner: CliRunner, sample_file: Path) -> None:
        result = runner.invoke(cli, ["audit", str(sample_file)])
        assert "immutable" in result.output
        assert "mutable" in result.output
