"""Tests for 'shrinkwrap consolidate' — multi-file auto-discovery and consolidation.

All tests in this file are RED until the consolidate command and its engine are implemented.
"""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from shrinkwrap.cli import cli

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Auto-discovery: is_agentic_file()
# ---------------------------------------------------------------------------


class TestAgenticFileDetection:
    """Files with agentic signatures are detected; plain markdown is rejected."""

    def test_claude_md_filename_is_agentic(self, tmp_path: Path) -> None:
        f = _write(tmp_path / "CLAUDE.md", "## Rules\nDo stuff.\n")
        from shrinkwrap.consolidate import is_agentic_file
        assert is_agentic_file(f) is True

    def test_cursorrules_filename_is_agentic(self, tmp_path: Path) -> None:
        f = _write(tmp_path / ".cursorrules", "## Rules\nDo cursor stuff.\n")
        from shrinkwrap.consolidate import is_agentic_file
        assert is_agentic_file(f) is True

    def test_dot_cursorrules_extension_is_agentic(self, tmp_path: Path) -> None:
        f = _write(tmp_path / "project.cursorrules", "## Rules\ncontent\n")
        from shrinkwrap.consolidate import is_agentic_file
        assert is_agentic_file(f) is True

    def test_claude_sw_md_pattern_is_agentic(self, tmp_path: Path) -> None:
        f = _write(tmp_path / "CLAUDE.sw.md", "## Rules\ncompressed\n")
        from shrinkwrap.consolidate import is_agentic_file
        assert is_agentic_file(f) is True

    def test_shrinkwrap_annotation_makes_file_agentic(self, tmp_path: Path) -> None:
        f = _write(tmp_path / "guide.md", "<!-- shrinkwrap: immutable -->\n## Rules\nNever.\n")
        from shrinkwrap.consolidate import is_agentic_file
        assert is_agentic_file(f) is True

    def test_shrinkwrap_schema_frontmatter_is_agentic(self, tmp_path: Path) -> None:
        f = _write(
            tmp_path / "instr.md",
            '---\nshrinkwrap_schema: "1.0"\nsource_file: "CLAUDE.md"\n---\n## Rules\n',
        )
        from shrinkwrap.consolidate import is_agentic_file
        assert is_agentic_file(f) is True

    def test_plain_markdown_is_not_agentic(self, tmp_path: Path) -> None:
        f = _write(tmp_path / "blog_post.md", "# My Blog\nSome prose here.\n")
        from shrinkwrap.consolidate import is_agentic_file
        assert is_agentic_file(f) is False

    def test_plain_readme_is_not_agentic(self, tmp_path: Path) -> None:
        f = _write(tmp_path / "README.md", "# Project\nInstall with pip.\n")
        from shrinkwrap.consolidate import is_agentic_file
        assert is_agentic_file(f) is False

    def test_changelog_is_not_agentic(self, tmp_path: Path) -> None:
        f = _write(tmp_path / "CHANGELOG.md", "# Changelog\n## v1.0\n- initial release\n")
        from shrinkwrap.consolidate import is_agentic_file
        assert is_agentic_file(f) is False


# ---------------------------------------------------------------------------
# Auto-discovery: discover_agentic_files()
# ---------------------------------------------------------------------------


class TestAgenticFileDiscovery:
    """discover_agentic_files() crawls a directory and returns agentic files."""

    def test_discovers_claude_md_in_root(self, tmp_path: Path) -> None:
        _write(tmp_path / "CLAUDE.md", "## Rules\nDo stuff.\n")
        _write(tmp_path / "README.md", "# Project\nNot agentic.\n")
        from shrinkwrap.consolidate import discover_agentic_files
        found = discover_agentic_files(tmp_path)
        names = [f.name for f in found]
        assert "CLAUDE.md" in names
        assert "README.md" not in names

    def test_discovers_nested_agentic_files(self, tmp_path: Path) -> None:
        _write(tmp_path / "CLAUDE.md", "## Rules\nRoot.\n")
        _write(tmp_path / "subdir" / "CLAUDE.md", "## Rules\nSub.\n")
        from shrinkwrap.consolidate import discover_agentic_files
        found = discover_agentic_files(tmp_path)
        assert len(found) == 2

    def test_skips_git_directory(self, tmp_path: Path) -> None:
        _write(tmp_path / "CLAUDE.md", "## Rules\nLegit.\n")
        _write(tmp_path / ".git" / "CLAUDE.md", "## Rules\nGit internal.\n")
        from shrinkwrap.consolidate import discover_agentic_files
        found = discover_agentic_files(tmp_path)
        paths = [str(f) for f in found]
        assert not any(".git" in p for p in paths)

    def test_skips_node_modules(self, tmp_path: Path) -> None:
        _write(tmp_path / "CLAUDE.md", "## Rules\nLegit.\n")
        _write(tmp_path / "node_modules" / "pkg" / "CLAUDE.md", "## Rules\nPackage.\n")
        from shrinkwrap.consolidate import discover_agentic_files
        found = discover_agentic_files(tmp_path)
        skip_prefix = str(tmp_path / "node_modules")
        assert not any(str(f).startswith(skip_prefix) for f in found)

    def test_empty_directory_returns_empty_list(self, tmp_path: Path) -> None:
        from shrinkwrap.consolidate import discover_agentic_files
        assert discover_agentic_files(tmp_path) == []


# ---------------------------------------------------------------------------
# Merge engine: merge_documents()
# ---------------------------------------------------------------------------


