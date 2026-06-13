"""Tests for parser.py — front-matter extraction, section splitting, and classification."""

from __future__ import annotations

import warnings

import pytest

from shrinkwrap.parser import (
    ParsedDocument,
    Section,
    ShrinkWrapClassificationWarning,
    parse,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def section_by_heading(doc: ParsedDocument, heading: str) -> Section:
    for s in doc.sections:
        if s.heading == heading:
            return s
    raise KeyError(f"No section with heading {heading!r}")


# ---------------------------------------------------------------------------
# Front-matter extraction
# ---------------------------------------------------------------------------

class TestFrontMatterExtraction:
    def test_no_front_matter(self) -> None:
        doc = parse("## Hello\nworld\n")
        assert doc.front_matter == {}

    def test_valid_front_matter(self) -> None:
        text = "---\nauthor: alice\n---\n## Hello\nworld\n"
        doc = parse(text)
        assert doc.front_matter["author"] == "alice"

    def test_front_matter_not_in_sections(self) -> None:
        text = "---\nauthor: alice\n---\n## Hello\nworld\n"
        doc = parse(text)
        # The YAML front-matter block must not appear as a section
        assert len(doc.sections) == 1
        assert doc.sections[0].heading == "Hello"

    def test_invalid_yaml_falls_back_to_empty(self) -> None:
        text = "---\n: : invalid yaml ::\n---\n## Hello\n"
        doc = parse(text)
        assert doc.front_matter == {}

    def test_shrinkwrap_meta_extracted(self) -> None:
        text = (
            "---\n"
            "shrinkwrap:\n"
            "  immutable_sections:\n"
            "    - Security Rules\n"
            "---\n"
            "## Security Rules\ncontent\n"
        )
        doc = parse(text)
        assert "Security Rules" in doc.shrinkwrap_meta.get("immutable_sections", [])


# ---------------------------------------------------------------------------
# Section splitting
# ---------------------------------------------------------------------------

class TestSectionSplitting:
    def test_single_section(self) -> None:
        doc = parse("## Alpha\nline one\nline two\n")
        assert len(doc.sections) == 1
        assert doc.sections[0].heading == "Alpha"
        assert "line one" in doc.sections[0].body

    def test_multiple_sections(self) -> None:
        text = "## Alpha\nbody a\n## Beta\nbody b\n"
        doc = parse(text)
        assert len(doc.sections) == 2
        assert doc.sections[0].heading == "Alpha"
        assert doc.sections[1].heading == "Beta"

    def test_heading_levels_preserved(self) -> None:
        text = "# Top\nbody\n## Sub\nbody\n### Sub-sub\nbody\n"
        doc = parse(text)
        assert doc.sections[0].level == 1
        assert doc.sections[1].level == 2
        assert doc.sections[2].level == 3

    def test_preamble_before_first_heading(self) -> None:
        text = "This is preamble text.\n\n## Section\nbody\n"
        doc = parse(text)
        assert "preamble" in doc.preamble
        assert len(doc.sections) == 1

    def test_empty_document(self) -> None:
        doc = parse("")
        assert doc.sections == []
        assert doc.preamble == ""

    def test_document_with_only_front_matter(self) -> None:
        doc = parse("---\nkey: value\n---\n")
        assert doc.sections == []


# ---------------------------------------------------------------------------
# Classification — Signal 1: explicit annotation
# ---------------------------------------------------------------------------

class TestClassificationAnnotation:
    def test_annotation_immutable(self) -> None:
        text = "<!-- shrinkwrap: immutable -->\n## Security Rules\ncontent\n"
        doc = parse(text)
        s = section_by_heading(doc, "Security Rules")
        assert s.classification == "immutable"
        assert s.annotation_source is True

    def test_annotation_mutable(self) -> None:
        text = "<!-- shrinkwrap: mutable -->\n## Current Status\ncontent\n"
        doc = parse(text)
        s = section_by_heading(doc, "Current Status")
        assert s.classification == "mutable"
        assert s.annotation_source is True

    def test_annotation_applies_to_next_section_only(self) -> None:
        text = (
            "<!-- shrinkwrap: immutable -->\n"
            "## Section A\ncontent\n"
            "## Section B\ncontent\n"
        )
        doc = parse(text)
        assert section_by_heading(doc, "Section A").classification == "immutable"
        # Section B has no annotation — classification driven by other signals
        assert section_by_heading(doc, "Section B").classification != "immutable"

    def test_annotation_between_sections(self) -> None:
        text = (
            "## Section A\ncontent\n"
            "<!-- shrinkwrap: immutable -->\n"
            "## Section B\ncontent\n"
        )
        doc = parse(text)
        # Section A should NOT be immutable (annotation was for B)
        assert section_by_heading(doc, "Section A").classification != "immutable"
        assert section_by_heading(doc, "Section B").classification == "immutable"

    def test_annotation_compression_level(self) -> None:
        text = "<!-- shrinkwrap: mutable compression=condense -->\n## Sprint Notes\ncontent\n"
        doc = parse(text)
        s = section_by_heading(doc, "Sprint Notes")
        assert s.compression == "condense"


# ---------------------------------------------------------------------------
# Classification — Signal 2: front-matter section lists
# ---------------------------------------------------------------------------

class TestClassificationFrontMatter:
    def test_immutable_via_front_matter(self) -> None:
        text = (
            "---\n"
            "shrinkwrap:\n"
            "  immutable_sections:\n"
            "    - Coding Conventions\n"
            "---\n"
            "## Coding Conventions\ncontent\n"
        )
        doc = parse(text)
        s = section_by_heading(doc, "Coding Conventions")
        assert s.classification == "immutable"
        assert s.annotation_source is False

    def test_mutable_via_front_matter(self) -> None:
        text = (
            "---\n"
            "shrinkwrap:\n"
            "  mutable_sections:\n"
            "    - Sprint Context\n"
            "---\n"
            "## Sprint Context\ncontent\n"
        )
        doc = parse(text)
        assert section_by_heading(doc, "Sprint Context").classification == "mutable"

    def test_annotation_overrides_front_matter(self) -> None:
        text = (
            "---\n"
            "shrinkwrap:\n"
            "  mutable_sections:\n"
            "    - Important Section\n"
            "---\n"
            "<!-- shrinkwrap: immutable -->\n"
            "## Important Section\ncontent\n"
        )
        doc = parse(text)
        s = section_by_heading(doc, "Important Section")
        assert s.classification == "immutable"
        assert s.annotation_source is True


# ---------------------------------------------------------------------------
# Classification — Signal 3: heading text heuristics
# ---------------------------------------------------------------------------

class TestClassificationHeuristics:
    @pytest.mark.parametrize("heading", [
        "Security Rules",
        "Coding Conventions",
        "Architecture Patterns",
        "Forbidden Operations",
        "Constraints",
    ])
    def test_immutable_keywords_detected(self, heading: str) -> None:
        doc = parse(f"## {heading}\nsome content here\n")
        assert section_by_heading(doc, heading).classification == "immutable"

    @pytest.mark.parametrize("heading", [
        "Current Status",
        "Recent Changes",
        "Sprint Progress",
        "Todo List",
        "Changelog",
    ])
    def test_mutable_keywords_detected(self, heading: str) -> None:
        doc = parse(f"## {heading}\nsome content here\n")
        assert section_by_heading(doc, heading).classification == "mutable"

    def test_ambiguous_heading_warns(self) -> None:
        text = "## Current Architecture Rules\ncontent\n"
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            parse(text)
            assert any(issubclass(x.category, ShrinkWrapClassificationWarning) for x in w)

    def test_ambiguous_treated_as_immutable(self) -> None:
        text = "## Current Architecture Rules\ncontent\n"
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            doc = parse(text)
        s = section_by_heading(doc, "Current Architecture Rules")
        assert s.classification == "ambiguous"


# ---------------------------------------------------------------------------
# Classification — Signal 4: structural heuristics
# ---------------------------------------------------------------------------

class TestClassificationStructural:
    def test_bullet_only_section_is_mutable(self) -> None:
        body = "- item one\n- item two\n- item three\n"
        doc = parse(f"## My List\n{body}")
        assert section_by_heading(doc, "My List").classification == "mutable"

    def test_code_and_prose_section_is_immutable(self) -> None:
        body = (
            "Use this pattern when calling the API.\n\n"
            "```python\nresponse = client.get('/api/v1/data')\n```\n\n"
            "Never pass raw user input.\n"
        )
        doc = parse(f"## API Usage\n{body}")
        assert section_by_heading(doc, "API Usage").classification == "immutable"

    def test_pure_prose_no_keywords_defaults_to_mutable(self) -> None:
        doc = parse("## General Notes\nThis is some text without any keywords.\n")
        assert section_by_heading(doc, "General Notes").classification == "mutable"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_heading_with_trailing_hashes(self) -> None:
        doc = parse("## Heading Text ##\ncontent\n")
        assert doc.sections[0].heading == "Heading Text"

    def test_heading_text_stripped(self) -> None:
        doc = parse("##   Spaced Heading   \ncontent\n")
        assert doc.sections[0].heading == "Spaced Heading"

    def test_deeply_nested_heading(self) -> None:
        doc = parse("###### Deep\ncontent\n")
        assert doc.sections[0].level == 6

    def test_annotation_on_non_adjacent_line_is_ignored(self) -> None:
        # Annotation is separated from heading by a blank line — should NOT apply
        text = "<!-- shrinkwrap: immutable -->\n\n## Section\ncontent\n"
        doc = parse(text)
        # The annotation was separated by a blank line; it should not apply
        s = section_by_heading(doc, "Section")
        assert s.annotation_source is False

    def test_multiple_annotations_last_wins(self) -> None:
        text = (
            "<!-- shrinkwrap: immutable -->\n"
            "<!-- shrinkwrap: mutable -->\n"
            "## Section\ncontent\n"
        )
        doc = parse(text)
        s = section_by_heading(doc, "Section")
        assert s.classification == "mutable"

    def test_body_content_preserved(self) -> None:
        body = "line one\nline two\n\nline four\n"
        doc = parse(f"## Section\n{body}")
        assert doc.sections[0].body == body
