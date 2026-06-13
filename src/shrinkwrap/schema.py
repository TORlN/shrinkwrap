from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import yaml

from .compressor import compress_document_sections
from .parser import _FRONTMATTER_RE, ParsedDocument

SCHEMA_VERSION = "1.0"

_SECTION_OPEN_RE = re.compile(
    r"<!-- sw:section\s+"
    r'id="(?P<id>[^"]+)"\s+'
    r'class="(?P<cls>[^"]+)"'
    r'(?:\s+checksum="(?P<checksum>[^"]+)")?'
    r'(?:\s+compression="(?P<compression>[^"]+)")?'
    r"(?:\s+original_tokens=(?P<orig_tok>\d+))?"
    r"(?:\s+compressed_tokens=(?P<comp_tok>\d+))?"
    r'(?:\s+manually_edited="(?P<manually_edited>[^"]+)")?'
    r"\s*-->",
)
_SECTION_CLOSE = "<!-- /sw:section -->"


@dataclass
class VerifyResult:
    valid: bool
    errors: list[str]
    warnings: list[str]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _sha256_short(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def _approx_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _section_id(heading: str) -> str:
    result = re.sub(r"[^a-z0-9]+", "-", heading.lower()).strip("-")
    return result or "section"


# ---------------------------------------------------------------------------
# Serialize
# ---------------------------------------------------------------------------


def serialize(
    doc: ParsedDocument,
    source_path: str,
    source_text: str,
    allow_lossy: bool = False,
) -> str:
    """Serialize a ParsedDocument into a VTBF markdown string."""
    total_original = 0
    total_compressed = 0
    section_blocks: list[str] = []
    seen_ids: set[str] = set()

    # Pre-compute all bodies together so cross-section dedup runs for condense/aggressive.
    compressed_bodies = compress_document_sections(doc.sections, allow_lossy=allow_lossy)

    for section, compressed_body in zip(doc.sections, compressed_bodies):
        heading_line = f"{'#' * section.level} {section.heading}\n"
        original_content = heading_line + section.body
        compressed_content = heading_line + compressed_body

        # Checksum covers the literal content that will appear in the file.
        # Normalise CRLF → LF before hashing so the stored checksum is
        # platform-independent and survives git autocrlf round-trips.
        content_in_file = compressed_content.rstrip() + "\n"
        content_in_file = content_in_file.replace("\r\n", "\n")
        is_protected = section.classification in ("immutable", "ambiguous")
        checksum = _sha256_short(content_in_file) if is_protected else ""

        orig_tok = _approx_tokens(original_content)
        comp_tok = _approx_tokens(compressed_content)
        total_original += orig_tok
        total_compressed += comp_tok

        sec_id = _section_id(section.heading)
        if sec_id in seen_ids:
            counter = 2
            while f"{sec_id}-{counter}" in seen_ids:
                counter += 1
            sec_id = f"{sec_id}-{counter}"
        seen_ids.add(sec_id)

        attrs = f'id="{sec_id}" class="{section.classification}"'
        if checksum:
            attrs += f' checksum="{checksum}"'
        if not is_protected:
            attrs += f' compression="{section.compression}"'
            attrs += f" original_tokens={orig_tok}"
            attrs += f" compressed_tokens={comp_tok}"

        # Re-emit the shrinkwrap annotation so it survives an expand→compress round-trip.
        annotation = ""
        if section.annotation_source:
            comp_hint = (
                f" compression={section.compression}" if section.compression != "normalize" else ""
            )
            annotation = f"<!-- shrinkwrap: {section.classification}{comp_hint} -->\n"

        block = f"{annotation}<!-- sw:section {attrs} -->\n{content_in_file}{_SECTION_CLOSE}"
        section_blocks.append(block)

    ratio = round(total_compressed / max(total_original, 1), 3)
    source_hash = _sha256_short(source_text)
    now = datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")

    front_matter = (
        "---\n"
        f'shrinkwrap_schema: "{SCHEMA_VERSION}"\n'
        f'source_file: "{source_path}"\n'
        f'source_sha256: "{source_hash}"\n'
        f'compressed_at: "{now}"\n'
        f"compression_ratio: {ratio}\n"
        f"total_tokens_approx: {total_compressed}\n"
        "---\n"
    )

    parts: list[str] = [front_matter]
    if doc.preamble.strip():
        parts.append(doc.preamble.rstrip() + "\n")
    parts.append("\n".join(section_blocks))
    return "\n".join(parts) + "\n"


# ---------------------------------------------------------------------------
# Verify
# ---------------------------------------------------------------------------


def verify(
    vtbf_text: str,
    strict: bool = False,
    source_text: str | None = None,
) -> VerifyResult:
    """Verify a VTBF document's integrity."""
    # Normalise CRLF → LF so that git autocrlf=true (Windows) doesn't invalidate
    # checksums that were computed from LF-normalised content by serialize().
    vtbf_text = vtbf_text.replace("\r\n", "\n")

    errors: list[str] = []
    warnings: list[str] = []

    # 1. Must have front-matter
    fm_match = _FRONTMATTER_RE.match(vtbf_text)
    if not fm_match:
        return VerifyResult(False, ["Missing VTBF front-matter"], [])

    try:
        fm: dict[str, Any] = yaml.safe_load(fm_match.group(1)) or {}
    except yaml.YAMLError as exc:
        return VerifyResult(False, [f"Invalid front-matter YAML: {exc}"], [])

    # 2. Schema version check
    schema_ver = str(fm.get("shrinkwrap_schema", ""))
    if not schema_ver:
        errors.append("Missing shrinkwrap_schema in front-matter")
    elif not schema_ver.startswith("1."):
        errors.append(f"Unsupported schema version: {schema_ver!r}. Run 'shrinkwrap upgrade'.")

    if errors:
        return VerifyResult(False, errors, warnings)

    # 3. Verify immutable section checksums
    body = vtbf_text[fm_match.end() :]
    for open_match in _SECTION_OPEN_RE.finditer(body):
        cls = open_match.group("cls")
        stored_checksum = open_match.group("checksum")

        if cls not in ("immutable", "ambiguous") or not stored_checksum:
            continue

        # Extract content between open and close tags
        content_start = open_match.end()
        # Skip the newline immediately after the open tag
        if content_start < len(body) and body[content_start] == "\n":
            content_start += 1

        close_pos = body.find(_SECTION_CLOSE, content_start)
        if close_pos == -1:
            errors.append(f"Unclosed section tag (id={open_match.group('id')!r})")
            continue

        content = body[content_start:close_pos]
        actual_checksum = _sha256_short(content)

        if actual_checksum != stored_checksum:
            sec_id = open_match.group("id")
            errors.append(
                f"Checksum mismatch in immutable section {sec_id!r}: "
                f"expected {stored_checksum!r}, got {actual_checksum!r}"
            )

    # 4. Strict mode: verify source file hash
    if strict and source_text is not None:
        stored_source_sha = str(fm.get("source_sha256", ""))
        actual_source_sha = _sha256_short(source_text)
        if stored_source_sha and actual_source_sha != stored_source_sha:
            errors.append(
                "Source file has changed since compression "
                f"(stored={stored_source_sha!r}, current={actual_source_sha!r}). "
                "Re-run 'shrinkwrap compress'."
            )

    return VerifyResult(valid=len(errors) == 0, errors=errors, warnings=warnings)
