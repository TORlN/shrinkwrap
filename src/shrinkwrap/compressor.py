from __future__ import annotations

import re

from .parser import COMPRESSION, Section

# Sentences containing these patterns are pinned in aggressive mode — never dropped.
_HIGH_STAKES_RE = re.compile(
    r"\b(never|always|forbidden|must not|do not|don't|required|prohibited|disallowed)\b",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _strip_trailing_spaces(text: str) -> str:
    return "\n".join(line.rstrip() for line in text.split("\n"))


def _collapse_blank_lines(text: str) -> str:
    return re.sub(r"\n{3,}", "\n\n", text)


def _dedup_adjacent_bullets(text: str) -> str:
    """Remove immediately adjacent duplicate bullet points."""
    lines = text.split("\n")
    result: list[str] = []
    prev_bullet: str | None = None
    for line in lines:
        stripped = line.strip()
        is_bullet = stripped.startswith(("- ", "* ", "+ ")) or re.match(r"^\d+\.\s", stripped)
        if is_bullet and stripped == prev_bullet:
            continue
        result.append(line)
        prev_bullet = stripped if is_bullet else None
    return "\n".join(result)


def _normalize(text: str) -> str:
    text = _strip_trailing_spaces(text)
    text = _collapse_blank_lines(text)
    text = _dedup_adjacent_bullets(text)
    return text


def _dedup_cross_section(sections_bodies: list[str]) -> list[str]:
    """Remove bullet lines that already appeared in an earlier section."""
    seen_bullets: set[str] = set()
    result: list[str] = []
    for body in sections_bodies:
        output_lines: list[str] = []
        for line in body.split("\n"):
            stripped = line.strip()
            is_bullet = stripped.startswith(("- ", "* ", "+ ")) or re.match(r"^\d+\.\s", stripped)
            if is_bullet:
                key = re.sub(r"^[-*+]\s+|\d+\.\s+", "", stripped).lower().strip()
                if key in seen_bullets:
                    continue
                seen_bullets.add(key)
            output_lines.append(line)
        result.append("\n".join(output_lines))
    return result


def _is_high_stakes(sentence: str) -> bool:
    return bool(_HIGH_STAKES_RE.search(sentence))


def _relevance_prune(text: str) -> str:
    """
    Drop sentences that are neither high-stakes nor in list/code context.
    High-stakes sentences (never/always/forbidden/...) are always kept.
    """
    lines = text.split("\n")
    output: list[str] = []
    in_code_block = False

    for line in lines:
        stripped = line.strip()

        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_code_block = not in_code_block
            output.append(line)
            continue

        if in_code_block:
            output.append(line)
            continue

        # Keep list items, headings, and blank lines unconditionally
        is_structural = (
            not stripped
            or stripped.startswith(("#", "-", "*", "+"))
            or re.match(r"^\d+\.", stripped) is not None
        )
        if is_structural:
            output.append(line)
            continue

        # For prose lines: keep only if high-stakes
        if _is_high_stakes(line):
            output.append(line)
        # else: drop (filler prose)

    result = "\n".join(output)
    result = _collapse_blank_lines(result)
    return result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compress_section(section: Section, allow_lossy: bool = False) -> str:
    """
    Compress a section's body according to its classification and compression level.
    Returns the compressed body (without the heading line).
    """
    body = section.body

    # Immutable and ambiguous sections: whitespace normalization only.
    # Ambiguous sections matched both immutable and mutable keywords; the warning
    # says "treating as immutable", and we honour that in the compressor too.
    if section.classification in ("immutable", "ambiguous"):
        return _normalize(body)

    level: COMPRESSION = section.compression

    if level == "aggressive" and not allow_lossy:
        raise ValueError(
            "aggressive compression requires allow_lossy=True "
            "(pass --allow-lossy on the CLI)"
        )

    body = _normalize(body)

    if level == "normalize":
        return body

    # condense: normalize already applied
    if level == "condense":
        return body

    # aggressive: prune low-value prose, keep high-stakes sentences
    return _relevance_prune(body)


def compress_document_sections(
    sections: list[Section], allow_lossy: bool = False
) -> list[str]:
    """
    Compress all sections together, applying cross-section deduplication
    for the condense/aggressive levels.
    """
    # First pass: individual compression
    bodies = [compress_section(s, allow_lossy=allow_lossy) for s in sections]

    # Identify which sections are mutable and at condense+ level
    needs_cross_dedup = [
        s.classification not in ("immutable", "ambiguous")
        and s.compression in ("condense", "aggressive")
        for s in sections
    ]

    if not any(needs_cross_dedup):
        return bodies

    # Extract mutable bodies for cross-dedup
    mutable_indices = [i for i, nd in enumerate(needs_cross_dedup) if nd]
    mutable_bodies = [bodies[i] for i in mutable_indices]
    deduped = _dedup_cross_section(mutable_bodies)

    for idx, deduped_body in zip(mutable_indices, deduped):
        bodies[idx] = deduped_body

    return bodies
