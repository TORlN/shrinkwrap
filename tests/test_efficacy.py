"""
Efficacy tests — measures HOW WELL compression works, not just that it works.

Generates a synthetic instruction file with precisely controlled content:
deliberate cross-section duplicates, high-stakes safety rules, unique facts,
and filler prose. Compresses it through the full CLI stack and asserts
measurable quality metrics on the output.

Metrics tested:
  - Compression ratio (token reduction)
  - High-stakes rule preservation rate
  - Unique fact survival rate
  - Deduplication effectiveness
  - Information density improvement
  - Filler pruning (aggressive mode)
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from shrinkwrap.cli import cli

# ---------------------------------------------------------------------------
# Corpus definition — known content with measurable properties
# ---------------------------------------------------------------------------

# Imperative safety rules that MUST survive every compression level.
# Each contains a high-stakes keyword (never/always/must/forbidden/do not).
_MUST_SURVIVE = [
    "Never use eval() or exec() with user-supplied input.",
    "Always validate all input at system boundaries.",
    "Forbidden: committing secrets, API keys, or credentials to the repository.",
    "Must not use MD5 or SHA1 for cryptographic hashing.",
    "Do not store plaintext passwords under any circumstances.",
]

# Factual bullets appearing exactly once in the source (no duplicates).
_UNIQUE_FACTS = [
    "authentication uses JWT tokens with 24-hour expiry",
    "database migrations run via Alembic",
    "CI pipeline defined in .github/workflows/ci.yml",
    "staging environment at staging.example.internal",
    "production deploys require two approvals",
    "logging uses structured JSON format",
    "rate limiting: 100 req/min per API key",
    "test suite runs in under 90 seconds",
]

# Status bullets intentionally duplicated across all three mutable sections.
# condense must collapse each to a single occurrence.
_SHARED_BULLETS = [
    "tests are passing",
    "main branch is protected",
    "deploy is pending review",
    "documentation is up to date",
]

# Filler prose — non-high-stakes, non-bullet.
# The first two live in the immutable section (must be preserved regardless).
# The last two live in mutable sections (aggressive mode should prune them).
_FILLER = [
    "This section provides context for the development team.",
    "Please review the following items at your convenience.",
    "The information below has been compiled from various sources.",
    "Additional context may be found in the project wiki.",
]


def _bullets(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items)


def _build_corpus() -> str:
    """
    Build a synthetic CLAUDE.md with precisely controlled redundancy.

    Structure:
      Security Rules  (immutable)  — 5 must-survive rules + 2 filler sentences
      Sprint Status   (condense)   — 3 unique facts + 4 shared bullets + 1 filler
      Architecture    (condense)   — 3 unique facts + 4 shared bullets + 1 filler
      Operations      (condense)   — 2 unique facts + 4 shared bullets

    The 4 shared bullets appear 3 times each, giving 8 redundant occurrences
    for condense to eliminate.
    """
    return (
        "\n\n".join(
            [
                (
                    "<!-- shrinkwrap: immutable -->\n"
                    "## Security Rules\n" + "\n".join(_MUST_SURVIVE) + "\n" + "\n".join(_FILLER[:2])
                ),
                (
                    "<!-- shrinkwrap: mutable compression=condense -->\n"
                    "## Sprint Status\n"
                    + _bullets(_UNIQUE_FACTS[:3])
                    + "\n"
                    + _bullets(_SHARED_BULLETS)
                    + "\n"
                    + _FILLER[2]
                ),
                (
                    "<!-- shrinkwrap: mutable compression=condense -->\n"
                    "## Architecture Notes\n"
                    + _bullets(_UNIQUE_FACTS[3:6])
                    + "\n"
                    + _bullets(_SHARED_BULLETS)
                    + "\n"
                    + _FILLER[3]
                ),
                (
                    "<!-- shrinkwrap: mutable compression=condense -->\n"
                    "## Operations\n"
                    + _bullets(_UNIQUE_FACTS[6:])
                    + "\n"
                    + _bullets(_SHARED_BULLETS)
                ),
            ]
        )
        + "\n"
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _compress(src: Path, level: str | None = None, allow_lossy: bool = False) -> str:
    """Run `shrinkwrap compress` end-to-end; return the VTBF text."""
    args = ["compress", str(src)]
    if level:
        args += ["--level", level]
    if allow_lossy:
        args.append("--allow-lossy")
    result = CliRunner().invoke(cli, args)
    assert result.exit_code == 0, f"compress failed (exit {result.exit_code}):\n{result.output}"
    return src.with_suffix(".sw.md").read_text()


def _front_matter(vtbf: str) -> dict:  # type: ignore[type-arg]
    m = re.match(r"\A---\n(.*?)\n---\n", vtbf, re.DOTALL)
    assert m, "No VTBF front-matter found"
    return yaml.safe_load(m.group(1)) or {}


def _clean_vtbf(vtbf: str) -> str:
    """Strip front-matter and VTBF comment tags, leaving only section content."""
    text = re.sub(r"\A---\n.*?\n---\n", "", vtbf, flags=re.DOTALL)
    text = re.sub(r"<!--[^\n]*-->\n?", "", text)
    return text


def _extract_bullets(text: str) -> list[str]:
    """Return normalized bullet text (without the leading dash/space)."""
    return [
        re.sub(r"^\s*[-*+]\s+", "", line).strip()
        for line in text.splitlines()
        if re.match(r"^\s*[-*+]\s+", line)
    ]


def _bullet_occurrences(text: str, fact: str) -> int:
    return sum(1 for b in _extract_bullets(text) if fact in b)


def _information_density(vtbf: str) -> float:
    """
    Unique bullet count / non-blank non-heading content lines (after stripping VTBF markup).
    Higher is better — more distinct facts per line of text.
    """
    clean = _clean_vtbf(vtbf)
    content_lines = [ln for ln in clean.splitlines() if ln.strip() and not ln.startswith("#")]
    unique_bullets = set(_extract_bullets(clean))
    if not content_lines:
        return 0.0
    return len(unique_bullets) / len(content_lines)


# ---------------------------------------------------------------------------
# Corpus sanity check — verify test preconditions
# ---------------------------------------------------------------------------


class TestCorpusPreconditions:
    """Verify the synthetic corpus has the structural properties the efficacy tests rely on."""

    def test_corpus_has_four_sections(self) -> None:
        from shrinkwrap.parser import parse

        doc = parse(_build_corpus())
        assert len(doc.sections) == 4

    def test_corpus_has_duplicate_bullets(self) -> None:
        corpus = _build_corpus()
        bullets = _extract_bullets(corpus)
        assert len(bullets) > len(set(bullets)), (
            "Corpus must contain duplicate bullets for dedup tests to be meaningful"
        )

    def test_corpus_has_expected_duplication_count(self) -> None:
        corpus = _build_corpus()
        bullets = _extract_bullets(corpus)
        duplicate_count = len(bullets) - len(set(bullets))
        # 4 shared bullets × 2 extra occurrences (appear in all 3 sections) = 8
        assert duplicate_count == 8, f"Expected 8 duplicate bullets, found {duplicate_count}"

    def test_corpus_immutable_section_has_no_bullets(self) -> None:
        from shrinkwrap.parser import parse

        doc = parse(_build_corpus())
        immutable = next(s for s in doc.sections if s.classification == "immutable")
        assert _extract_bullets(immutable.body) == []

    def test_all_must_survive_rules_are_in_immutable_section(self) -> None:
        from shrinkwrap.parser import parse

        doc = parse(_build_corpus())
        immutable = next(s for s in doc.sections if s.classification == "immutable")
        for rule in _MUST_SURVIVE:
            assert rule in immutable.body


# ---------------------------------------------------------------------------
# 1. Compression ratio
# ---------------------------------------------------------------------------


class TestCompressionRatio:
    """Token reduction must be meaningful and correctly ordered across levels."""

    def test_condense_compression_ratio_is_below_one(self, tmp_path: Path) -> None:
        src = tmp_path / "CLAUDE.md"
        src.write_text(_build_corpus())
        vtbf = _compress(src, level="condense")
        ratio = float(_front_matter(vtbf).get("compression_ratio", 1.0))
        assert ratio < 1.0, f"Expected compression_ratio < 1.0, got {ratio}"

    def test_condense_achieves_at_least_15_percent_reduction(self, tmp_path: Path) -> None:
        """8 duplicate bullets removed from known corpus must yield ≥15% token saving."""
        src = tmp_path / "CLAUDE.md"
        src.write_text(_build_corpus())
        vtbf = _compress(src, level="condense")
        ratio = float(_front_matter(vtbf).get("compression_ratio", 1.0))
        assert ratio <= 0.85, (
            f"Expected compression_ratio ≤0.85 with 8 duplicates removed, got {ratio:.3f}"
        )

    def test_normalize_ratio_higher_than_condense(self, tmp_path: Path) -> None:
        """condense must produce fewer tokens than normalize on duplicate-heavy input."""
        src_norm = tmp_path / "norm.md"
        src_cond = tmp_path / "cond.md"
        src_norm.write_text(_build_corpus())
        src_cond.write_text(_build_corpus())

        tok_norm = int(
            _front_matter(_compress(src_norm, "normalize")).get("total_tokens_approx", 0)
        )
        tok_cond = int(_front_matter(_compress(src_cond, "condense")).get("total_tokens_approx", 0))
        assert tok_cond <= tok_norm, (
            f"condense ({tok_cond} tok) produced more tokens than normalize ({tok_norm} tok)"
        )

    def test_aggressive_produces_fewer_tokens_than_condense(self, tmp_path: Path) -> None:
        """aggressive must strip filler prose → lower token count than condense."""
        src_agg = tmp_path / "agg.md"
        src_cond = tmp_path / "cond.md"
        src_agg.write_text(_build_corpus())
        src_cond.write_text(_build_corpus())

        tok_agg = int(
            _front_matter(_compress(src_agg, "aggressive", allow_lossy=True)).get(
                "total_tokens_approx", 99999
            )
        )
        tok_cond = int(_front_matter(_compress(src_cond, "condense")).get("total_tokens_approx", 0))
        assert tok_agg <= tok_cond, (
            f"aggressive ({tok_agg} tok) not smaller than condense ({tok_cond} tok)"
        )

    def test_compression_ratio_reported_in_front_matter(self, tmp_path: Path) -> None:
        src = tmp_path / "CLAUDE.md"
        src.write_text(_build_corpus())
        vtbf = _compress(src, level="condense")
        fm = _front_matter(vtbf)
        assert "compression_ratio" in fm
        assert "total_tokens_approx" in fm
        assert isinstance(fm["total_tokens_approx"], int)
        assert fm["total_tokens_approx"] > 0


# ---------------------------------------------------------------------------
# 2. High-stakes rule preservation
# ---------------------------------------------------------------------------


class TestHighStakesPreservation:
    """Safety-critical rules must survive every compression level at 100%."""

    @pytest.mark.parametrize("rule", _MUST_SURVIVE)
    def test_rule_survives_condense(self, tmp_path: Path, rule: str) -> None:
        src = tmp_path / "CLAUDE.md"
        src.write_text(_build_corpus())
        vtbf = _compress(src, level="condense")
        assert rule in vtbf, f"Rule lost in condense: {rule!r}"

    @pytest.mark.parametrize("rule", _MUST_SURVIVE)
    def test_rule_survives_aggressive(self, tmp_path: Path, rule: str) -> None:
        src = tmp_path / "CLAUDE.md"
        src.write_text(_build_corpus())
        vtbf = _compress(src, level="aggressive", allow_lossy=True)
        assert rule in vtbf, f"Rule lost in aggressive: {rule!r}"

    def test_preservation_rate_100_percent_condense(self, tmp_path: Path) -> None:
        src = tmp_path / "CLAUDE.md"
        src.write_text(_build_corpus())
        vtbf = _compress(src, level="condense")
        survived = sum(1 for r in _MUST_SURVIVE if r in vtbf)
        assert survived == len(_MUST_SURVIVE), (
            f"Only {survived}/{len(_MUST_SURVIVE)} rules survived condense"
        )

    def test_preservation_rate_100_percent_aggressive(self, tmp_path: Path) -> None:
        src = tmp_path / "CLAUDE.md"
        src.write_text(_build_corpus())
        vtbf = _compress(src, level="aggressive", allow_lossy=True)
        survived = sum(1 for r in _MUST_SURVIVE if r in vtbf)
        assert survived == len(_MUST_SURVIVE), (
            f"Only {survived}/{len(_MUST_SURVIVE)} rules survived aggressive"
        )

    def test_immutable_section_content_byte_identical(self, tmp_path: Path) -> None:
        """Immutable section body must be character-for-character identical after compression."""
        from shrinkwrap.parser import parse

        corpus = _build_corpus()
        src = tmp_path / "CLAUDE.md"
        src.write_text(corpus)
        vtbf = _compress(src, level="aggressive", allow_lossy=True)

        # Extract body from original and from VTBF
        src_doc = parse(corpus)
        out_doc = parse(vtbf)

        src_immutable = next(s for s in src_doc.sections if s.classification == "immutable")
        out_immutable = next(s for s in out_doc.sections if s.classification == "immutable")

        # Bodies should be identical after normalization (strip/collapse blank lines)
        src_body = src_immutable.body.strip()
        out_body = out_immutable.body.strip()
        assert src_body == out_body, (
            "Immutable section body changed after compression\n"
            f"  before: {src_body!r}\n"
            f"  after:  {out_body!r}"
        )


# ---------------------------------------------------------------------------
# 3. Unique fact preservation
# ---------------------------------------------------------------------------


class TestUniqueFactPreservation:
    """Every unique, non-duplicated fact must survive condense compression."""

    def test_all_unique_facts_survive_condense(self, tmp_path: Path) -> None:
        src = tmp_path / "CLAUDE.md"
        src.write_text(_build_corpus())
        vtbf = _compress(src, level="condense")
        missing = [f for f in _UNIQUE_FACTS if f not in vtbf]
        assert not missing, (
            f"{len(missing)}/{len(_UNIQUE_FACTS)} unique facts lost in condense:\n"
            + "\n".join(f"  - {f}" for f in missing)
        )

    def test_unique_fact_survival_rate_is_100_percent(self, tmp_path: Path) -> None:
        src = tmp_path / "CLAUDE.md"
        src.write_text(_build_corpus())
        vtbf = _compress(src, level="condense")
        survived = sum(1 for f in _UNIQUE_FACTS if f in vtbf)
        assert survived == len(_UNIQUE_FACTS), (
            f"Unique fact survival rate: {survived}/{len(_UNIQUE_FACTS)}"
        )

    def test_all_section_headings_preserved(self, tmp_path: Path) -> None:
        src = tmp_path / "CLAUDE.md"
        src.write_text(_build_corpus())
        vtbf = _compress(src, level="condense")
        for heading in ("Security Rules", "Sprint Status", "Architecture Notes", "Operations"):
            assert heading in vtbf, f"Section heading missing: {heading!r}"

    @pytest.mark.parametrize("fact", _UNIQUE_FACTS)
    def test_each_unique_fact_present_in_output(self, tmp_path: Path, fact: str) -> None:
        src = tmp_path / "CLAUDE.md"
        src.write_text(_build_corpus())
        vtbf = _compress(src, level="condense")
        assert fact in vtbf, f"Unique fact missing from condense output: {fact!r}"


# ---------------------------------------------------------------------------
# 4. Deduplication effectiveness
# ---------------------------------------------------------------------------


class TestDeduplicationEffectiveness:
    """Shared bullets duplicated 3× across sections must collapse to exactly 1 each."""

    @pytest.mark.parametrize("fact", _SHARED_BULLETS)
    def test_shared_bullet_appears_exactly_once(self, tmp_path: Path, fact: str) -> None:
        src = tmp_path / "CLAUDE.md"
        src.write_text(_build_corpus())
        vtbf = _compress(src, level="condense")
        count = _bullet_occurrences(vtbf, fact)
        assert count == 1, (
            f"Shared bullet {fact!r} appears {count}× after condense (expected exactly 1)"
        )

    def test_total_bullet_count_reduced(self, tmp_path: Path) -> None:
        """condense must eliminate ≥8 of the 8 known duplicate bullet occurrences."""
        corpus = _build_corpus()
        src = tmp_path / "CLAUDE.md"
        src.write_text(corpus)
        vtbf = _compress(src, level="condense")

        src_count = len(_extract_bullets(corpus))
        out_count = len(_extract_bullets(_clean_vtbf(vtbf)))
        removed = src_count - out_count
        assert removed >= 8, (
            f"Expected ≥8 duplicate bullets removed; removed {removed} "
            f"(src={src_count}, out={out_count})"
        )

    def test_output_has_no_duplicate_bullets(self, tmp_path: Path) -> None:
        """After condense, every bullet in the output must be unique."""
        src = tmp_path / "CLAUDE.md"
        src.write_text(_build_corpus())
        vtbf = _compress(src, level="condense")
        out_bullets = _extract_bullets(_clean_vtbf(vtbf))
        assert len(out_bullets) == len(set(out_bullets)), (
            f"Output contains duplicate bullets: "
            f"{[b for b in out_bullets if out_bullets.count(b) > 1]}"
        )

    def test_normalize_does_not_remove_cross_section_duplicates(self, tmp_path: Path) -> None:
        """normalize must not deduplicate cross-section bullets — only condense should."""
        corpus = _build_corpus()
        src = tmp_path / "CLAUDE.md"
        src.write_text(corpus)
        vtbf = _compress(src, level="normalize")

        for fact in _SHARED_BULLETS:
            count = _bullet_occurrences(_clean_vtbf(vtbf), fact)
            assert count >= 2, (
                f"normalize incorrectly deduplicated shared bullet {fact!r} "
                f"(only {count} occurrence(s) — normalize must preserve all)"
            )


# ---------------------------------------------------------------------------
# 5. Information density
# ---------------------------------------------------------------------------


class TestInformationDensity:
    """Compressed output must pack more distinct facts per line than the source."""

    def test_condense_improves_information_density(self, tmp_path: Path) -> None:
        """
        After removing 8 duplicate bullets, the ratio of unique bullets to
        total content lines must be higher in the output than the source.
        """
        corpus = _build_corpus()
        src = tmp_path / "CLAUDE.md"
        src.write_text(corpus)
        vtbf = _compress(src, level="condense")

        src_density = _information_density(corpus)
        out_density = _information_density(vtbf)
        assert out_density > src_density, (
            f"Information density did not improve: "
            f"source={src_density:.3f}, output={out_density:.3f}"
        )

    def test_normalize_does_not_degrade_density(self, tmp_path: Path) -> None:
        """normalize only cleans whitespace — density must not substantially decrease."""
        corpus = _build_corpus()
        src = tmp_path / "CLAUDE.md"
        src.write_text(corpus)
        vtbf = _compress(src, level="normalize")

        src_density = _information_density(corpus)
        out_density = _information_density(vtbf)
        assert out_density >= src_density * 0.80, (
            f"normalize degraded information density: "
            f"source={src_density:.3f}, output={out_density:.3f}"
        )

    def test_aggressive_density_at_least_as_good_as_condense(self, tmp_path: Path) -> None:
        """aggressive removes filler prose without removing bullets → density at least as good."""
        src_agg = tmp_path / "agg.md"
        src_cond = tmp_path / "cond.md"
        src_agg.write_text(_build_corpus())
        src_cond.write_text(_build_corpus())

        dens_agg = _information_density(_compress(src_agg, "aggressive", allow_lossy=True))
        dens_cond = _information_density(_compress(src_cond, "condense"))
        assert dens_agg >= dens_cond * 0.90, (
            f"aggressive density ({dens_agg:.3f}) much lower than condense ({dens_cond:.3f})"
        )


# ---------------------------------------------------------------------------
# 6. Filler pruning (aggressive mode)
# ---------------------------------------------------------------------------


class TestFillerPruning:
    """aggressive must prune non-high-stakes prose from mutable sections."""

    def test_mutable_filler_pruned_in_aggressive(self, tmp_path: Path) -> None:
        """Filler sentences in mutable sections must be absent from aggressive output."""
        src = tmp_path / "CLAUDE.md"
        src.write_text(_build_corpus())
        vtbf = _compress(src, level="aggressive", allow_lossy=True)

        # FILLER[2] and FILLER[3] are in mutable sections
        mutable_filler = _FILLER[2:]
        surviving = [f for f in mutable_filler if f in vtbf]
        assert not surviving, (
            f"aggressive failed to prune {len(surviving)} mutable filler sentences:\n"
            + "\n".join(f"  - {f}" for f in surviving)
        )

    def test_condense_preserves_mutable_filler(self, tmp_path: Path) -> None:
        """condense must NOT prune prose — that is only aggressive's job."""
        src = tmp_path / "CLAUDE.md"
        src.write_text(_build_corpus())
        vtbf = _compress(src, level="condense")

        mutable_filler = _FILLER[2:]
        missing = [f for f in mutable_filler if f not in vtbf]
        assert not missing, (
            f"condense incorrectly pruned {len(missing)} prose sentence(s):\n"
            + "\n".join(f"  - {f}" for f in missing)
        )

    def test_aggressive_removes_more_filler_than_condense(self, tmp_path: Path) -> None:
        """Quantitative: aggressive must retain fewer filler sentences than condense."""
        src_agg = tmp_path / "agg.md"
        src_cond = tmp_path / "cond.md"
        src_agg.write_text(_build_corpus())
        src_cond.write_text(_build_corpus())

        all_filler = _FILLER[2:]  # only mutable filler
        agg_retained = sum(
            1 for f in all_filler if f in _compress(src_agg, "aggressive", allow_lossy=True)
        )
        cond_retained = sum(1 for f in all_filler if f in _compress(src_cond, "condense"))

        assert agg_retained < cond_retained, (
            f"aggressive retained {agg_retained} filler sentences vs condense {cond_retained} "
            "— aggressive should prune more"
        )

    def test_immutable_filler_always_preserved(self, tmp_path: Path) -> None:
        """Filler inside the immutable section must never be removed, even in aggressive mode."""
        src = tmp_path / "CLAUDE.md"
        src.write_text(_build_corpus())
        vtbf = _compress(src, level="aggressive", allow_lossy=True)

        for sentence in _FILLER[:2]:  # FILLER[0], FILLER[1] are in the immutable section
            assert sentence in vtbf, (
                f"Immutable section filler was incorrectly pruned:\n  {sentence!r}"
            )
