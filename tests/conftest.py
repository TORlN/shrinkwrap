from __future__ import annotations

import re
import tempfile
from pathlib import Path

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--update-readme",
        action="store_true",
        default=False,
        help="After the session, regenerate the performance section in README.md.",
    )


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    if not session.config.getoption("--update-readme", default=False):
        return
    if exitstatus != 0:
        session.config.pluginmanager.get_plugin("terminalreporter").write_line(
            "\n[update-readme] Skipped — test suite did not pass cleanly.",
            yellow=True,
        )
        return
    _regenerate_perf_section(session)


# ---------------------------------------------------------------------------
# Metric computation — mirrors test_efficacy.py corpus exactly
# ---------------------------------------------------------------------------

_MUST_SURVIVE = [
    "Never use eval() or exec() with user-supplied input.",
    "Always validate all input at system boundaries.",
    "Forbidden: committing secrets, API keys, or credentials to the repository.",
    "Must not use MD5 or SHA1 for cryptographic hashing.",
    "Do not store plaintext passwords under any circumstances.",
]
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
_SHARED_BULLETS = [
    "tests are passing",
    "main branch is protected",
    "deploy is pending review",
    "documentation is up to date",
]
_FILLER = [
    "This section provides context for the development team.",
    "Please review the following items at your convenience.",
    "The information below has been compiled from various sources.",
    "Additional context may be found in the project wiki.",
]


def _bul(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items)


def _build_corpus() -> str:
    return (
        "\n\n".join(
            [
                (
                    "<!-- shrinkwrap: immutable -->\n## Security Rules\n"
                    + "\n".join(_MUST_SURVIVE)
                    + "\n"
                    + "\n".join(_FILLER[:2])
                ),
                (
                    "<!-- shrinkwrap: mutable compression=condense -->\n## Sprint Status\n"
                    + _bul(_UNIQUE_FACTS[:3])
                    + "\n"
                    + _bul(_SHARED_BULLETS)
                    + "\n"
                    + _FILLER[2]
                ),
                (
                    "<!-- shrinkwrap: mutable compression=condense -->\n## Architecture Notes\n"
                    + _bul(_UNIQUE_FACTS[3:6])
                    + "\n"
                    + _bul(_SHARED_BULLETS)
                    + "\n"
                    + _FILLER[3]
                ),
                (
                    "<!-- shrinkwrap: mutable compression=condense -->\n## Operations\n"
                    + _bul(_UNIQUE_FACTS[6:])
                    + "\n"
                    + _bul(_SHARED_BULLETS)
                ),
            ]
        )
        + "\n"
    )


def _extract_bullets(text: str) -> list[str]:
    clean = re.sub(r"\A---\n.*?\n---\n", "", text, flags=re.DOTALL)
    clean = re.sub(r"<!--[^\n]*-->\n?", "", clean)
    return [
        re.sub(r"^\s*[-*+]\s+", "", ln).strip()
        for ln in clean.splitlines()
        if re.match(r"^\s*[-*+]\s+", ln)
    ]


def _density(text: str) -> float:
    clean = re.sub(r"\A---\n.*?\n---\n", "", text, flags=re.DOTALL)
    clean = re.sub(r"<!--[^\n]*-->\n?", "", clean)
    content = [ln for ln in clean.splitlines() if ln.strip() and not ln.startswith("#")]
    unique = set(_extract_bullets(text))
    return len(unique) / len(content) if content else 0.0


def _measure(level: str, allow_lossy: bool = False) -> dict[str, object]:
    import yaml
    from click.testing import CliRunner

    from shrinkwrap.cli import cli

    corpus = _build_corpus()
    with tempfile.TemporaryDirectory() as d:
        src = Path(d) / "CLAUDE.md"
        src.write_text(corpus, encoding="utf-8")
        args = ["compress", str(src), "--level", level]
        if allow_lossy:
            args.append("--allow-lossy")
        result = CliRunner().invoke(cli, args)
        if result.exit_code != 0:
            raise RuntimeError(f"compress failed for level={level}: {result.output}")
        vtbf = src.with_suffix(".sw.md").read_text(encoding="utf-8")

    m = re.match(r"\A---\n(.*?)\n---\n", vtbf, re.DOTALL)
    fm = yaml.safe_load(m.group(1)) if m else {}

    src_bullets = _extract_bullets(corpus)
    out_bullets = _extract_bullets(vtbf)
    src_dens = _density(corpus)
    out_dens = _density(vtbf)

    ratio = float(fm.get("compression_ratio", 1.0))
    reduction_pct = round((1.0 - ratio) * 100)
    density_improvement_pct = round((out_dens - src_dens) / src_dens * 100) if src_dens else 0

    src_dup_count = len(src_bullets) - len(set(src_bullets))
    out_dup_count = len(out_bullets) - len(set(out_bullets))
    removed_dups = src_dup_count - out_dup_count

    return {
        "reduction_pct": reduction_pct,
        "density_improvement_pct": density_improvement_pct,
        "src_density_pct": round(src_dens * 100),
        "out_density_pct": round(out_dens * 100),
        "rules_survived": sum(1 for r in _MUST_SURVIVE if r in vtbf),
        "rules_total": len(_MUST_SURVIVE),
        "facts_survived": sum(1 for f in _UNIQUE_FACTS if f in vtbf),
        "facts_total": len(_UNIQUE_FACTS),
        "dups_removed": removed_dups,
        "dups_total": src_dup_count,
    }


