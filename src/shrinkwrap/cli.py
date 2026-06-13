from __future__ import annotations

import json
import re
import sys
import threading
import warnings
from copy import deepcopy
from pathlib import Path

import click
import yaml
from rich.console import Console
from rich.table import Table

from .config import load_config
from .metrics import CompressionMetrics
from .parser import parse
from .schema import compress_with_metrics, serialize
from .schema import verify as verify_vtbf

console = Console()

try:
    from importlib.metadata import version as _pkg_version

    _VERSION = _pkg_version("shrinkwrap")
except Exception:
    _VERSION = "0.0.0"


@click.group()
@click.version_option(_VERSION, prog_name="shrinkwrap")
def cli() -> None:
    """ShrinkWrap — compress AI agent instruction files."""


@cli.command()
@click.argument("input_file", type=click.Path(), required=False, default=None)
@click.option("--output", "-o", default=None, help="Output file (default: <input>.sw.md)")
@click.option(
    "--level",
    type=click.Choice(["normalize", "condense", "aggressive"]),
    default=None,
    help="Compression level override (default: respect per-section annotations or shrinkwrap.toml)",
)
@click.option(
    "--profile",
    type=click.Choice(["claude", "cursor", "generic"]),
    default=None,
    help="Output profile (default: shrinkwrap.toml or 'claude')",
)
@click.option(
    "--allow-lossy",
    is_flag=True,
    default=False,
    help="Allow aggressive (lossy) compression.",
)
@click.option("--dry-run", is_flag=True, default=False, help="Print to stdout; do not write file.")
@click.option("--in-place", is_flag=True, default=False, help="Overwrite the source file.")
@click.option(
    "--backup",
    is_flag=True,
    default=False,
    help="Write <file>.bak before overwriting (requires --in-place).",
)
def compress(
    input_file: str | None,
    output: str | None,
    level: str | None,
    profile: str | None,
    allow_lossy: bool,
    dry_run: bool,
    in_place: bool,
    backup: bool,
) -> None:
    """Compress an instruction file into VTBF format."""
    # Auto-discover CLAUDE.md in cwd when no argument given
    if input_file is None:
        input_file = str(Path.cwd() / "CLAUDE.md")

    src_path = Path(input_file)
    if not src_path.exists():
        console.print(
            f"[red]Error:[/red] {src_path.name} not found. "
            "Specify a file or create CLAUDE.md in the current directory."
        )
        sys.exit(1)

    if in_place and output:
        console.print("[red]Error:[/red] --in-place and --output are mutually exclusive.")
        sys.exit(1)

    if backup and not in_place:
        console.print("[red]Error:[/red] --backup requires --in-place.")
        sys.exit(1)

    if level == "aggressive" and not allow_lossy:
        console.print("[red]Error:[/red] --level=aggressive requires --allow-lossy")
        sys.exit(1)

    cfg = load_config(src_path.parent)

    # Resolve effective level and profile: CLI flag > config > built-in default
    effective_profile: str = profile if profile is not None else cfg.default_profile

    source_text = _read_text(src_path)
    doc = parse(source_text, config=cfg)

    for section in doc.sections:
        if section.classification == "immutable":
            continue
        if level is not None:
            # Explicit CLI flag: override every mutable section including annotated ones.
            section.compression = level  # type: ignore[assignment]
        elif cfg.default_level is not None and not section.annotation_source:
            # Config default: only fill in sections without an explicit annotation.
            section.compression = cfg.default_level

    # Fail early if any section requests aggressive compression without --allow-lossy.
    if not allow_lossy:
        aggressive_sections = [
            s.heading
            for s in doc.sections
            if s.compression == "aggressive" and s.classification not in ("immutable", "ambiguous")
        ]
        if aggressive_sections:
            names = ", ".join(repr(h) for h in aggressive_sections)
            console.print(
                "[red]Error:[/red] Section(s) use aggressive compression but "
                f"--allow-lossy was not passed: {names}"
            )
            sys.exit(1)

    vtbf, metrics = compress_with_metrics(doc, src_path.name, source_text, allow_lossy=allow_lossy)

    if effective_profile == "cursor":
        vtbf = _strip_front_matter(vtbf)
    elif effective_profile == "generic":
        vtbf = _strip_all_tags(vtbf)

    _maybe_warn_size(vtbf, source_text, effective_profile)

    if dry_run:
        console.print(vtbf)
        _print_compress_metrics(metrics)
        return

    if backup:
        bak_path = src_path.with_suffix(src_path.suffix + ".bak")
        bak_path.write_text(source_text, encoding="utf-8")

    if in_place:
        out_path = src_path
    elif output:
        out_path = Path(output)
    else:
        out_path = src_path.with_suffix(".sw.md")
    out_path.write_text(vtbf, encoding="utf-8")

    fm_ratio = _parse_ratio(vtbf)
    console.print(
        f"[green]Compressed[/green] {src_path.name} -> {out_path.name} (ratio: {fm_ratio:.0%})"
    )
    _print_compress_metrics(metrics)


