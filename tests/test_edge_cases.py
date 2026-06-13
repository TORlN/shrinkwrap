"""
Tests for edge cases: ambiguous sections treated as immutable, aggressive
compression requiring --allow-lossy, tilde fence protection in relevance
pruning, corrupt TOML warning, and drift_threshold clamping.
"""

from __future__ import annotations

import warnings
from pathlib import Path

import pytest
from click.testing import CliRunner

from shrinkwrap.cli import cli
from shrinkwrap.compressor import compress_document_sections, compress_section
from shrinkwrap.config import load_config
from shrinkwrap.parser import Section, parse
from shrinkwrap.schema import serialize, verify

# ---------------------------------------------------------------------------
# B2 — aggressive annotation without --allow-lossy must exit non-zero
# ---------------------------------------------------------------------------

_AGGRESSIVE_ANNOTATED = (
    "<!-- shrinkwrap: mutable compression=aggressive -->\n"
    "## Release Notes\n"
    "Some filler prose content.\n"
)


class TestAggressiveAnnotationRequiresAllowLossy:
    def test_aggressive_annotation_without_flag_exits_nonzero(
        self, tmp_path: Path
    ) -> None:
        src = tmp_path / "CLAUDE.md"
        src.write_text(_AGGRESSIVE_ANNOTATED)
        result = CliRunner().invoke(cli, ["compress", str(src)])
        assert result.exit_code != 0

    def test_aggressive_annotation_without_flag_shows_helpful_error(
        self, tmp_path: Path
    ) -> None:
        src = tmp_path / "CLAUDE.md"
        src.write_text(_AGGRESSIVE_ANNOTATED)
        result = CliRunner().invoke(cli, ["compress", str(src)])
        output = result.output.lower()
        assert "allow-lossy" in output or "aggressive" in output

    def test_aggressive_annotation_with_flag_succeeds(
        self, tmp_path: Path
    ) -> None:
        src = tmp_path / "CLAUDE.md"
        src.write_text(_AGGRESSIVE_ANNOTATED)
        result = CliRunner().invoke(cli, ["compress", str(src), "--allow-lossy"])
        assert result.exit_code == 0

    def test_aggressive_annotation_error_writes_no_output_file(
        self, tmp_path: Path
    ) -> None:
        src = tmp_path / "CLAUDE.md"
        src.write_text(_AGGRESSIVE_ANNOTATED)
        CliRunner().invoke(cli, ["compress", str(src)])
        assert not src.with_suffix(".sw.md").exists()

    def test_non_aggressive_annotation_without_flag_succeeds(
        self, tmp_path: Path
    ) -> None:
        src = tmp_path / "CLAUDE.md"
        src.write_text(
            "<!-- shrinkwrap: mutable compression=condense -->\n"
            "## Notes\nContent.\n"
        )
        result = CliRunner().invoke(cli, ["compress", str(src)])
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# B1 — ambiguous sections must be treated as immutable (normalize only)
# ---------------------------------------------------------------------------

def _make_ambiguous(body: str, compression: str = "normalize") -> Section:
    return Section(
        heading="Current Architecture Rules",
        level=2,
        body=body,
        classification="ambiguous",
        compression=compression,  # type: ignore[arg-type]
    )


class TestAmbiguousAsImmutable:
    def test_ambiguous_compress_section_preserves_prose_even_with_aggressive(
        self,
    ) -> None:
        """Ambiguous sections must not be pruned even when compression=aggressive."""
        body = "This sentence is filler.\nThis is also filler text.\n"
        result = compress_section(_make_ambiguous(body, "aggressive"), allow_lossy=True)
        assert "filler" in result

    def test_ambiguous_compress_section_does_not_prune_sentences_aggressive(
        self,
    ) -> None:
        """Compression of ambiguous must be normalize-only even when allow_lossy=True."""
        body = (
            "Context sentence one.\nContext sentence two.\nContext sentence three.\n"
        )
        result = compress_section(_make_ambiguous(body, "aggressive"), allow_lossy=True)
        assert "Context sentence one." in result
        assert "Context sentence two." in result
        assert "Context sentence three." in result

    def test_ambiguous_section_gets_checksum_in_vtbf(self) -> None:
        """Ambiguous sections must be checksummed in the VTBF output."""
        text = "## Current Architecture Rules\nImportant content.\n"
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            doc = parse(text)
        assert any(s.classification == "ambiguous" for s in doc.sections)
        vtbf = serialize(doc, "test.md", text)
        assert 'checksum="' in vtbf

    def test_ambiguous_section_verify_passes(self) -> None:
        """VTBF with an ambiguous section must verify clean."""
        text = "## Current Architecture Rules\nImportant content.\n"
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            doc = parse(text)
        vtbf = serialize(doc, "test.md", text)
        result = verify(vtbf)
        assert result.valid

    def test_ambiguous_section_checksum_mismatch_caught(self) -> None:
        """Tampering with an ambiguous section must fail verify."""
        text = "## Current Architecture Rules\nImportant content.\n"
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            doc = parse(text)
        vtbf = serialize(doc, "test.md", text)
        tampered = vtbf.replace("Important content.", "Tampered content.")
        result = verify(tampered)
        assert not result.valid

    def test_ambiguous_excluded_from_cross_section_dedup(self) -> None:
        """Ambiguous section bullets must survive even when they appear after a mutable
        section that already contains the same bullet."""
        s_mut = Section(
            heading="Status",
            level=2,
            body="- shared bullet\n- unique\n",
            classification="mutable",
            compression="condense",
        )
        s_amb = Section(
            heading="Arch Rules",
            level=2,
            body="- shared bullet\n",
            classification="ambiguous",
            compression="condense",
        )
        results = compress_document_sections([s_mut, s_amb])
        # Ambiguous section is second; dedup must NOT strip its bullet.
        assert "shared bullet" in results[1]


