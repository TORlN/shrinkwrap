"""Multi-file auto-discovery and consolidation engine."""

from __future__ import annotations

import os
import re
from pathlib import Path

import yaml

from .compressor import _dedup_cross_section_counted, compress_document_sections_counted
from .metrics import CompressionMetrics
from .parser import Section, parse

# ---------------------------------------------------------------------------
# Agentic-signature detection
# ---------------------------------------------------------------------------

# Files whose name alone is sufficient to flag them as agentic instruction files.
_AGENTIC_NAMES: frozenset[str] = frozenset(
    [
        "CLAUDE.md",
        ".cursorrules",
        "SYSTEM_PROMPT.md",
        "INSTRUCTIONS.md",
        "AGENTS.md",
        "cursor_rules.md",
    ]
)

# YAML front-matter keys commonly found in agentic instruction files.
_AGENTIC_FM_KEYS: frozenset[str] = frozenset(
    [
        "shrinkwrap_schema",
        "model",
        "instructions",
        "rules",
        "description",
        "agent",
        "system_prompt",
    ]
)

_SHRINKWRAP_ANNOTATION_RE = re.compile(r"<!--\s*shrinkwrap:", re.IGNORECASE)
_FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)

# Directories that are never crawled.
_SKIP_DIRS: frozenset[str] = frozenset(
    [".git", "node_modules", "__pycache__", ".venv", "venv", ".tox", ".mypy_cache"]
)


def is_agentic_file(path: Path) -> bool:
    """Return True if *path* looks like an agentic instruction file.

    Checks (in order):
    1. The filename matches a known agentic name.
    2. The filename matches the CLAUDE.<anything>.md pattern.
    3. The filename ends with .cursorrules.
    4. The file body contains a <!-- shrinkwrap: ... --> annotation.
    5. The YAML front-matter contains at least one known agentic key.
    """
    name = path.name

    if name in _AGENTIC_NAMES:
        return True

    if name.startswith("CLAUDE.") and name.endswith(".md"):
        return True

    if name.endswith(".cursorrules"):
        return True

    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False

    if _SHRINKWRAP_ANNOTATION_RE.search(text):
        return True

    fm_match = _FRONTMATTER_RE.match(text)
    if fm_match:
        try:
            fm = yaml.safe_load(fm_match.group(1)) or {}
        except Exception:
            fm = {}
        if isinstance(fm, dict) and any(k in _AGENTIC_FM_KEYS for k in fm):
            return True

    return False


def discover_agentic_files(root: Path) -> list[Path]:
    """Recursively crawl *root* and return all agentic instruction files.

    Uses os.walk with topdown=True so that skip-listed directories (.git,
    node_modules, etc.) are pruned in-place before descent — rglob cannot
    do this and would still enumerate files inside those directories.
    """
    found: list[Path] = []

    for dirpath_str, dirnames, filenames in os.walk(str(root), topdown=True):
        # Prune skip-listed directories in-place so os.walk doesn't descend.
        dirnames[:] = sorted(d for d in dirnames if d not in _SKIP_DIRS)

        for filename in sorted(filenames):
            path = Path(dirpath_str) / filename
            # Only consider markdown-adjacent and extensionless files.
            if path.suffix not in (".md", "") and not filename.endswith(".cursorrules"):
                continue
            if is_agentic_file(path):
                found.append(path)

    return found


# ---------------------------------------------------------------------------
# Merge engine
# ---------------------------------------------------------------------------


def _approx_tokens(text: str) -> int:
    return max(1, len(text) // 4)


_VALID_LEVELS = frozenset(["normalize", "condense", "aggressive"])


def consolidate_with_metrics(
    paths: list[Path],
    level: str | None = None,
    allow_lossy: bool = False,
) -> tuple[str, CompressionMetrics]:
    """Parse all *paths*, deduplicate, and return (merged_markdown, metrics).

    tokens_before counts every section from every file (including dropped duplicates)
    so the savings figure reflects the full consolidation benefit.

    When *level* is set, mutable sections are compressed at that level after
    heading-deduplication.  ``level="aggressive"`` requires ``allow_lossy=True``
    or raises ValueError.
    """
    if level is not None and level not in _VALID_LEVELS:
        raise ValueError(f"Invalid level {level!r}. Must be one of {sorted(_VALID_LEVELS)}.")
    if level == "aggressive" and not allow_lossy:
        raise ValueError(
            "level='aggressive' requires allow_lossy=True (it may discard prose content)."
        )

    if not paths:
        return "", CompressionMetrics(
            files_processed=0,
            tokens_before=0,
            tokens_after=0,
            tokens_saved=0,
            compression_pct=0.0,
            duplicate_sections_removed=0,
            duplicate_bullets_removed=0,
        )

    all_sections: list[Section] = []
    seen_headings: set[str] = set()
    sections_encountered = 0
    tokens_before = 0

    for path in paths:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue

        doc = parse(text)
        for section in doc.sections:
            sections_encountered += 1
            tokens_before += _approx_tokens(section.body)
            key = section.heading.lower().strip()
            if key not in seen_headings:
                seen_headings.add(key)
                all_sections.append(section)

    duplicate_sections_removed = sections_encountered - len(all_sections)

    if not all_sections:
        tokens_saved = tokens_before
        return "", CompressionMetrics(
            files_processed=len(paths),
            tokens_before=tokens_before,
            tokens_after=0,
            tokens_saved=tokens_saved,
            compression_pct=round(tokens_saved / max(tokens_before, 1) * 100, 1),
            duplicate_sections_removed=duplicate_sections_removed,
            duplicate_bullets_removed=0,
        )

    if level is not None:
        # Apply level to mutable sections, then route through compression pipeline.
        for section in all_sections:
            if section.classification not in ("immutable", "ambiguous"):
                section.compression = level  # type: ignore[assignment]
        deduped_bodies, duplicate_bullets_removed = compress_document_sections_counted(
            all_sections, allow_lossy=allow_lossy
        )
    else:
        bodies = [s.body for s in all_sections]
        deduped_bodies, duplicate_bullets_removed = _dedup_cross_section_counted(bodies)

    tokens_after = sum(_approx_tokens(body) for body in deduped_bodies)
    tokens_saved = max(0, tokens_before - tokens_after)
    compression_pct = round(tokens_saved / max(tokens_before, 1) * 100, 1)

    parts: list[str] = []
    for section, body in zip(all_sections, deduped_bodies):
        heading_line = f"{'#' * section.level} {section.heading}"
        if body.strip():
            parts.append(f"{heading_line}\n{body.rstrip()}")
        else:
            parts.append(heading_line)

    merged = "\n\n".join(parts) + "\n"

    metrics = CompressionMetrics(
        files_processed=len(paths),
        tokens_before=tokens_before,
        tokens_after=tokens_after,
        tokens_saved=tokens_saved,
        compression_pct=compression_pct,
        duplicate_sections_removed=duplicate_sections_removed,
        duplicate_bullets_removed=duplicate_bullets_removed,
    )
    return merged, metrics


def merge_documents(paths: list[Path]) -> str:
    """Parse all *paths*, deduplicate sections by heading, and return merged markdown.

    Deduplication strategy:
    - First-seen heading wins (files are processed in the order given).
    - Bullet lines that appear in earlier sections are removed from later sections
      via the existing cross-section deduplication engine in compressor.py.

    Returns an empty string when *paths* is empty or yields no sections.
    """
    merged, _ = consolidate_with_metrics(paths)
    return merged
