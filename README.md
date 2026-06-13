# ShrinkWrap

Compress AI agent instruction files (CLAUDE.md, .cursorrules, system prompts) into a
token-optimized format without losing meaning. Keeps security rules and architecture
constraints byte-identical while compressing volatile status/todo sections.

```
$ shrinkwrap stats CLAUDE.md
┌─────────────────────────────────────────────┐
│ Section              │ Class     │ Tokens    │
│ Security Rules       │ immutable │ 312       │
│ Architecture         │ immutable │ 198       │
│ Current Sprint       │ mutable   │ 847       │
│ Todo                 │ mutable   │ 423       │
│ Total                │           │ 1780      │
└─────────────────────────────────────────────┘

$ shrinkwrap compress CLAUDE.md --level condense --in-place
Compressed CLAUDE.md (ratio: 61%)
```

## Installation

```bash
pip install shrinkwrap
```

Requires Python 3.11+.

## Quick start

```bash
# See what's in your instruction file and how it's classified
shrinkwrap audit CLAUDE.md

# Compress in-place (replaces CLAUDE.md with the compressed version)
shrinkwrap compress CLAUDE.md --in-place

# Preview without writing anything
shrinkwrap compress CLAUDE.md --dry-run

# Install a git hook that alerts you when your code drifts from your instructions
shrinkwrap install-hooks
```

## Performance

<!-- perf-section-start -->
The numbers below are measured by the efficacy test suite on a controlled corpus: 8 sections (1 immutable, 3 mutable), 8 unique facts, 5 safety rules, and 8 status bullets duplicated across all 3 mutable sections.

| Metric | `normalize` | `condense` | `aggressive` |
|---|---|---|---|
| Token reduction | 0%† | 17% | 26% |
| Information density improvement | — | +38% | +53% |
| Safety rule preservation | **5/5** (100%) | **5/5** (100%) | **5/5** (100%) |
| Unique fact survival | **8/8** (100%) | **8/8** (100%) | **8/8** (100%) |
| Duplicate bullets removed | 0 / 8 | 8 / 8 | 8 / 8 |

† `normalize` removes whitespace noise only — zero reduction on an already-clean file.

**Information density** is the ratio of unique facts to total content lines. On the test corpus, removing 8 redundant status bullets raised the density from 41% to 57% under `condense` — the model receives the same information in fewer tokens.

**Safety rules and constraints** in `immutable` sections are never modified regardless of level. The 100% preservation rate is enforced structurally: immutable sections are excluded from all compression passes and their content is verified by SHA-256 checksum in the output file.

Real-world savings depend on how much duplicate and filler content your instruction file contains. Files with many repeated status bullets across sections benefit most from `condense`; files with dense filler prose benefit additionally from `aggressive`.
<!-- perf-section-end -->

## Commands

### `compress`

```
shrinkwrap compress <file> [options]
```

| Option | Default | Description |
|--------|---------|-------------|
| `--level` | *(annotation)* | `normalize`, `condense`, or `aggressive` |
| `--in-place` | off | Overwrite the source file instead of creating `<file>.sw.md` |
| `--output / -o` | `<file>.sw.md` | Custom output path (mutually exclusive with `--in-place`) |
| `--profile` | `claude` | `claude` (full tags), `cursor` (no front-matter), `generic` (no tags) |
| `--allow-lossy` | off | Required for `--level aggressive` |
| `--dry-run` | off | Print to stdout; do not write file |

**Compression levels**

| Level | What it does | Token savings | Semantic loss |
|-------|-------------|--------------|--------------|
| `normalize` | Whitespace cleanup, adjacent duplicate bullets removed | ~10–20% | None |
| `condense` | `normalize` + removes bullets that appear in multiple sections | ~25–40% | Minimal |
| `aggressive` | `condense` + drops low-value prose (requires `--allow-lossy`) | ~40–60% | Moderate |

Immutable sections (security rules, architecture) are never touched beyond whitespace normalization regardless of level.

### `stats`

```
shrinkwrap stats <file>
```

Shows each section, its classification (immutable/mutable), and approximate token count. Use this to decide which level to apply before compressing.

### `audit`

```
shrinkwrap audit <file>
```

Classification report: shows each section, its heading level, how it was classified (annotation vs heuristic), and the classification result. Use this when the compressor is doing something unexpected.

### `verify`

```
shrinkwrap verify <file.sw.md> [--strict]
```

Verifies a compressed file's integrity. Checks schema version and validates checksums on immutable sections. Use `--strict` in CI to also verify the source file hash hasn't changed.

### `expand`

```
shrinkwrap expand <file.sw.md> [-o output.md]
```

Strips all VTBF tags and front-matter to produce clean readable markdown. Useful for diffing or sharing.

### `install-hooks`

```
shrinkwrap install-hooks [--repo .]
```

Installs a post-commit hook that runs `shrinkwrap drift-check` after every commit. When your code changes public API, you get a notification that your instruction file may need updating.

### `drift-check`

```
shrinkwrap drift-check [--repo .]
```

Scores how much the last commit drifted from what your instruction file describes. Uses AST diffing on Python files (stdlib `ast` — no extra dependencies) so internal refactors produce zero signal.

## Controlling classification with annotations

By default ShrinkWrap classifies sections using heading text heuristics. Override with an HTML comment on the line immediately preceding the heading:

```markdown
<!-- shrinkwrap: immutable -->
## Architecture Decisions
Content here is never compressed beyond whitespace normalization.

<!-- shrinkwrap: mutable compression=condense -->
## Current Sprint
This section will always use condense level regardless of the --level flag.
```

**Annotation compression is respected** — `--level` only applies to sections without explicit annotations.

## YAML front-matter configuration

```yaml
---
shrinkwrap:
  immutable_sections:
    - My Custom Section   # force immutable by heading text
  mutable_sections:
    - Another Section     # force mutable by heading text
---
```

## `shrinkwrap.toml`

Project-level defaults (place in the repo root):

```toml
[shrinkwrap]
default_level = "condense"
default_profile = "claude"
drift_threshold = 0.35

# Restrict drift detection to these paths (faster on large repos)
watched_paths = ["src/"]

# Extend the keyword classifier
extra_immutable_keywords = ["invariant", "contract"]
extra_mutable_keywords = ["backlog", "icebox"]
```

## Output format (VTBF)

Compressed files are valid markdown with machine-readable metadata in HTML comments. The comments are invisible to rendered markdown but let ShrinkWrap re-compress, verify, and diff files reliably.

```
---
shrinkwrap_schema: "1.0"
source_file: "CLAUDE.md"
source_sha256: "a3f8b2c1..."
compressed_at: "2026-06-12T00:00:00Z"
compression_ratio: 0.61
total_tokens_approx: 1087
---

<!-- sw:section id="security-rules" class="immutable" checksum="b4d2e1f3..." -->
## Security Rules
Never use eval(). Always validate input at system boundaries.
<!-- /sw:section -->

<!-- sw:section id="current-sprint" class="mutable" compression="condense" original_tokens=847 compressed_tokens=312 -->
## Current Sprint
- deploy pipeline fix
- auth refactor
<!-- /sw:section -->
```

## License

MIT
