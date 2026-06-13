from __future__ import annotations

import json
import re
import warnings
from dataclasses import dataclass
from typing import Any, Literal, cast

import mistletoe
import yaml
from mistletoe.ast_renderer import AstRenderer

CLASSIFICATION = Literal["immutable", "mutable", "ambiguous"]
COMPRESSION = Literal["normalize", "condense", "aggressive"]

_FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)
_HEADING_RE = re.compile(r"^(#{1,6}) +(.+?)(?:\s+#+\s*)?$")
_ANNOTATION_RE = re.compile(
    r"<!--\s*shrinkwrap:\s*(\w+)(?:\s+compression=(\w+))?\s*-->"
)
# Strip VTBF section tags so re-parsing a compressed file is transparent.
_VTBF_TAG_RE = re.compile(r"<!--\s*/?sw:section\b[^\n]*-->")
# Detects the opening or closing of a fenced code block (``` or ~~~).
_FENCE_RE = re.compile(r"^(`{3,}|~{3,})")

_IMMUTABLE_KEYWORDS: frozenset[str] = frozenset(
    "security rules conventions requirements forbidden never always "
    "constraints architecture patterns".split()
)
_MUTABLE_KEYWORDS: frozenset[str] = frozenset(
    "status current recent today sprint progress todo changelog context notes".split()
)

_CODE_BLOCK_TYPES = frozenset(["FencedCode", "CodeFence", "BlockCode"])


class ShrinkWrapClassificationWarning(UserWarning):
    pass


@dataclass
class Section:
    heading: str
    level: int
    body: str
    classification: CLASSIFICATION
    annotation_source: bool = False
    compression: COMPRESSION = "normalize"
    trigger_keyword: str | None = None  # which heading keyword drove heuristic classification


@dataclass
class ParsedDocument:
    front_matter: dict[str, Any]
    shrinkwrap_meta: dict[str, Any]
    sections: list[Section]
    preamble: str


def _extract_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}, text
    try:
        data = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        data = {}
    if not isinstance(data, dict):
        data = {}
    return cast(dict[str, Any], data), text[m.end():]


def _classify_section(
    heading: str,
    annotation: str | None,
    annotation_compression: str | None,
    shrinkwrap_meta: dict[str, Any],
    body: str,
    extra_immutable: frozenset[str] = frozenset(),
    extra_mutable: frozenset[str] = frozenset(),
) -> tuple[CLASSIFICATION, bool, COMPRESSION, str | None]:
    """Return (classification, from_annotation, compression_level, trigger_keyword)."""

    # Signal 1: explicit annotation (highest precedence)
    if annotation is not None:
        ann = annotation.lower()
        if ann in ("immutable", "mutable", "ambiguous"):
            comp: COMPRESSION = "normalize"
            if annotation_compression in ("normalize", "condense", "aggressive"):
                comp = cast(COMPRESSION, annotation_compression)
            return cast(CLASSIFICATION, ann), True, comp, None

    # Signal 2: front-matter section lists
    immutable_list: list[str] = shrinkwrap_meta.get("immutable_sections", [])
    mutable_list: list[str] = shrinkwrap_meta.get("mutable_sections", [])
    if heading in immutable_list:
        return "immutable", False, "normalize", None
    if heading in mutable_list:
        return "mutable", False, "normalize", None

    # Signal 3: heading text heuristics
    words = set(re.sub(r"[^a-z\s]", "", heading.lower()).split())
    immutable_hits = words & (_IMMUTABLE_KEYWORDS | extra_immutable)
    mutable_hits = words & (_MUTABLE_KEYWORDS | extra_mutable)

    if immutable_hits and not mutable_hits:
        return "immutable", False, "normalize", sorted(immutable_hits)[0]
    if mutable_hits and not immutable_hits:
        return "mutable", False, "normalize", sorted(mutable_hits)[0]
    if immutable_hits and mutable_hits:
        warnings.warn(
            f"Section '{heading}' matched both immutable and mutable keywords "
            f"({immutable_hits!r} vs {mutable_hits!r}). "
            "Treating as immutable. Add an explicit annotation to suppress this warning.",
            ShrinkWrapClassificationWarning,
            stacklevel=4,
        )
        return "ambiguous", False, "normalize", sorted(immutable_hits)[0]

    # Signal 4: structural heuristics via mistletoe AST
    if body.strip():
        with AstRenderer() as renderer:  # type: ignore[no-untyped-call]
            ast_json = renderer.render(mistletoe.Document(body))  # type: ignore[attr-defined]
        ast = json.loads(ast_json)
        children: list[dict[str, Any]] = ast.get("children") or []

        has_code = any(c.get("type") in _CODE_BLOCK_TYPES for c in children)
        has_prose = any(c.get("type") == "Paragraph" for c in children)
        all_lists = bool(children) and all(c.get("type") == "List" for c in children)

        if all_lists:
            return "mutable", False, "normalize", None
        if has_code and has_prose:
            return "immutable", False, "normalize", None

    return "mutable", False, "normalize", None


