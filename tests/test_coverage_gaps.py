"""Tests targeting previously uncovered code paths identified by coverage report."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from shrinkwrap.cli import cli
from shrinkwrap.config import load_config
from shrinkwrap.consolidate import consolidate_with_metrics, discover_agentic_files, is_agentic_file
from shrinkwrap.drift import DriftResult, score_commit
from shrinkwrap.parser import parse
from shrinkwrap.schema import compress_with_metrics, verify

# ---------------------------------------------------------------------------
# schema.py:138 — document with preamble (content before first heading)
# ---------------------------------------------------------------------------


class TestSchemaPreamble:
    def test_preamble_preserved_in_vtbf(self) -> None:
        text = "Introductory preamble text.\n\n## Status\n- ok\n"
        doc = parse(text)
        vtbf, _ = compress_with_metrics(doc, "test.md", text)
        assert "Introductory preamble text" in vtbf

    def test_empty_preamble_omitted(self) -> None:
        text = "## Status\n- ok\n"
        doc = parse(text)
        vtbf, _ = compress_with_metrics(doc, "test.md", text)
        # No preamble block — content starts with section tag
        assert vtbf.count("sw:section") >= 1


# ---------------------------------------------------------------------------
# schema.py:191-192 — malformed YAML in VTBF front-matter
# ---------------------------------------------------------------------------


class TestVerifyMalformedYaml:
    def test_malformed_front_matter_yaml_returns_invalid(self) -> None:
        # Leading tab is a YAML scanner error
        bad_vtbf = "---\n\tfoo: bar\n---\n"
        result = verify(bad_vtbf)
        assert not result.valid


# ---------------------------------------------------------------------------
# schema.py:221-222 — unclosed sw:section tag
# ---------------------------------------------------------------------------


class TestVerifyUnclosedSection:
    def test_unclosed_section_tag_returns_invalid(self) -> None:
        vtbf = (
            "---\n"
            'shrinkwrap_schema: "1.0"\n'
            'source_file: "x.md"\n'
            'source_sha256: "abc123"\n'
            'compressed_at: "2026-01-01T00:00:00Z"\n'
            "compression_ratio: 1.0\n"
            "total_tokens_approx: 10\n"
            "---\n"
            '<!-- sw:section id="security" class="immutable" checksum="abc123" -->\n'
            "## Security Rules\n"
            "Never.\n"
            # Intentionally missing <!-- /sw:section -->
        )
        result = verify(vtbf)
        assert not result.valid
        assert any("unclosed" in e.lower() for e in result.errors)


# ---------------------------------------------------------------------------
# consolidate.py:111 — discover_agentic_files skips non-markdown extensions
# ---------------------------------------------------------------------------


class TestDiscoverSkipsNonMarkdown:
    def test_txt_and_py_files_not_discovered(self, tmp_path: Path) -> None:
        (tmp_path / "CLAUDE.md").write_text("## Section\n- item\n")
        (tmp_path / "notes.txt").write_text("some text")
        (tmp_path / "script.py").write_text("def main(): pass")
        found = [f.name for f in discover_agentic_files(tmp_path)]
        assert "CLAUDE.md" in found
        assert "notes.txt" not in found
        assert "script.py" not in found


# ---------------------------------------------------------------------------
# consolidate.py:145 — invalid level in library function raises ValueError
# ---------------------------------------------------------------------------


class TestConsolidateInvalidLevel:
    def test_invalid_level_raises_value_error(self, tmp_path: Path) -> None:
        f = tmp_path / "CLAUDE.md"
        f.write_text("## Section\n- item\n")
        with pytest.raises(ValueError, match="Invalid level"):
            consolidate_with_metrics([f], level="turbo")


# ---------------------------------------------------------------------------
# consolidate.py:170-171 — OSError reading a path is silently skipped
# ---------------------------------------------------------------------------


class TestConsolidateOSError:
    def test_nonexistent_path_is_skipped(self, tmp_path: Path) -> None:
        missing = tmp_path / "nonexistent.md"
        merged, metrics = consolidate_with_metrics([missing])
        assert merged == ""
        assert metrics.tokens_before == 0
        assert metrics.files_processed == 1


# ---------------------------------------------------------------------------
# consolidate.py:185-186 — paths that yield no sections return empty
# ---------------------------------------------------------------------------


class TestConsolidateNoSections:
    def test_empty_file_returns_empty_string(self, tmp_path: Path) -> None:
        empty = tmp_path / "CLAUDE.md"
        empty.write_text("")
        merged, metrics = consolidate_with_metrics([empty])
        assert merged == ""

    def test_front_matter_only_file_returns_empty_string(self, tmp_path: Path) -> None:
        fm_only = tmp_path / "CLAUDE.md"
        fm_only.write_text("---\nshrinkwrap_schema: '1.0'\n---\n")
        merged, metrics = consolidate_with_metrics([fm_only])
        assert merged == ""


# ---------------------------------------------------------------------------
# consolidate.py:86-87 — malformed YAML front-matter in is_agentic_file
# ---------------------------------------------------------------------------


class TestIsAgenticFileMalformedYaml:
    def test_malformed_yaml_front_matter_does_not_crash(self, tmp_path: Path) -> None:
        f = tmp_path / "file.md"
        f.write_text("---\n\tfoo: bad yaml\n---\n## Section\nContent\n")
        result = is_agentic_file(f)
        assert isinstance(result, bool)


# ---------------------------------------------------------------------------
# config.py:44 — shrinkwrap key in TOML is not a table
# ---------------------------------------------------------------------------


class TestConfigShrinkwrapNotTable:
    def test_string_value_falls_back_to_defaults(self, tmp_path: Path) -> None:
        (tmp_path / "shrinkwrap.toml").write_text('shrinkwrap = "should-be-a-table"\n')
        cfg = load_config(tmp_path)
        assert cfg.default_level is None
        assert cfg.default_profile == "claude"


# ---------------------------------------------------------------------------
# parser.py:70 — front-matter YAML that is not a dict
# ---------------------------------------------------------------------------


class TestParserFrontMatterNotDict:
    def test_list_front_matter_treated_as_empty(self) -> None:
        text = "---\n- item1\n- item2\n---\n## Section\nContent\n"
        doc = parse(text)
        assert len(doc.sections) >= 1
        assert doc.sections[0].heading == "Section"


# ---------------------------------------------------------------------------
# drift.py:110 — config file in changed files contributes to score
# ---------------------------------------------------------------------------


class TestDriftConfigFileChange:
    def test_config_file_change_raises_score(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        def mock_git_run(args: list[str], cwd: Path) -> str:
            if "--name-only" in args:
                return "pyproject.toml\n"
            return ""

        monkeypatch.setattr("shrinkwrap.drift._git_run", mock_git_run)
        result = score_commit(tmp_path)
        # config_changed adds 0.15 * 0.15 weight — score must be > 0
        assert result.score > 0.0
        assert isinstance(result, DriftResult)


# ---------------------------------------------------------------------------
# drift.py:115 — new top-level directory detected as structure change
# ---------------------------------------------------------------------------


class TestDriftNewTopLevelDir:
    def test_new_top_level_dir_detected_as_structure_change(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        def mock_git_run(args: list[str], cwd: Path) -> str:
            if "--name-only" in args:
                return "newpackage/module.py\n"
            if "show" in args:
                return "def func(): pass\n"
            return ""

        monkeypatch.setattr("shrinkwrap.drift._git_run", mock_git_run)
        result = score_commit(tmp_path)
        assert any("dir:" in sc for sc in result.structure_changes)


# ---------------------------------------------------------------------------
# cli.py:604-605 — install-hooks when target is not a git repo
# ---------------------------------------------------------------------------


class TestInstallHooksNotGitRepo:
    def test_install_hooks_fails_without_git_directory(self, tmp_path: Path) -> None:
        result = CliRunner().invoke(cli, ["install-hooks", "--repo", str(tmp_path)])
        assert result.exit_code != 0
        assert "git" in result.output.lower() or "repository" in result.output.lower()


# ---------------------------------------------------------------------------
# cli.py:659-663 — drift-check notification fires when score exceeds threshold
# ---------------------------------------------------------------------------


class TestDriftCheckNotificationFires:
    def test_notification_fires_when_score_exceeds_threshold(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        def fake_score(
            repo_root: Path,
            commit_sha: str = "HEAD",
            watched_paths: list[str] | None = None,
        ) -> DriftResult:
            return DriftResult(score=0.9, changed_public_symbols=["my_func"], structure_changes=[])

        monkeypatch.setattr("shrinkwrap.drift.score_commit", fake_score)
        result = CliRunner().invoke(cli, ["drift-check", "--repo", str(tmp_path)])
        assert "drift detected" in result.output.lower()
        assert "my_func" in result.output

    def test_notification_lists_changed_public_symbols(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        def fake_score(
            repo_root: Path,
            commit_sha: str = "HEAD",
            watched_paths: list[str] | None = None,
        ) -> DriftResult:
            return DriftResult(
                score=0.9, changed_public_symbols=["alpha", "beta"], structure_changes=[]
            )

        monkeypatch.setattr("shrinkwrap.drift.score_commit", fake_score)
        result = CliRunner().invoke(cli, ["drift-check", "--repo", str(tmp_path)])
        assert "alpha" in result.output or "beta" in result.output

    def test_notification_not_fired_below_threshold(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        def fake_score(
            repo_root: Path,
            commit_sha: str = "HEAD",
            watched_paths: list[str] | None = None,
        ) -> DriftResult:
            return DriftResult(score=0.1, changed_public_symbols=[], structure_changes=[])

        monkeypatch.setattr("shrinkwrap.drift.score_commit", fake_score)
        result = CliRunner().invoke(cli, ["drift-check", "--repo", str(tmp_path)])
        assert "drift detected" not in result.output.lower()
