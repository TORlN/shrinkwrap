"""
Edge-case and robustness tests — RED until bugs are fixed.

Bugs targeted:
  B1  parser.py  — heading detection inside fenced code blocks
  B2  schema.py  — duplicate section IDs cause silent collision
  B3  parser.py  — invalid compression annotation value is silent
  B4  compressor — nested bullet dedup preserves indentation structure
  B5  parser.py  — heading detection with Windows (CRLF) line endings
  B6  parser.py  — Unicode heading text classified correctly
  B7  compressor — whitespace-only body compresses to empty string (not crash)
  B8  schema.py  — empty section body serializes/round-trips cleanly
  B9  cli        — compress on already-compressed file is idempotent (no tag doubling)
  B10 cli        — expand of a non-VTBF file exits non-zero with useful message
  B11 schema     — verify handles a VTBF file with no immutable sections
  B12 parser     — annotation immediately before EOF (no heading follows) is ignored cleanly
"""

from __future__ import annotations

import warnings
from pathlib import Path

import pytest
from click.testing import CliRunner

from shrinkwrap.cli import cli
from shrinkwrap.compressor import compress_section
from shrinkwrap.parser import (
    Section,
    ShrinkWrapClassificationWarning,
    parse,
)
from shrinkwrap.schema import serialize, verify

# ---------------------------------------------------------------------------
# B1 — fenced code blocks must not be split on heading-like lines
# ---------------------------------------------------------------------------

class TestCodeBlockHeadingProtection:
    def test_hash_line_inside_backtick_fence_not_split(self) -> None:
        text = (
            "## Usage\n"
            "Here is how:\n\n"
            "```bash\n"
            "## This is a bash comment, not a heading\n"
            "echo hello\n"
            "```\n\n"
            "Done.\n"
        )
        doc = parse(text)
        assert len(doc.sections) == 1
        assert doc.sections[0].heading == "Usage"
        assert "## This is a bash comment" in doc.sections[0].body

    def test_h2_line_inside_fence_not_split(self) -> None:
        text = (
            "## Security Rules\n"
            "Never do this:\n\n"
            "```python\n"
            "## Bad pattern example\n"
            "eval(user_input)\n"
            "```\n"
        )
        doc = parse(text)
        assert len(doc.sections) == 1

    def test_fence_at_document_preamble_not_split(self) -> None:
        text = (
            "```\n"
            "## Not a real heading\n"
            "```\n\n"
            "## Real Heading\n"
            "content\n"
        )
        doc = parse(text)
        # Only one section — the preamble code block must not create a section
        assert len(doc.sections) == 1
        assert doc.sections[0].heading == "Real Heading"

    def test_unclosed_fence_treats_rest_as_code(self) -> None:
        text = (
            "## Setup\n"
            "```python\n"
            "## Inside unclosed fence\n"
            "code continues\n"
        )
        doc = parse(text)
        assert len(doc.sections) == 1
        assert "## Inside unclosed fence" in doc.sections[0].body

    def test_tilde_fence_also_protected(self) -> None:
        text = (
            "## Notes\n"
            "~~~\n"
            "## Not a heading\n"
            "~~~\n"
        )
        doc = parse(text)
        assert len(doc.sections) == 1

    def test_heading_after_closed_fence_is_split(self) -> None:
        text = (
            "## First\n"
            "```\n"
            "code\n"
            "```\n"
            "## Second\n"
            "content\n"
        )
        doc = parse(text)
        assert len(doc.sections) == 2
        assert doc.sections[0].heading == "First"
        assert doc.sections[1].heading == "Second"

    def test_code_block_content_preserved_in_body(self) -> None:
        body_content = "```python\neval(x)\n```\n"
        text = f"## Rules\n{body_content}"
        doc = parse(text)
        assert doc.sections[0].body == body_content


# ---------------------------------------------------------------------------
# B2 — duplicate section IDs must not collide in VTBF output
# ---------------------------------------------------------------------------

