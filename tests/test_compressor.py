"""Tests for compressor.py — normalize, condense, aggressive levels and idempotency."""

from __future__ import annotations

import pytest

from shrinkwrap.compressor import compress_document_sections, compress_section
from shrinkwrap.parser import Section


def make_section(
    heading: str = "Test",
    body: str = "content\n",
    classification: str = "mutable",
    compression: str = "normalize",
    level: int = 2,
) -> Section:
    return Section(
        heading=heading,
        level=level,
        body=body,
        classification=classification,  # type: ignore[arg-type]
        compression=compression,  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------------
# Immutable sections — never modified beyond whitespace normalization
# ---------------------------------------------------------------------------

class TestImmutableSections:
    def test_immutable_content_preserved_verbatim(self) -> None:
        body = "Never use eval().\n\nAlways validate input.\n"
        s = make_section(body=body, classification="immutable")
        result = compress_section(s)
        # Prose content must survive unchanged
        assert "Never use eval()" in result
        assert "Always validate input" in result

    def test_immutable_whitespace_normalized(self) -> None:
        body = "line one\n\n\n\nline two\n"
        s = make_section(body=body, classification="immutable")
        result = compress_section(s)
        # Multiple consecutive blank lines collapsed to one
        assert "\n\n\n" not in result

    def test_immutable_trailing_spaces_stripped(self) -> None:
        body = "line with trailing spaces   \nanother line  \n"
        s = make_section(body=body, classification="immutable")
        result = compress_section(s)
        for line in result.splitlines():
            assert line == line.rstrip()


# ---------------------------------------------------------------------------
# Normalize level
# ---------------------------------------------------------------------------

class TestNormalizeLevel:
    def test_normalize_strips_trailing_spaces(self) -> None:
        body = "line one   \nline two  \n"
        s = make_section(body=body, compression="normalize")
        result = compress_section(s)
        for line in result.splitlines():
            assert line == line.rstrip()

    def test_normalize_collapses_multiple_blank_lines(self) -> None:
        body = "para one\n\n\n\npara two\n"
        s = make_section(body=body, compression="normalize")
        result = compress_section(s)
        assert "\n\n\n" not in result

    def test_normalize_deduplicates_adjacent_identical_bullets(self) -> None:
        body = "- item a\n- item a\n- item b\n- item a\n"
        s = make_section(body=body, compression="normalize")
        result = compress_section(s)
        # Adjacent duplicate removed; non-adjacent kept
        lines = [ln for ln in result.splitlines() if ln.strip()]
        # "item a" should appear at most twice (first and last occurrences)
        item_a_count = sum(1 for ln in lines if "item a" in ln)
        assert item_a_count < 3

    def test_normalize_preserves_non_duplicate_bullets(self) -> None:
        body = "- alpha\n- beta\n- gamma\n"
        s = make_section(body=body, compression="normalize")
        result = compress_section(s)
        assert "alpha" in result
        assert "beta" in result
        assert "gamma" in result

    def test_normalize_output_smaller_than_or_equal_to_input(self) -> None:
        body = "  line one   \n\n\n  line two   \n"
        s = make_section(body=body, compression="normalize")
        assert len(compress_section(s)) <= len(body)


# ---------------------------------------------------------------------------
# Condense level
# ---------------------------------------------------------------------------

class TestCondenseLevel:
    def test_condense_includes_normalize(self) -> None:
        body = "line one   \n\n\n\nline two\n"
        s = make_section(body=body, compression="condense")
        result = compress_section(s)
        assert "\n\n\n" not in result

    def test_condense_removes_cross_section_duplicate_bullet(self) -> None:
        s1 = make_section(
            heading="A", body="- tests are passing\n- deploy done\n", compression="condense"
        )
        s2 = make_section(
            heading="B",
            body="- tests are passing\n- new feature added\n",
            compression="condense",
        )
        results = compress_document_sections([s1, s2])
        # "tests are passing" in both → keep only in the first occurrence
        count = sum(1 for r in results if "tests are passing" in r)
        assert count == 1

    def test_condense_output_shorter_than_normalize(self) -> None:
        # Duplicate content across sections means condense produces less text
        body = "- item x\n- item y\n- item x\n- item y\n- item z\n"
        s = make_section(body=body, compression="condense")
        norm = make_section(body=body, compression="normalize")
        assert len(compress_section(s)) <= len(compress_section(norm))


# ---------------------------------------------------------------------------
# Aggressive level — requires explicit opt-in; stubs tested for interface
# ---------------------------------------------------------------------------

class TestAggressiveLevel:
    def test_aggressive_requires_allow_lossy_flag(self) -> None:
        # compress_section with aggressive level without allow_lossy should raise
        s = make_section(compression="aggressive")
        with pytest.raises((ValueError, NotImplementedError)):
            compress_section(s)

    def test_aggressive_with_allow_lossy_returns_string(self) -> None:
        s = make_section(
            body="This is not important. Never use eval().\n", compression="aggressive"
        )
        result = compress_section(s, allow_lossy=True)
        assert isinstance(result, str)

    def test_aggressive_high_stakes_sentences_preserved(self) -> None:
        body = (
            "This sentence is filler content.\n"
            "Never use eval() in any context.\n"
            "More filler here.\n"
            "Do not commit secrets.\n"
            "Even more filler.\n"
        )
        s = make_section(body=body, compression="aggressive")
        result = compress_section(s, allow_lossy=True)
        assert "Never use eval()" in result
        assert "Do not commit secrets" in result

    def test_aggressive_smaller_than_condense(self) -> None:
        body = "\n".join(
            [f"This is filler sentence number {i}." for i in range(20)]
            + ["Never use eval() under any circumstances."]
        ) + "\n"
        s_agg = make_section(body=body, compression="aggressive")
        s_cond = make_section(body=body, compression="condense")
        result_agg = compress_section(s_agg, allow_lossy=True)
        result_cond = compress_section(s_cond)
        assert len(result_agg) <= len(result_cond)


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------

class TestIdempotency:
    @pytest.mark.parametrize("level", ["normalize", "condense"])
    def test_compress_is_idempotent(self, level: str) -> None:
        body = "  line one   \n\n\n- dup\n- dup\n- other\n"
        s = make_section(body=body, compression=level)  # type: ignore[arg-type]
        first_pass = compress_section(s)
        s2 = make_section(body=first_pass, compression=level)  # type: ignore[arg-type]
        second_pass = compress_section(s2)
        assert first_pass == second_pass
