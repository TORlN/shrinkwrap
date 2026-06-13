"""Tests for schema.py — VTBF serialization, front-matter envelope, and verify."""

from __future__ import annotations

import re

import yaml

from shrinkwrap.parser import parse
from shrinkwrap.schema import (
    SCHEMA_VERSION,
    VerifyResult,
    serialize,
    verify,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SAMPLE_SOURCE = """\
---
shrinkwrap:
  immutable_sections:
    - Security Rules
---

<!-- shrinkwrap: immutable -->
## Security Rules
Never use eval().
Always validate user input.

## Current Status
- tests passing
- deploy pending
"""

def _parse_fm(vtbf: str) -> dict:  # type: ignore[type-arg]
    m = re.match(r"\A---\n(.*?)\n---\n", vtbf, re.DOTALL)
    assert m, "No front-matter found in VTBF output"
    return yaml.safe_load(m.group(1)) or {}


# ---------------------------------------------------------------------------
# Serialize — front-matter envelope
# ---------------------------------------------------------------------------

class TestSerializeFrontMatter:
    def setup_method(self) -> None:
        self.doc = parse(SAMPLE_SOURCE)
        self.vtbf = serialize(self.doc, "CLAUDE.md", SAMPLE_SOURCE)
        self.fm = _parse_fm(self.vtbf)

    def test_schema_version_present(self) -> None:
        assert self.fm.get("shrinkwrap_schema") == SCHEMA_VERSION

    def test_source_file_recorded(self) -> None:
        assert self.fm.get("source_file") == "CLAUDE.md"

    def test_source_sha256_present_and_hex(self) -> None:
        sha = self.fm.get("source_sha256", "")
        assert re.fullmatch(r"[0-9a-f]+", sha)

    def test_compressed_at_iso8601(self) -> None:
        ts = self.fm.get("compressed_at", "")
        assert "T" in ts  # basic ISO 8601 check

    def test_compression_ratio_between_0_and_1(self) -> None:
        ratio = self.fm.get("compression_ratio", -1)
        assert 0.0 < ratio <= 1.0

    def test_total_tokens_positive(self) -> None:
        assert self.fm.get("total_tokens_approx", 0) > 0


# ---------------------------------------------------------------------------
# Serialize — section tags
# ---------------------------------------------------------------------------

class TestSerializeSectionTags:
    def setup_method(self) -> None:
        self.doc = parse(SAMPLE_SOURCE)
        self.vtbf = serialize(self.doc, "CLAUDE.md", SAMPLE_SOURCE)

    def test_immutable_section_has_checksum(self) -> None:
        # The immutable section tag should have a checksum attribute
        assert re.search(r'class="immutable"[^>]*checksum="[0-9a-f]+"', self.vtbf)

    def test_mutable_section_has_compression_attr(self) -> None:
        assert re.search(r'class="mutable"[^>]*compression="\w+"', self.vtbf)

    def test_section_open_and_close_tags_balanced(self) -> None:
        opens = len(re.findall(r"<!-- sw:section ", self.vtbf))
        closes = len(re.findall(r"<!-- /sw:section -->", self.vtbf))
        assert opens == closes
        assert opens == len(self.doc.sections)

    def test_section_content_between_tags(self) -> None:
        # The heading text must appear between the section tags
        assert "## Security Rules" in self.vtbf
        assert "## Current Status" in self.vtbf

    def test_immutable_content_not_modified(self) -> None:
        assert "Never use eval()" in self.vtbf
        assert "Always validate user input" in self.vtbf

    def test_output_is_valid_markdown(self) -> None:
        # Very basic: the output must not be empty and must contain heading markers
        assert self.vtbf.strip()
        assert "##" in self.vtbf


# ---------------------------------------------------------------------------
# Serialize — round-trip
# ---------------------------------------------------------------------------

class TestRoundTrip:
    def test_immutable_sections_byte_identical_after_round_trip(self) -> None:
        doc = parse(SAMPLE_SOURCE)
        vtbf = serialize(doc, "CLAUDE.md", SAMPLE_SOURCE)
        # Re-parse and re-serialize the VTBF output
        doc2 = parse(vtbf)
        vtbf2 = serialize(doc2, "CLAUDE.md.sw.md", vtbf)
        # The immutable section content must be identical across both passes
        def extract_section_content(text: str, section_id: str) -> str:
            m = re.search(
                rf'<!-- sw:section[^>]*id="{section_id}"[^>]*-->\n(.*?)<!-- /sw:section -->',
                text, re.DOTALL
            )
            return m.group(1) if m else ""

        first = extract_section_content(vtbf, "security-rules")
        second = extract_section_content(vtbf2, "security-rules")
        assert first == second

    def test_serialization_is_idempotent(self) -> None:
        doc = parse(SAMPLE_SOURCE)
        vtbf1 = serialize(doc, "CLAUDE.md", SAMPLE_SOURCE)
        doc2 = parse(vtbf1)
        vtbf2 = serialize(doc2, "CLAUDE.md", vtbf1)
        # The section count should be stable after re-serialization
        assert vtbf1.count("<!-- sw:section") == vtbf2.count("<!-- sw:section")


# ---------------------------------------------------------------------------
# Verify — valid document
# ---------------------------------------------------------------------------

class TestVerifyValid:
    def setup_method(self) -> None:
        doc = parse(SAMPLE_SOURCE)
        self.vtbf = serialize(doc, "CLAUDE.md", SAMPLE_SOURCE)

    def test_valid_document_passes(self) -> None:
        result = verify(self.vtbf)
        assert result.valid is True
        assert result.errors == []

    def test_verify_returns_verify_result(self) -> None:
        result = verify(self.vtbf)
        assert isinstance(result, VerifyResult)

    def test_strict_mode_passes_valid_document(self) -> None:
        result = verify(self.vtbf, strict=True, source_text=SAMPLE_SOURCE)
        assert result.valid is True


# ---------------------------------------------------------------------------
# Verify — tampered immutable section
# ---------------------------------------------------------------------------

class TestVerifyTamperedImmutable:
    def test_modified_immutable_content_fails_soft(self) -> None:
        doc = parse(SAMPLE_SOURCE)
        vtbf = serialize(doc, "CLAUDE.md", SAMPLE_SOURCE)
        # Tamper with the immutable content
        tampered = vtbf.replace("Never use eval().", "Always use eval().")
        result = verify(tampered)
        assert result.valid is False
        assert any("checksum" in e.lower() or "immutable" in e.lower() for e in result.errors)

    def test_modified_mutable_content_passes_soft(self) -> None:
        doc = parse(SAMPLE_SOURCE)
        vtbf = serialize(doc, "CLAUDE.md", SAMPLE_SOURCE)
        # Mutable sections have no checksum — modification should pass soft verify
        tampered = vtbf.replace("tests passing", "tests failing")
        result = verify(tampered)
        assert result.valid is True


# ---------------------------------------------------------------------------
# Verify — missing/invalid front-matter
# ---------------------------------------------------------------------------

class TestVerifyInvalidFrontMatter:
    def test_missing_front_matter_fails(self) -> None:
        result = verify("## Hello\ncontent\n")
        assert result.valid is False

    def test_unsupported_schema_version_fails(self) -> None:
        vtbf = "---\nshrinkwrap_schema: \"99.0\"\nsource_file: x\n---\n## H\ncontent\n"
        result = verify(vtbf)
        assert result.valid is False
        assert any("version" in e.lower() or "schema" in e.lower() for e in result.errors)