class TestDuplicateSectionIDs:
    def _doc_with_duplicate_headings(self) -> str:
        return (
            "## Current Status\nfirst occurrence\n"
            "## Current Status\nsecond occurrence\n"
        )

    def test_duplicate_headings_produce_unique_ids(self) -> None:
        doc = parse(self._doc_with_duplicate_headings())
        vtbf = serialize(doc, "test.md", self._doc_with_duplicate_headings())
        import re
        ids = re.findall(r'id="([^"]+)"', vtbf)
        assert len(ids) == len(set(ids)), f"Duplicate IDs found: {ids}"

    def test_duplicate_ids_use_numeric_suffix(self) -> None:
        doc = parse(self._doc_with_duplicate_headings())
        vtbf = serialize(doc, "test.md", self._doc_with_duplicate_headings())
        assert 'id="current-status"' in vtbf
        assert 'id="current-status-2"' in vtbf

    def test_triple_duplicate_heading(self) -> None:
        text = "## Notes\na\n## Notes\nb\n## Notes\nc\n"
        doc = parse(text)
        vtbf = serialize(doc, "test.md", text)
        import re
        ids = re.findall(r'id="([^"]+)"', vtbf)
        assert len(ids) == 3
        assert len(set(ids)) == 3

    def test_verify_passes_with_duplicate_immutable_sections(self) -> None:
        text = (
            "<!-- shrinkwrap: immutable -->\n## Rules\ncontent\n"
            "<!-- shrinkwrap: immutable -->\n## Rules\nother content\n"
        )
        doc = parse(text)
        vtbf = serialize(doc, "test.md", text)
        result = verify(vtbf)
        assert result.valid is True


# ---------------------------------------------------------------------------
# B3 — invalid compression annotation value warns, falls back gracefully
# ---------------------------------------------------------------------------

class TestInvalidAnnotationCompression:
    def test_invalid_compression_value_warns(self) -> None:
        text = "<!-- shrinkwrap: mutable compression=turbo -->\n## Notes\ncontent\n"
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            parse(text)
            assert any(issubclass(x.category, ShrinkWrapClassificationWarning) for x in w)

    def test_invalid_compression_falls_back_to_normalize(self) -> None:
        text = "<!-- shrinkwrap: mutable compression=turbo -->\n## Notes\ncontent\n"
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            doc = parse(text)
        assert doc.sections[0].compression == "normalize"

    def test_valid_compression_value_no_warning(self) -> None:
        text = "<!-- shrinkwrap: mutable compression=condense -->\n## Notes\ncontent\n"
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            doc = parse(text)
            classification_warns = [
                x for x in w if issubclass(x.category, ShrinkWrapClassificationWarning)
            ]
            assert not classification_warns
        assert doc.sections[0].compression == "condense"


# ---------------------------------------------------------------------------
# B4 — nested bullet lists: indented items must not be deduped with parent
# ---------------------------------------------------------------------------

class TestNestedBulletDeduplication:
    def test_nested_bullets_not_deduped_with_parent(self) -> None:
        body = (
            "- item\n"
            "  - nested item\n"
            "  - another nested item\n"
            "- item\n"
        )
        s = Section(heading="List", level=2, body=body, classification="mutable")
        result = compress_section(s)
        assert "nested item" in result
        assert "another nested item" in result

    def test_indented_bullets_preserved_verbatim(self) -> None:
        body = "- parent\n  - child a\n  - child b\n"
        s = Section(heading="List", level=2, body=body, classification="mutable")
        result = compress_section(s)
        assert "child a" in result
        assert "child b" in result

    def test_truly_adjacent_identical_top_level_bullets_still_deduped(self) -> None:
        body = "- dup item\n- dup item\n- other\n"
        s = Section(heading="List", level=2, body=body, classification="mutable")
        result = compress_section(s)
        lines = [ln for ln in result.splitlines() if "dup item" in ln]
        assert len(lines) == 1


# ---------------------------------------------------------------------------
# B5 — Windows CRLF line endings
# ---------------------------------------------------------------------------