def parse(text: str, config: object = None) -> ParsedDocument:
    """Parse a markdown instruction file into a structured ParsedDocument."""
    from .config import ShrinkWrapConfig  # local import to avoid circular
    extra_immutable: frozenset[str] = frozenset()
    extra_mutable: frozenset[str] = frozenset()
    if isinstance(config, ShrinkWrapConfig):
        extra_immutable = frozenset(k.lower() for k in config.extra_immutable_keywords)
        extra_mutable = frozenset(k.lower() for k in config.extra_mutable_keywords)

    front_matter, body_text = _extract_frontmatter(text)
    # Transparent re-parse: strip any existing VTBF section tags so that
    # compressing an already-compressed file is idempotent.
    body_text = _VTBF_TAG_RE.sub("", body_text)
    shrinkwrap_raw = front_matter.get("shrinkwrap", {})
    shrinkwrap_meta: dict[str, Any] = (
        shrinkwrap_raw if isinstance(shrinkwrap_raw, dict) else {}
    )

    sections: list[Section] = []
    lines = body_text.splitlines(keepends=True)

    # Annotation state: pending = seen, not yet consumed; current = belongs to open section
    pending_annotation: str | None = None
    pending_annotation_compression: str | None = None
    current_annotation: str | None = None
    current_annotation_compression: str | None = None

    current_heading: str | None = None
    current_level: int = 0
    current_body_lines: list[str] = []
    preamble_lines: list[str] = []
    # Track whether the last non-blank line before the heading was the annotation
    last_non_blank_was_annotation = False
    # Fenced code block tracking: headings inside fences must not split sections
    in_code_block = False
    code_fence_char: str = ""  # ` or ~

    def flush_current() -> None:
        nonlocal current_heading, current_level, current_body_lines
        nonlocal current_annotation, current_annotation_compression
        if current_heading is None:
            return
        body = "".join(current_body_lines)
        cls, from_ann, comp, kw = _classify_section(
            current_heading,
            current_annotation,
            current_annotation_compression,
            shrinkwrap_meta,
            body,
            extra_immutable=extra_immutable,
            extra_mutable=extra_mutable,
        )
        sections.append(
            Section(
                heading=current_heading,
                level=current_level,
                body=body,
                classification=cls,
                annotation_source=from_ann,
                compression=comp,
                trigger_keyword=kw,
            )
        )
        current_heading = None
        current_level = 0
        current_body_lines = []
        current_annotation = None
        current_annotation_compression = None

    for line in lines:
        stripped = line.rstrip()

        # --- Fenced code block tracking (must be first) ---
        fence_m = _FENCE_RE.match(stripped)
        if fence_m:
            marker_char = fence_m.group(1)[0]
            if not in_code_block:
                in_code_block = True
                code_fence_char = marker_char
            elif marker_char == code_fence_char:
                in_code_block = False
                code_fence_char = ""
            # Fence lines are always body/preamble — never headings or annotations
            if current_heading is not None:
                current_body_lines.append(line)
            else:
                preamble_lines.append(line)
            continue

        # Inside a code block: skip annotation and heading detection entirely
        if in_code_block:
            if current_heading is not None:
                current_body_lines.append(line)
            else:
                preamble_lines.append(line)
            continue

        # Check for annotation comment
        if "shrinkwrap:" in stripped:
            ann_match = _ANNOTATION_RE.search(stripped)
            if ann_match:
                pending_annotation = ann_match.group(1).lower()
                comp_val: str | None = ann_match.group(2)
                if comp_val and comp_val.lower() not in (
                    "normalize",
                    "condense",
                    "aggressive",
                ):
                    warnings.warn(
                        f"Invalid compression level {comp_val!r} in shrinkwrap annotation; "
                        "falling back to 'normalize'.",
                        ShrinkWrapClassificationWarning,
                        stacklevel=2,
                    )
                    comp_val = None
                pending_annotation_compression = comp_val
                last_non_blank_was_annotation = True
                continue

        # Track blank lines to detect non-adjacent annotations
        if not stripped:
            if last_non_blank_was_annotation:
                # Blank line after annotation — annotation is NOT adjacent to a heading
                # so it won't be applied; clear it
                pending_annotation = None
                pending_annotation_compression = None
                last_non_blank_was_annotation = False
            if current_heading is not None:
                current_body_lines.append(line)
            else:
                preamble_lines.append(line)
            continue

        last_non_blank_was_annotation = False

        # Check for heading
        h_match = _HEADING_RE.match(stripped)
        if h_match:
            flush_current()
            current_heading = h_match.group(2).strip()
            current_level = len(h_match.group(1))
            current_body_lines = []
            # Consume pending annotation for this section
            current_annotation = pending_annotation
            current_annotation_compression = pending_annotation_compression
            pending_annotation = None
            pending_annotation_compression = None
            continue

        # Regular content line
        if current_heading is not None:
            current_body_lines.append(line)
        else:
            preamble_lines.append(line)

    flush_current()

    return ParsedDocument(
        front_matter=front_matter,
        shrinkwrap_meta=shrinkwrap_meta,
        sections=sections,
        preamble="".join(preamble_lines),
    )