# ---------------------------------------------------------------------------
# B4 — aggressive mode must protect ~~~ fences, not just ``` fences
# ---------------------------------------------------------------------------

class TestTildeFenceProtection:
    def test_aggressive_preserves_tilde_fence_content(self) -> None:
        body = "~~~python\nsome_function()\n~~~\n"
        s = Section(
            heading="Example",
            level=2,
            body=body,
            classification="mutable",
            compression="aggressive",
        )
        result = compress_section(s, allow_lossy=True)
        assert "some_function()" in result

    def test_aggressive_preserves_both_fence_styles(self) -> None:
        body = "```python\nfunc_a()\n```\n~~~\nfunc_b()\n~~~\n"
        s = Section(
            heading="Example",
            level=2,
            body=body,
            classification="mutable",
            compression="aggressive",
        )
        result = compress_section(s, allow_lossy=True)
        assert "func_a()" in result
        assert "func_b()" in result

    def test_aggressive_still_drops_prose_outside_fences(self) -> None:
        body = "Filler sentence outside the fence.\n~~~\ncode()\n~~~\n"
        s = Section(
            heading="Example",
            level=2,
            body=body,
            classification="mutable",
            compression="aggressive",
        )
        result = compress_section(s, allow_lossy=True)
        assert "code()" in result
        assert "Filler sentence" not in result


# ---------------------------------------------------------------------------
# S1 — corrupt shrinkwrap.toml must emit a warning, not silently use defaults
# ---------------------------------------------------------------------------

class TestCorruptTomlWarning:
    def test_corrupt_toml_emits_warning(self, tmp_path: Path) -> None:
        (tmp_path / "shrinkwrap.toml").write_text("[[[invalid toml")
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            load_config(tmp_path)
        assert len(caught) > 0

    def test_corrupt_toml_warning_mentions_toml_or_config(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "shrinkwrap.toml").write_text("[[[invalid toml")
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            load_config(tmp_path)
        text = " ".join(str(w.message) for w in caught).lower()
        assert "toml" in text or "config" in text or "shrinkwrap" in text

    def test_corrupt_toml_still_returns_defaults(self, tmp_path: Path) -> None:
        (tmp_path / "shrinkwrap.toml").write_text("[[[invalid toml")
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            cfg = load_config(tmp_path)
        assert cfg.default_level is None
        assert cfg.default_profile == "claude"

    def test_valid_toml_emits_no_warning(self, tmp_path: Path) -> None:
        (tmp_path / "shrinkwrap.toml").write_text(
            '[shrinkwrap]\ndefault_level = "condense"\n'
        )
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            load_config(tmp_path)
        assert len(caught) == 0


# ---------------------------------------------------------------------------
# S2 — drift_threshold must be clamped to [0.0, 1.0]
# ---------------------------------------------------------------------------

class TestDriftThresholdClamping:
    def test_threshold_above_one_clamped_to_one(self, tmp_path: Path) -> None:
        (tmp_path / "shrinkwrap.toml").write_text(
            "[shrinkwrap]\ndrift_threshold = 5.0\n"
        )
        cfg = load_config(tmp_path)
        assert cfg.drift_threshold <= 1.0

    def test_threshold_below_zero_clamped_to_zero(self, tmp_path: Path) -> None:
        (tmp_path / "shrinkwrap.toml").write_text(
            "[shrinkwrap]\ndrift_threshold = -0.5\n"
        )
        cfg = load_config(tmp_path)
        assert cfg.drift_threshold >= 0.0

    def test_valid_threshold_unchanged(self, tmp_path: Path) -> None:
        (tmp_path / "shrinkwrap.toml").write_text(
            "[shrinkwrap]\ndrift_threshold = 0.6\n"
        )
        cfg = load_config(tmp_path)
        assert cfg.drift_threshold == pytest.approx(0.6)

    def test_boundary_zero_accepted(self, tmp_path: Path) -> None:
        (tmp_path / "shrinkwrap.toml").write_text(
            "[shrinkwrap]\ndrift_threshold = 0.0\n"
        )
        cfg = load_config(tmp_path)
        assert cfg.drift_threshold == pytest.approx(0.0)

    def test_boundary_one_accepted(self, tmp_path: Path) -> None:
        (tmp_path / "shrinkwrap.toml").write_text(
            "[shrinkwrap]\ndrift_threshold = 1.0\n"
        )
        cfg = load_config(tmp_path)
        assert cfg.drift_threshold == pytest.approx(1.0)