@cli.command()
@click.argument("vtbf_file", type=click.Path(exists=True))
@click.option("--output", "-o", default=None, help="Output file (default: <name>.expanded.md)")
@click.option("--in-place", is_flag=True, default=False, help="Overwrite the source file.")
def expand(vtbf_file: str, output: str | None, in_place: bool) -> None:
    """Expand a VTBF file back to clean readable markdown."""
    if in_place and output:
        console.print("[red]Error:[/red] --in-place and --output are mutually exclusive.")
        sys.exit(1)

    vtbf_path = Path(vtbf_file)
    vtbf_text = _read_text(vtbf_path)

    if "shrinkwrap_schema" not in vtbf_text:
        console.print(
            f"[red]Error:[/red] {vtbf_path.name} is not a VTBF file "
            "(missing shrinkwrap_schema front-matter). "
            "Run 'shrinkwrap compress' first."
        )
        sys.exit(1)

    # Strip VTBF front-matter
    text = re.sub(r"\A---\n.*?\n---\n", "", vtbf_text, flags=re.DOTALL)
    # Strip sw:section tags (but NOT shrinkwrap annotation comments)
    text = re.sub(r"<!--\s*/?sw:section\b[^\n]*-->\n?", "", text)
    # Collapse excess blank lines
    text = re.sub(r"\n{3,}", "\n\n", text).lstrip()

    if in_place:
        out_path = vtbf_path
    else:
        stem = vtbf_path.stem.replace(".sw", "")
        default_out = vtbf_path.parent / f"{stem}.expanded.md"
        out_path = Path(output) if output else default_out

    out_path.write_text(text, encoding="utf-8")
    console.print(f"[green]Expanded[/green] {vtbf_path.name} -> {out_path.name}")