class TestMergeDocuments:
    """merge_documents() combines parsed files with cross-file section dedup."""

    def test_sections_from_all_files_appear_in_output(self, tmp_path: Path) -> None:
        a = _write(tmp_path / "a.md", "## Alpha\ncontent A\n")
        b = _write(tmp_path / "b.md", "## Beta\ncontent B\n")
        from shrinkwrap.consolidate import merge_documents
        merged = merge_documents([a, b])
        assert "Alpha" in merged
        assert "Beta" in merged

    def test_duplicate_heading_only_appears_once(self, tmp_path: Path) -> None:
        a = _write(tmp_path / "a.md", "## Security Rules\ncontent from A\n")
        b = _write(tmp_path / "b.md", "## Security Rules\ncontent from B\n")
        from shrinkwrap.consolidate import merge_documents
        merged = merge_documents([a, b])
        # Heading appears once (first-seen wins)
        assert merged.count("## Security Rules") == 1

    def test_first_file_content_wins_on_dedup(self, tmp_path: Path) -> None:
        a = _write(tmp_path / "a.md", "## Rules\nContent from A.\n")
        b = _write(tmp_path / "b.md", "## Rules\nContent from B.\n")
        from shrinkwrap.consolidate import merge_documents
        merged = merge_documents([a, b])
        assert "Content from A" in merged
        assert "Content from B" not in merged

    def test_cross_file_bullet_deduplication(self, tmp_path: Path) -> None:
        a = _write(tmp_path / "a.md", "## Notes\n- shared bullet\n- unique to A\n")
        b = _write(tmp_path / "b.md", "## Extra\n- shared bullet\n- unique to B\n")
        from shrinkwrap.consolidate import merge_documents
        merged = merge_documents([a, b])
        # "shared bullet" should appear at most once
        assert merged.count("shared bullet") == 1
        assert "unique to A" in merged
        assert "unique to B" in merged

    def test_empty_file_list_returns_empty_string(self) -> None:
        from shrinkwrap.consolidate import merge_documents
        assert merge_documents([]) == ""

    def test_output_is_valid_markdown_with_headings(self, tmp_path: Path) -> None:
        a = _write(tmp_path / "CLAUDE.md", "## Setup\nInstall deps.\n## Usage\nRun it.\n")
        from shrinkwrap.consolidate import merge_documents
        merged = merge_documents([a])
        assert "## Setup" in merged
        assert "## Usage" in merged


# ---------------------------------------------------------------------------
# CLI: shrinkwrap consolidate
# ---------------------------------------------------------------------------


class TestConsolidateCLI:
    """End-to-end CLI tests for 'shrinkwrap consolidate'."""

    def test_consolidate_exits_zero_with_agentic_files(self, tmp_path: Path) -> None:
        _write(tmp_path / "CLAUDE.md", "## Rules\nNever use eval.\n")
        runner = CliRunner()
        result = runner.invoke(cli, ["consolidate", str(tmp_path)])
        assert result.exit_code == 0, result.output

    def test_consolidate_writes_output_file(self, tmp_path: Path) -> None:
        _write(tmp_path / "CLAUDE.md", "## Rules\nNever use eval.\n")
        runner = CliRunner()
        out_file = tmp_path / "CONSOLIDATED.md"
        runner.invoke(cli, ["consolidate", str(tmp_path), "--output", str(out_file)])
        assert out_file.exists()

    def test_consolidate_output_contains_merged_content(self, tmp_path: Path) -> None:
        _write(tmp_path / "CLAUDE.md", "## Security\nNever.\n")
        _write(tmp_path / "CLAUDE.sw.md", "## Status\n- ok\n")
        runner = CliRunner()
        out_file = tmp_path / "CONSOLIDATED.md"
        runner.invoke(cli, ["consolidate", str(tmp_path), "--output", str(out_file)])
        content = out_file.read_text()
        assert "Security" in content
        assert "Status" in content

    def test_consolidate_dry_run_prints_to_stdout(self, tmp_path: Path) -> None:
        _write(tmp_path / "CLAUDE.md", "## Rules\nDo things.\n")
        runner = CliRunner()
        result = runner.invoke(cli, ["consolidate", str(tmp_path), "--dry-run"])
        assert result.exit_code == 0
        assert "Rules" in result.output

    def test_consolidate_dry_run_does_not_write_file(self, tmp_path: Path) -> None:
        _write(tmp_path / "CLAUDE.md", "## Rules\nDo things.\n")
        runner = CliRunner()
        runner.invoke(cli, ["consolidate", str(tmp_path), "--dry-run"])
        assert not (tmp_path / "CONSOLIDATED.md").exists()

    def test_consolidate_no_files_found_exits_zero(self, tmp_path: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["consolidate", str(tmp_path)])
        assert result.exit_code == 0

    def test_consolidate_defaults_to_cwd(self, tmp_path: Path) -> None:
        _write(tmp_path / "CLAUDE.md", "## Rules\nDo things.\n")
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            import os
            os.chdir(tmp_path)
            result = runner.invoke(cli, ["consolidate"])
            assert result.exit_code == 0

    def test_consolidate_deduplicates_across_discovered_files(self, tmp_path: Path) -> None:
        _write(tmp_path / "CLAUDE.md", "## Security Rules\nNever use eval.\n")
        _write(tmp_path / "CLAUDE.sw.md", "## Security Rules\nDuplicate heading.\n")
        runner = CliRunner()
        out_file = tmp_path / "out.md"
        runner.invoke(cli, ["consolidate", str(tmp_path), "--output", str(out_file)])
        content = out_file.read_text()
        assert content.count("## Security Rules") == 1
