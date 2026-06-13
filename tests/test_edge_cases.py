"""
Tests for edge cases: ambiguous sections treated as immutable, aggressive
compression requiring --allow-lossy, tilde fence protection in relevance
pruning, corrupt TOML warning, drift_threshold clamping, non-UTF-8 file
handling, section-id edge cases, and watch-loop error recovery.
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
    def test_aggressive_annotation_without_flag_exits_nonzero(self, tmp_path: Path) -> None:
        src = tmp_path / "CLAUDE.md"
        src.write_text(_AGGRESSIVE_ANNOTATED)
        result = CliRunner().invoke(cli, ["compress", str(src)])
        assert result.exit_code != 0

    def test_aggressive_annotation_without_flag_shows_helpful_error(self, tmp_path: Path) -> None:
        src = tmp_path / "CLAUDE.md"
        src.write_text(_AGGRESSIVE_ANNOTATED)
        result = CliRunner().invoke(cli, ["compress", str(src)])
        output = result.output.lower()
        assert "allow-lossy" in output or "aggressive" in output

    def test_aggressive_annotation_with_flag_succeeds(self, tmp_path: Path) -> None:
        src = tmp_path / "CLAUDE.md"
        src.write_text(_AGGRESSIVE_ANNOTATED)
        result = CliRunner().invoke(cli, ["compress", str(src), "--allow-lossy"])
        assert result.exit_code == 0

    def test_aggressive_annotation_error_writes_no_output_file(self, tmp_path: Path) -> None:
        src = tmp_path / "CLAUDE.md"
        src.write_text(_AGGRESSIVE_ANNOTATED)
        CliRunner().invoke(cli, ["compress", str(src)])
        assert not src.with_suffix(".sw.md").exists()

    def test_non_aggressive_annotation_without_flag_succeeds(self, tmp_path: Path) -> None:
        src = tmp_path / "CLAUDE.md"
        src.write_text("<!-- shrinkwrap: mutable compression=condense -->\n## Notes\nContent.\n")
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
        body = "Context sentence one.\nContext sentence two.\nContext sentence three.\n"
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

    def test_corrupt_toml_warning_mentions_toml_or_config(self, tmp_path: Path) -> None:
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
        (tmp_path / "shrinkwrap.toml").write_text('[shrinkwrap]\ndefault_level = "condense"\n')
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            load_config(tmp_path)
        assert len(caught) == 0


# ---------------------------------------------------------------------------
# S2 — drift_threshold must be clamped to [0.0, 1.0]
# ---------------------------------------------------------------------------


class TestDriftThresholdClamping:
    def test_threshold_above_one_clamped_to_one(self, tmp_path: Path) -> None:
        (tmp_path / "shrinkwrap.toml").write_text("[shrinkwrap]\ndrift_threshold = 5.0\n")
        cfg = load_config(tmp_path)
        assert cfg.drift_threshold <= 1.0

    def test_threshold_below_zero_clamped_to_zero(self, tmp_path: Path) -> None:
        (tmp_path / "shrinkwrap.toml").write_text("[shrinkwrap]\ndrift_threshold = -0.5\n")
        cfg = load_config(tmp_path)
        assert cfg.drift_threshold >= 0.0

    def test_valid_threshold_unchanged(self, tmp_path: Path) -> None:
        (tmp_path / "shrinkwrap.toml").write_text("[shrinkwrap]\ndrift_threshold = 0.6\n")
        cfg = load_config(tmp_path)
        assert cfg.drift_threshold == pytest.approx(0.6)

    def test_boundary_zero_accepted(self, tmp_path: Path) -> None:
        (tmp_path / "shrinkwrap.toml").write_text("[shrinkwrap]\ndrift_threshold = 0.0\n")
        cfg = load_config(tmp_path)
        assert cfg.drift_threshold == pytest.approx(0.0)

    def test_boundary_one_accepted(self, tmp_path: Path) -> None:
        (tmp_path / "shrinkwrap.toml").write_text("[shrinkwrap]\ndrift_threshold = 1.0\n")
        cfg = load_config(tmp_path)
        assert cfg.drift_threshold == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Non-UTF-8 file handling — _read_text() must exit cleanly
# ---------------------------------------------------------------------------

# Bytes that are valid Latin-1 but not valid UTF-8
_INVALID_UTF8 = b"## Section\nsome content\n\x80\x81invalid bytes\n"


class TestNonUtf8FileHandling:
    def test_compress_non_utf8_exits_nonzero(self, tmp_path: Path) -> None:
        src = tmp_path / "CLAUDE.md"
        src.write_bytes(_INVALID_UTF8)
        result = CliRunner().invoke(cli, ["compress", str(src)])
        assert result.exit_code != 0

    def test_compress_non_utf8_shows_encoding_error(self, tmp_path: Path) -> None:
        src = tmp_path / "CLAUDE.md"
        src.write_bytes(_INVALID_UTF8)
        result = CliRunner().invoke(cli, ["compress", str(src)])
        output = result.output.lower()
        assert "utf" in output or "encoding" in output or "error" in output

    def test_compress_non_utf8_writes_no_output_file(self, tmp_path: Path) -> None:
        src = tmp_path / "CLAUDE.md"
        src.write_bytes(_INVALID_UTF8)
        CliRunner().invoke(cli, ["compress", str(src)])
        assert not src.with_suffix(".sw.md").exists()

    def test_expand_non_utf8_exits_nonzero(self, tmp_path: Path) -> None:
        src = tmp_path / "CLAUDE.sw.md"
        src.write_bytes(_INVALID_UTF8)
        result = CliRunner().invoke(cli, ["expand", str(src)])
        assert result.exit_code != 0

    def test_stats_non_utf8_exits_nonzero(self, tmp_path: Path) -> None:
        src = tmp_path / "CLAUDE.md"
        src.write_bytes(_INVALID_UTF8)
        result = CliRunner().invoke(cli, ["stats", str(src)])
        assert result.exit_code != 0

    def test_audit_non_utf8_exits_nonzero(self, tmp_path: Path) -> None:
        src = tmp_path / "CLAUDE.md"
        src.write_bytes(_INVALID_UTF8)
        result = CliRunner().invoke(cli, ["audit", str(src)])
        assert result.exit_code != 0

    def test_valid_utf8_file_still_compresses_normally(self, tmp_path: Path) -> None:
        src = tmp_path / "CLAUDE.md"
        src.write_text("## Status\n- all good\n", encoding="utf-8")
        result = CliRunner().invoke(cli, ["compress", str(src)])
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# _section_id edge cases — empty heading must not produce empty ID
# ---------------------------------------------------------------------------


class TestSectionIdEdgeCases:
    def test_all_symbol_heading_returns_nonempty_id(self) -> None:
        from shrinkwrap.schema import _section_id

        result = _section_id("---")
        assert result, "_section_id must never return an empty string"

    def test_all_symbol_heading_returns_fallback(self) -> None:
        from shrinkwrap.schema import _section_id

        assert _section_id("---") == "section"

    def test_all_symbol_heading_with_spaces_returns_fallback(self) -> None:
        from shrinkwrap.schema import _section_id

        assert _section_id("!!! ???") == "section"

    def test_normal_heading_still_works(self) -> None:
        from shrinkwrap.schema import _section_id

        assert _section_id("Security Rules") == "security-rules"

    def test_mixed_heading_strips_leading_trailing_dashes(self) -> None:
        from shrinkwrap.schema import _section_id

        result = _section_id("!Status!")
        assert not result.startswith("-")
        assert not result.endswith("-")

    def test_duplicate_headings_get_unique_ids(self, tmp_path: Path) -> None:
        """Two sections with the same heading must get distinct IDs in the VTBF output."""
        src = tmp_path / "CLAUDE.md"
        src.write_text("## Notes\ncontent a\n\n## Notes\ncontent b\n")
        result = CliRunner().invoke(cli, ["compress", str(src)])
        assert result.exit_code == 0
        vtbf = src.with_suffix(".sw.md").read_text()
        import re

        ids = re.findall(r'id="([^"]+)"', vtbf)
        assert len(ids) == len(set(ids)), f"Duplicate section IDs found: {ids}"


# ---------------------------------------------------------------------------
# Watch-loop error recovery — must not crash on aggressive or bad files
# ---------------------------------------------------------------------------


class TestWatchLoopErrorRecovery:
    def test_watch_loop_survives_aggressive_without_allow_lossy(self, tmp_path: Path) -> None:
        """
        A file annotated with compression=aggressive must not crash the watch loop
        when allow_lossy=False. The loop must catch the ValueError and continue.
        """
        import threading
        import time

        from shrinkwrap.cli import _watch_loop

        src = tmp_path / "CLAUDE.md"
        src.write_text(
            "<!-- shrinkwrap: mutable compression=aggressive -->\n## Notes\nSome content.\n"
        )

        stop = threading.Event()
        raised: list[Exception] = []

        def run() -> None:
            try:
                _watch_loop(
                    src,
                    level=None,
                    profile=None,
                    allow_lossy=False,
                    interval=0.05,
                    stop_event=stop,
                )
            except Exception as exc:
                raised.append(exc)

        t = threading.Thread(target=run, daemon=True)
        t.start()
        time.sleep(0.02)

        # Trigger a change
        src.write_text(
            "<!-- shrinkwrap: mutable compression=aggressive -->\n## Notes\nUpdated content.\n"
        )
        time.sleep(0.20)  # two full poll cycles at 0.05 s interval
        stop.set()
        t.join(timeout=1.0)

        assert not raised, f"_watch_loop raised an exception: {raised[0]}"

    def test_watch_loop_survives_read_error(self, tmp_path: Path) -> None:
        """A file that becomes unreadable mid-watch must not crash the loop."""
        import threading
        import time

        from shrinkwrap.cli import _watch_loop

        src = tmp_path / "CLAUDE.md"
        src.write_text("## Notes\nContent.\n")

        stop = threading.Event()
        raised: list[Exception] = []

        def run() -> None:
            try:
                _watch_loop(
                    src,
                    level=None,
                    profile=None,
                    allow_lossy=False,
                    interval=0.05,
                    stop_event=stop,
                )
            except Exception as exc:
                raised.append(exc)

        t = threading.Thread(target=run, daemon=True)
        t.start()
        time.sleep(0.02)

        # Replace the file with invalid UTF-8 to trigger a read error
        src.write_bytes(b"## Notes\n\xff\xfe invalid\n")
        time.sleep(0.20)
        stop.set()
        t.join(timeout=1.0)

        assert not raised, f"_watch_loop raised on bad file: {raised[0]}"