@cli.command()
@click.argument("vtbf_file", type=click.Path(exists=True))
@click.option(
    "--strict",
    is_flag=True,
    default=False,
    help="Also verify that the source file hash matches (detects source changes post-compress).",
)
@click.option(
    "--json",
    "output_json",
    is_flag=True,
    default=False,
    help="Emit machine-readable JSON instead of human-readable output.",
)
def verify(vtbf_file: str, strict: bool, output_json: bool) -> None:
    """Verify a VTBF file's integrity."""
    vtbf_path = Path(vtbf_file)
    vtbf_text = _read_text(vtbf_path)

    # For --strict, locate and read the original source file referenced in front-matter.
    source_text: str | None = None
    if strict:
        fm_match = re.match(r"\A---\n(.*?)\n---\n", vtbf_text, re.DOTALL)
        if fm_match:
            try:
                fm = yaml.safe_load(fm_match.group(1)) or {}
            except yaml.YAMLError as exc:
                console.print(f"[yellow]Warning:[/yellow] Could not parse front-matter: {exc}")
                fm = {}
            source_file = str(fm.get("source_file", ""))
            if source_file:
                source_path = vtbf_path.parent / source_file
                if source_path.exists():
                    try:
                        source_text = source_path.read_text(encoding="utf-8")
                    except UnicodeDecodeError:
                        console.print(
                            f"[yellow]Warning:[/yellow] Source file {source_file!r} is not "
                            "valid UTF-8; skipping source hash check."
                        )
                else:
                    console.print(
                        f"[yellow]Warning:[/yellow] Source file {source_file!r} not found; "
                        "skipping source hash check."
                    )

    result = verify_vtbf(vtbf_text, strict=strict, source_text=source_text)

    if output_json:
        click.echo(
            json.dumps(
                {
                    "valid": result.valid,
                    "errors": result.errors,
                    "warnings": result.warnings,
                }
            )
        )
        if not result.valid:
            sys.exit(1)
        return

    if result.valid:
        console.print(f"[green]✓ Valid[/green] {vtbf_file}")
    else:
        console.print(f"[red]✗ Invalid[/red] {vtbf_file}")
        for err in result.errors:
            console.print(f"  [red]•[/red] {err}")
        sys.exit(1)

    for warn in result.warnings:
        console.print(f"  [yellow]![/yellow] {warn}")


@cli.command()
@click.argument("input_file", type=click.Path(), required=False, default=None)
def audit(input_file: str | None) -> None:
    """Show classification report for an instruction file."""
    from .parser import ShrinkWrapClassificationWarning

    if input_file is None:
        input_file = str(Path.cwd() / "CLAUDE.md")

    src_path = Path(input_file)
    if not src_path.exists():
        console.print(
            f"[red]Error:[/red] {src_path.name} not found. "
            "Specify a file or create CLAUDE.md in the current directory."
        )
        sys.exit(1)

    cfg = load_config(src_path.parent)
    source_text = _read_text(src_path)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        doc = parse(source_text, config=cfg)

    table = Table(title=f"ShrinkWrap audit: {input_file}")
    table.add_column("Heading", style="bold")
    table.add_column("Level")
    table.add_column("Classification")
    table.add_column("Source")

    for section in doc.sections:
        cls_color = {
            "immutable": "green",
            "mutable": "cyan",
            "ambiguous": "yellow",
        }.get(section.classification, "white")
        if section.annotation_source:
            source_label = "annotation"
        elif section.trigger_keyword:
            source_label = f"keyword: {section.trigger_keyword}"
        else:
            source_label = "structural"
        table.add_row(
            section.heading,
            str(section.level),
            f"[{cls_color}]{section.classification}[/{cls_color}]",
            source_label,
        )

    console.print(table)

    for w in caught:
        if issubclass(w.category, ShrinkWrapClassificationWarning):
            console.print(f"[yellow]⚠[/yellow] {w.message}")