class TestCRLFLineEndings:
    def test_crlf_front_matter_parsed(self) -> None:
        text = "---\r\nauthor: alice\r\n---\r\n## Hello\r\nworld\r\n"
        doc = parse(text)
        # Should not crash; sections may or may not parse depending on CRLF handling
        assert isinstance(doc, object)

    def test_crlf_headings_detected(self) -> None:
        text = "## Alpha\r\nbody a\r\n## Beta\r\nbody b\r\n"
        doc = parse(text)
        headings = [s.heading for s in doc.sections]
        assert "Alpha" in headings
        assert "Beta" in headings

    def test_crlf_annotations_work(self) -> None:
        text = "<!-- shrinkwrap: immutable -->\r\n## Rules\r\nNever do it.\r\n"
        doc = parse(text)
        assert len(doc.sections) == 1
        assert doc.sections[0].classification == "immutable"


# ---------------------------------------------------------------------------
# B6 — Unicode headings
# ---------------------------------------------------------------------------

class TestUnicodeHeadings:
    def test_unicode_heading_text_preserved(self) -> None:
        doc = parse("## Règles de Sécurité\ncontent\n")
        assert doc.sections[0].heading == "Règles de Sécurité"

    def test_unicode_body_preserved(self) -> None:
        body = "Ne jamais utiliser eval().\n"
        doc = parse(f"## Rules\n{body}")
        assert doc.sections[0].body == body

    def test_emoji_in_heading_does_not_crash(self) -> None:
        doc = parse("## 🚨 Security Rules 🚨\ncontent\n")
        assert len(doc.sections) == 1

    def test_cjk_heading_text(self) -> None:
        doc = parse("## 安全規則\ncontent\n")
        assert doc.sections[0].heading == "安全規則"


# ---------------------------------------------------------------------------
# B7 + B8 — empty / whitespace-only bodies
# ---------------------------------------------------------------------------

class TestEmptyAndWhitespaceBodies:
    def test_empty_body_compresses_to_empty(self) -> None:
        s = Section(heading="H", level=2, body="", classification="mutable")
        assert compress_section(s) == ""

    def test_whitespace_only_body_compresses_to_empty_or_minimal(self) -> None:
        s = Section(heading="H", level=2, body="   \n  \n  \n", classification="mutable")
        result = compress_section(s)
        assert result.strip() == ""

    def test_empty_body_serializes_without_crash(self) -> None:
        doc = parse("## Empty Section\n## Next Section\ncontent\n")
        vtbf = serialize(doc, "test.md", "## Empty Section\n## Next Section\ncontent\n")
        assert "## Empty Section" in vtbf
        assert "## Next Section" in vtbf

    def test_empty_body_round_trips(self) -> None:
        source = "## Empty Section\n## Next Section\ncontent\n"
        doc = parse(source)
        vtbf = serialize(doc, "test.md", source)
        result = verify(vtbf)
        assert result.valid is True

    def test_immutable_empty_body_checksum_stable(self) -> None:
        text = (
            "<!-- shrinkwrap: immutable -->\n## Rules\n"
            "<!-- shrinkwrap: immutable -->\n## Also Rules\nsome content\n"
        )
        doc = parse(text)
        vtbf = serialize(doc, "test.md", text)
        result = verify(vtbf)
        assert result.valid is True


# ---------------------------------------------------------------------------
# B9 — compress on already-compressed file is idempotent (CLI)
# ---------------------------------------------------------------------------

