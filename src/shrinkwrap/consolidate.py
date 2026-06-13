"""Multi-file auto-discovery and consolidation engine."""

from __future__ import annotations

import os
import re
from pathlib import Path

import yaml

from .compressor import _dedup_cross_section
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


def merge_documents(paths: list[Path]) -> str:
    """Parse all *paths*, deduplicate sections by heading, and return merged markdown.

    Deduplication strategy:
    - First-seen heading wins (files are processed in the order given).
    - Bullet lines that appear in earlier sections are removed from later sections
      via the existing cross-section deduplication engine in compressor.py.

    Returns an empty string when *paths* is empty or yields no sections.
    """
    all_sections: list[Section] = []
    seen_headings: set[str] = set()

    for path in paths:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue

        doc = parse(text)
        for section in doc.sections:
            key = section.heading.lower().strip()
            if key not in seen_headings:
                seen_headings.add(key)
                all_sections.append(section)

    if not all_sections:
        return ""

    # Cross-section bullet deduplication using the existing condense infrastructure.
    bodies = [s.body for s in all_sections]
    deduped_bodies = _dedup_cross_section(bodies)

    parts: list[str] = []
    for section, body in zip(all_sections, deduped_bodies):
        heading_line = f"{'#' * section.level} {section.heading}"
        if body.strip():
            parts.append(f"{heading_line}\n{body.rstrip()}")
        else:
            parts.append(heading_line)

    return "\n\n".join(parts) + "\n"