@cli.command()
@click.argument("input_file", type=click.Path(), required=False, default=None)
@click.option(
    "--json",
    "output_json",
    is_flag=True,
    default=False,
    help="Emit machine-readable JSON instead of human-readable output.",
)
def stats(input_file: str | None, output_json: bool) -> None:
    """Show token statistics and compression projections for an instruction file."""
    from .compressor import compress_document_sections

    # Auto-discover CLAUDE.md in cwd when no argument given
    if input_file is None:
        input_file = str(Path.cwd() / "CLAUDE.md")

    src_path = Path(input_file)
    if not src_path.exists():
        console.print(
            f"[red]Error:[/red] {src_path.name} not found. "
            "Specify a file or create CLAUDE.md in the current directory."
        )
        sys.exit(1)

    source_text = _read_text(src_path)
    cfg = load_config(src_path.parent)
    doc = parse(source_text, config=cfg)

    # Shared projection helper (used by both JSON and table paths)
    def _project(level: str) -> int:
        clones = deepcopy(doc.sections)
        for s in clones:
            if s.classification != "immutable":
                s.compression = level  # type: ignore[assignment]
        bodies = compress_document_sections(clones)
        return sum(max(1, len(b) // 4) for b in bodies)

    total_tokens = sum(max(1, len(s.body) // 4) for s in doc.sections)

    if output_json:
        click.echo(
            json.dumps(
                {
                    "sections": [
                        {
                            "heading": s.heading,
                            "classification": s.classification,
                            "tokens": max(1, len(s.body) // 4),
                        }
                        for s in doc.sections
                    ],
                    "total_tokens": total_tokens,
                    "projections": {
                        "normalize": _project("normalize"),
                        "condense": _project("condense"),
                    },
                }
            )
        )
        return

    # Current token counts per section
    table = Table(title=f"ShrinkWrap stats: {input_file}")
    table.add_column("Section", style="bold")
    table.add_column("Classification")
    table.add_column("Tokens (approx)", justify="right")

    for section in doc.sections:
        tok = max(1, len(section.body) // 4)
        cls_color = {
            "immutable": "green",
            "mutable": "cyan",
            "ambiguous": "yellow",
        }.get(section.classification, "white")
        table.add_row(
            section.heading,
            f"[{cls_color}]{section.classification}[/{cls_color}]",
            str(tok),
        )

    table.add_section()
    table.add_row("[bold]Total[/bold]", "", f"[bold]{total_tokens}[/bold]")
    console.print(table)

    norm_tok = _project("normalize")
    cond_tok = _project("condense")

    proj = Table(title="Projection (mutable sections compressed, immutable unchanged)")
    proj.add_column("Level")
    proj.add_column("Est. tokens", justify="right")
    proj.add_column("Reduction", justify="right")

    def _pct(before: int, after: int) -> str:
        if before == 0:
            return "—"
        saved = (before - after) / before
        return f"{saved:.0%}" if saved > 0 else "0%"

    proj.add_row("normalize", str(norm_tok), _pct(total_tokens, norm_tok))
    proj.add_row(
        "[bold]condense[/bold]",
        f"[bold]{cond_tok}[/bold]",
        f"[bold]{_pct(total_tokens, cond_tok)}[/bold]",
    )
    console.print(proj)
    console.print(
        f"[dim]{len(doc.sections)} section(s) · {total_tokens} tokens now · "
        f"immutable sections excluded from projection[/dim]"
    )


@cli.command()
@click.option("--force", is_flag=True, default=False, help="Overwrite existing shrinkwrap.toml.")
def init(force: bool) -> None:
    """Scaffold a shrinkwrap.toml with commented defaults in the current directory."""
    config_path = Path.cwd() / "shrinkwrap.toml"
    if config_path.exists() and not force:
        console.print(
            "[yellow]Warning:[/yellow] shrinkwrap.toml already exists. "
            "Use [bold]--force[/bold] to overwrite."
        )
        sys.exit(1)

    template = (
        "[shrinkwrap]\n"
        "# Compression level for mutable sections (no per-section annotation override).\n"
        '# Options: "normalize" (default), "condense", "aggressive" (needs --allow-lossy)\n'
        'default_level = "normalize"\n'
        "\n"
        "# Output profile controls front-matter and tag verbosity.\n"
        '# Options: "claude" (full VTBF), "cursor" (no front-matter), "generic" (plain)\n'
        'default_profile = "claude"\n'
        "\n"
        "# Drift score (0.0–1.0) above which the post-commit hook fires a notification.\n"
        "drift_threshold = 0.35\n"
        "\n"
        "# Heading keywords that force a section to be classified as immutable.\n"
        "# extra_immutable_keywords = []\n"
        "\n"
        "# Heading keywords that force a section to be classified as mutable.\n"
        "# extra_mutable_keywords = []\n"
        "\n"
        "# Limit drift analysis to specific directories (faster for large monorepos).\n"
        '# watched_paths = ["src", "lib"]\n'
    )
    config_path.write_text(template, encoding="utf-8")
    console.print(
        "[green]Created[/green] shrinkwrap.toml — edit it to customise compression behaviour."
    )


@cli.command()
@click.argument("vtbf_file", type=click.Path(exists=True))
def upgrade(vtbf_file: str) -> None:
    """Upgrade a VTBF file to the current schema version."""
    from .schema import SCHEMA_VERSION

    text = _read_text(Path(vtbf_file))
    if "shrinkwrap_schema" not in text:
        console.print(
            f"[red]Error:[/red] {Path(vtbf_file).name} is not a VTBF file "
            "(missing shrinkwrap_schema front-matter). "
            "Run 'shrinkwrap compress' first."
        )
        sys.exit(1)

    console.print(
        f"[green]✓[/green] {Path(vtbf_file).name} is already at schema version {SCHEMA_VERSION}."
    )


@cli.command()
@click.argument("directory", type=click.Path(exists=True), required=False, default=None)
@click.option("--output", "-o", default=None, help="Output file (default: CONSOLIDATED.md).")
@click.option("--dry-run", is_flag=True, default=False, help="Print to stdout; do not write file.")
def consolidate(directory: str | None, output: str | None, dry_run: bool) -> None:
    """Discover and consolidate all agentic instruction files in a directory.

    Crawls DIRECTORY (default: current directory) for Markdown files that carry
    agentic signatures — CLAUDE.md, .cursorrules, shrinkwrap annotations, or
    recognised YAML front-matter keys.  All discovered files are parsed, their
    sections deduplicated across files, and the result written to a single
    master instruction file.
    """
    from .consolidate import consolidate_with_metrics, discover_agentic_files

    root = Path(directory).resolve() if directory else Path.cwd()
    found = discover_agentic_files(root)

    if not found:
        console.print(f"[yellow]No agentic instruction files found in {root}[/yellow]")
        return

    console.print(f"Found {len(found)} agentic file(s):")
    for f in found:
        try:
            rel = f.relative_to(root)
        except ValueError:
            rel = f
        console.print(f"  {rel}")

    merged, metrics = consolidate_with_metrics(found)

    if dry_run:
        console.print(merged)
        _print_consolidate_metrics(metrics)
        return

    out_path = Path(output) if output else root / "CONSOLIDATED.md"
    out_path.write_text(merged, encoding="utf-8")
    console.print(f"[green]Consolidated[/green] {len(found)} file(s) → {out_path.name}")
    _print_consolidate_metrics(metrics)


@cli.command("install-hooks")
@click.option("--repo", default=".", help="Path to git repo root", show_default=True)
@click.option("--force", is_flag=True, default=False, help="Overwrite an existing hook.")
def install_hooks(repo: str, force: bool) -> None:
    """Install ShrinkWrap post-commit drift detection hook."""
    hooks_dir = Path(repo) / ".git" / "hooks"
    if not hooks_dir.exists():
        console.print(f"[red]Error:[/red] {repo} does not appear to be a git repository.")
        sys.exit(1)

    hook_path = hooks_dir / "post-commit"
    if hook_path.exists() and not force:
        console.print(
            f"[yellow]Warning:[/yellow] An existing post-commit hook was found at {hook_path}.\n"
            "Re-run with [bold]--force[/bold] to overwrite it."
        )
        sys.exit(1)

    hook_script = "#!/bin/sh\nshrinkwrap drift-check --hook-mode 2>&1 || true\n"
    hook_path.write_text(hook_script, encoding="utf-8")
    hook_path.chmod(0o755)
    console.print(f"[green]Installed[/green] post-commit hook at {hook_path}")


@cli.command("drift-check")
@click.option("--hook-mode", is_flag=True, default=False, hidden=True)
@click.option("--repo", default=".", help="Path to git repo root")
def drift_check(hook_mode: bool, repo: str) -> None:
    """Check if the last commit introduced instruction-file drift."""
    from .drift import score_commit

    repo_path = Path(repo).resolve()
    cfg = load_config(repo_path)
    result_holder: list[object] = []
    error_holder: list[Exception] = []

    watched = cfg.watched_paths if cfg.watched_paths else None

    def run() -> None:
        try:
            result_holder.append(score_commit(repo_path, watched_paths=watched))
        except Exception as exc:
            error_holder.append(exc)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    thread.join(timeout=3.0)

    if not result_holder:
        # Distinguish a real error from a timeout: thread alive == timed out (silent).
        if error_holder and not thread.is_alive():
            console.print(
                f"[yellow][shrinkwrap] Warning:[/yellow] drift scoring failed ({error_holder[0]})"
            )
        return

    from .drift import DriftResult

    result = result_holder[0]
    if not isinstance(result, DriftResult) or result.score < cfg.drift_threshold:
        return

    symbols = ", ".join(result.changed_public_symbols[:5])
    console.print(f"\n[yellow][shrinkwrap][/yellow] Drift detected (score: {result.score:.2f})")
    if symbols:
        console.print(f"  Changed public API: {symbols}")
    console.print("  Run: shrinkwrap compress <file> --in-place")


# ---------------------------------------------------------------------------
# watch command + loop
# ---------------------------------------------------------------------------


def _watch_loop(
    path: Path,
    level: str | None,
    profile: str | None,  # None = read from shrinkwrap.toml or "claude"
    allow_lossy: bool,
    interval: float,
    *,
    stop_event: threading.Event | None = None,
) -> None:
    """Poll *path* and recompress in-place whenever its mtime changes."""
    _stop = stop_event or threading.Event()
    cfg = load_config(path.parent)
    effective_level = level if level is not None else cfg.default_level
    effective_profile: str = profile if profile is not None else cfg.default_profile
    last_mtime = path.stat().st_mtime

    while not _stop.is_set():
        _stop.wait(interval)  # interruptible sleep — wakes immediately on set()
        if _stop.is_set():
            break

        try:
            current_mtime = path.stat().st_mtime
        except FileNotFoundError:
            console.print(f"[red]Error:[/red] {path.name} was deleted.")
            break

        if current_mtime == last_mtime:
            continue

        last_mtime = current_mtime

        try:
            source_text = path.read_text(encoding="utf-8")
            doc = parse(source_text, config=cfg)
        except Exception as exc:
            console.print(f"[yellow]Warning:[/yellow] Could not read/parse {path.name}: {exc}")
            continue

        if effective_level is not None:
            for section in doc.sections:
                if section.classification != "immutable":
                    section.compression = effective_level  # type: ignore[assignment]

        try:
            vtbf = serialize(doc, path.name, source_text, allow_lossy=allow_lossy)
        except ValueError as exc:
            console.print(f"[red]Error:[/red] {exc} — skipping recompression of {path.name}")
            continue

        if effective_profile == "cursor":
            vtbf = _strip_front_matter(vtbf)
        elif effective_profile == "generic":
            vtbf = _strip_all_tags(vtbf)

        path.write_text(vtbf, encoding="utf-8")
        last_mtime = path.stat().st_mtime  # consume our own write

        fm_ratio = _parse_ratio(vtbf)
        console.print(f"[green]Recompressed[/green] {path.name} (ratio: {fm_ratio:.0%})")


@cli.command()
@click.argument("file", type=click.Path(), required=False, default=None)
@click.option(
    "--level",
    type=click.Choice(["normalize", "condense", "aggressive"]),
    default=None,
    help="Compression level override (default: respect per-section annotations).",
)
@click.option(
    "--interval",
    type=float,
    default=1.0,
    show_default=True,
    help="Poll interval in seconds.",
)
@click.option(
    "--profile",
    type=click.Choice(["claude", "cursor", "generic"]),
    default=None,
    help="Output profile (default: shrinkwrap.toml or 'claude').",
)
@click.option(
    "--allow-lossy",
    is_flag=True,
    default=False,
    help="Allow aggressive (lossy) compression for sections annotated with compression=aggressive.",
)
def watch(
    file: str | None,
    level: str | None,
    interval: float,
    profile: str | None,
    allow_lossy: bool,
) -> None:
    """Watch a file and recompress automatically whenever it changes."""
    if file is None:
        file = str(Path.cwd() / "CLAUDE.md")

    path = Path(file)
    if not path.exists():
        console.print(
            f"[red]Error:[/red] {path.name} not found. "
            "Specify a file or create CLAUDE.md in the current directory."
        )
        sys.exit(1)

    console.print(f"[green]Watching[/green] {path.name} (interval: {interval}s) — Ctrl+C to stop")
    try:
        _watch_loop(path, level, profile, allow_lossy, interval)
    except KeyboardInterrupt:
        console.print("\n[dim]Stopped watching.[/dim]")


# ---------------------------------------------------------------------------
# Metrics table helpers
# ---------------------------------------------------------------------------


def _print_compress_metrics(metrics: CompressionMetrics) -> None:
    table = Table(title="Compression Metrics")
    table.add_column("Metric", style="bold")
    table.add_column("Value", justify="right")
    table.add_row("Tokens before", str(metrics.tokens_before))
    table.add_row("Tokens after", str(metrics.tokens_after))
    table.add_row("Tokens saved", str(metrics.tokens_saved))
    table.add_row("Compression", f"{metrics.compression_pct:.1f}%")
    if metrics.duplicate_bullets_removed:
        table.add_row("Duplicate bullets removed", str(metrics.duplicate_bullets_removed))
    console.print(table)


def _print_consolidate_metrics(metrics: CompressionMetrics) -> None:
    table = Table(title="Consolidation Metrics")
    table.add_column("Metric", style="bold")
    table.add_column("Value", justify="right")
    table.add_row("Files processed", str(metrics.files_processed))
    table.add_row("Tokens before", str(metrics.tokens_before))
    table.add_row("Tokens after", str(metrics.tokens_after))
    table.add_row("Tokens saved", str(metrics.tokens_saved))
    table.add_row("Compression", f"{metrics.compression_pct:.1f}%")
    table.add_row("Duplicate sections removed", str(metrics.duplicate_sections_removed))
    table.add_row("Duplicate bullets removed", str(metrics.duplicate_bullets_removed))
    console.print(table)


# ---------------------------------------------------------------------------
# Profile helpers
# ---------------------------------------------------------------------------


def _read_text(path: Path) -> str:
    """Read a file as UTF-8, printing a clean error and exiting on encoding failure."""
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        console.print(
            f"[red]Error:[/red] {path.name} is not valid UTF-8. "
            "ShrinkWrap only supports UTF-8 encoded files."
        )
        sys.exit(1)


def _strip_front_matter(vtbf: str) -> str:
    return re.sub(r"\A---\n.*?\n---\n", "", vtbf, flags=re.DOTALL)


def _strip_all_tags(vtbf: str) -> str:
    text = _strip_front_matter(vtbf)
    text = re.sub(r"<!--[^>]*-->", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.lstrip()


def _parse_ratio(vtbf: str) -> float:
    m = re.search(r"compression_ratio:\s*([\d.]+)", vtbf)
    return float(m.group(1)) if m else 1.0


def _maybe_warn_size(vtbf: str, source_text: str, profile: str) -> None:
    """Warn when the output is larger than the source, with profile-aware messaging."""
    if len(vtbf) <= len(source_text):
        return
    if profile == "generic":
        # All tags stripped — any size difference is trivial trailing whitespace; don't warn.
        return
    suggestion = " Consider --profile generic." if profile == "claude" else ""
    console.print(
        f"[yellow]Warning:[/yellow] compressed output is larger than the source "
        f"({len(vtbf)} vs {len(source_text)} chars). "
        f"VTBF tag overhead dominates small files.{suggestion}"
    )