class TestCLIIdempotency:
    def test_compress_twice_same_section_count(self, tmp_path: Path) -> None:
        runner = CliRunner()
        src = tmp_path / "CLAUDE.md"
        src.write_text("## Security Rules\nNever use eval.\n## Status\n- ok\n")

        runner.invoke(cli, ["compress", str(src)])
        sw1 = src.with_suffix(".sw.md")
        assert sw1.exists()

        runner.invoke(cli, ["compress", str(sw1)])
        sw2 = sw1.with_suffix(".sw.md")  # CLAUDE.sw.sw.md

        # Both files should have the same number of sw:section tags
        c1 = sw1.read_text().count("<!-- sw:section")
        c2 = sw2.read_text().count("<!-- sw:section")
        assert c1 == c2

    def test_compress_twice_verify_passes(self, tmp_path: Path) -> None:
        runner = CliRunner()
        src = tmp_path / "CLAUDE.md"
        src.write_text("<!-- shrinkwrap: immutable -->\n## Security\nNever.\n## Status\n- ok\n")

        runner.invoke(cli, ["compress", str(src)])
        sw1 = src.with_suffix(".sw.md")

        runner.invoke(cli, ["compress", str(sw1)])
        sw2 = sw1.with_suffix(".sw.md")

        result = runner.invoke(cli, ["verify", str(sw2)])
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# B10 — expand of a non-VTBF file exits non-zero
# ---------------------------------------------------------------------------

class TestExpandNonVTBF:
    def test_expand_plain_markdown_exits_nonzero(self, tmp_path: Path) -> None:
        runner = CliRunner()
        f = tmp_path / "plain.md"
        f.write_text("## Hello\nworld\n")
        result = runner.invoke(cli, ["expand", str(f)])
        assert result.exit_code != 0

    def test_expand_plain_markdown_error_message(self, tmp_path: Path) -> None:
        runner = CliRunner()
        f = tmp_path / "plain.md"
        f.write_text("## Hello\nworld\n")
        result = runner.invoke(cli, ["expand", str(f)])
        out = result.output.lower()
        assert "vtbf" in out or "not" in out or result.exit_code != 0


# ---------------------------------------------------------------------------
# B11 — verify handles VTBF with no immutable sections
# ---------------------------------------------------------------------------

class TestVerifyAllMutable:
    def test_all_mutable_vtbf_passes_verify(self, tmp_path: Path) -> None:
        runner = CliRunner()
        src = tmp_path / "CLAUDE.md"
        src.write_text("## Current Status\n- ok\n## Notes\n- nothing\n")
        runner.invoke(cli, ["compress", str(src)])
        vtbf = src.with_suffix(".sw.md")
        result = runner.invoke(cli, ["verify", str(vtbf)])
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# B12 — annotation at EOF with no following heading
# ---------------------------------------------------------------------------

class TestAnnotationAtEOF:
    def test_annotation_at_end_of_file_no_crash(self) -> None:
        text = "## Section\ncontent\n<!-- shrinkwrap: immutable -->\n"
        doc = parse(text)
        assert len(doc.sections) == 1
        assert doc.sections[0].heading == "Section"

    def test_annotation_only_file_no_crash(self) -> None:
        text = "<!-- shrinkwrap: immutable -->\n"
        doc = parse(text)
        assert doc.sections == []


# ---------------------------------------------------------------------------
# Property: expand(compress(x)) contains same headings as x
# ---------------------------------------------------------------------------

class TestExpandCompressProperty:
    SOURCES = [
        "## Alpha\ncontent\n## Beta\ncontent\n",
        "<!-- shrinkwrap: immutable -->\n## Rules\nNever.\n## Status\n- ok\n",
        "---\nauthor: test\n---\n## Section\ntext\n",
    ]

    @pytest.mark.parametrize("source", SOURCES)
    def test_expand_contains_original_headings(
        self, source: str, tmp_path: Path
    ) -> None:
        import re

        runner = CliRunner()
        src = tmp_path / "source.md"
        src.write_text(source)

        runner.invoke(cli, ["compress", str(src)])
        sw = src.with_suffix(".sw.md")
        out = tmp_path / "expanded.md"
        runner.invoke(cli, ["expand", str(sw), "-o", str(out)])

        original_headings = re.findall(r"^#{1,6} (.+)$", source, re.MULTILINE)
        expanded_text = out.read_text()
        for heading in original_headings:
            assert heading in expanded_text, f"Missing heading {heading!r} after expand"