def _build_perf_section(metrics: dict[str, dict[str, object]]) -> str:
    n = metrics["normalize"]
    c = metrics["condense"]
    a = metrics["aggressive"]

    def pct(val: object) -> str:
        v = int(val)  # type: ignore[arg-type]
        return f"{v}%" if v else "0%†"

    def density_delta(val: object) -> str:
        v = int(val)  # type: ignore[arg-type]
        return f"+{v}%" if v > 0 else "—"

    def preserve(survived: object, total: object) -> str:
        return f"**{survived}/{total}** (100%)" if survived == total else f"{survived}/{total}"

    def dups(removed: object, total: object) -> str:
        return f"{removed} / {total}"

    rows = [
        (
            "Token reduction",
            pct(n["reduction_pct"]),
            pct(c["reduction_pct"]),
            pct(a["reduction_pct"]),
        ),
        (
            "Information density improvement",
            density_delta(n["density_improvement_pct"]),
            density_delta(c["density_improvement_pct"]),
            density_delta(a["density_improvement_pct"]),
        ),
        (
            "Safety rule preservation",
            preserve(n["rules_survived"], n["rules_total"]),
            preserve(c["rules_survived"], c["rules_total"]),
            preserve(a["rules_survived"], a["rules_total"]),
        ),
        (
            "Unique fact survival",
            preserve(n["facts_survived"], n["facts_total"]),
            preserve(c["facts_survived"], c["facts_total"]),
            preserve(a["facts_survived"], a["facts_total"]),
        ),
        (
            "Duplicate bullets removed",
            dups(n["dups_removed"], n["dups_total"]),
            dups(c["dups_removed"], c["dups_total"]),
            dups(a["dups_removed"], a["dups_total"]),
        ),
    ]
    table = "| Metric | `normalize` | `condense` | `aggressive` |\n|---|---|---|---|\n"
    table += "".join(f"| {r[0]} | {r[1]} | {r[2]} | {r[3]} |\n" for r in rows)

    c_src = int(c["src_density_pct"])
    c_out = int(c["out_density_pct"])

    shared_bullet_count = len(_SHARED_BULLETS)
    return (
        "The numbers below are measured by the efficacy test suite on a controlled corpus: "
        f"4 sections (1 immutable, 3 mutable), {c['facts_total']} unique facts, "
        f"{c['rules_total']} safety rules, and {shared_bullet_count} status bullets duplicated "
        "across all 3 mutable sections.\n"
        "\n" + table + "\n"
        "† `normalize` removes whitespace noise only — zero reduction on an already-clean file.\n"
        "\n"
        "**Information density** is the ratio of unique facts to total content lines. "
        f"On the test corpus, removing {c['dups_removed']} redundant status bullets raised "
        f"the density from {c_src}% to {c_out}% under `condense` — "
        "the model receives the same information in fewer tokens.\n"
        "\n"
        "**Safety rules and constraints** in `immutable` sections are never modified regardless "
        "of level. The 100% preservation rate is enforced structurally: immutable sections are "
        "excluded from all compression passes and their content is verified by SHA-256 checksum "
        "in the output file.\n"
        "\n"
        "Real-world savings depend on how much duplicate and filler content your instruction "
        "file contains. Files with many repeated status bullets across sections benefit most "
        "from `condense`; files with dense filler prose benefit additionally from `aggressive`."
    )


def _regenerate_perf_section(session: pytest.Session) -> None:
    reporter = session.config.pluginmanager.get_plugin("terminalreporter")
    readme = Path(__file__).parent.parent / "README.md"
    if not readme.exists():
        reporter.write_line("[update-readme] README.md not found — skipped.", yellow=True)
        return

    reporter.write_line("\n[update-readme] Measuring compression metrics...", bold=True)
    try:
        metrics = {
            "normalize": _measure("normalize"),
            "condense": _measure("condense"),
            "aggressive": _measure("aggressive", allow_lossy=True),
        }
    except Exception as exc:
        reporter.write_line(f"[update-readme] Measurement failed: {exc}", red=True)
        return

    new_body = _build_perf_section(metrics)
    original = readme.read_text(encoding="utf-8")
    updated = re.sub(
        r"(<!-- perf-section-start -->).*?(<!-- perf-section-end -->)",
        rf"\1\n{new_body}\n\2",
        original,
        flags=re.DOTALL,
    )

    if updated == original:
        reporter.write_line("[update-readme] README.md already up to date.", green=True)
        return

    readme.write_text(updated, encoding="utf-8")
    reporter.write_line("[update-readme] README.md performance section updated.", green=True)
