"""
Tests for the stats command respecting config, drift threshold from config,
audit CLAUDE.md auto-discovery, the init command, install-hooks guard behaviour,
and ShrinkWrapConfig.default_level being Optional.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner

from shrinkwrap.cli import cli

# ---------------------------------------------------------------------------
# 1 — stats must pass config to parse()
# ---------------------------------------------------------------------------


class TestStatsRespectsConfig:
    def test_stats_applies_extra_immutable_keywords_from_config(self, tmp_path: Path) -> None:
        """stats must use extra_immutable_keywords from shrinkwrap.toml for classification."""
        (tmp_path / "shrinkwrap.toml").write_text(
            '[shrinkwrap]\nextra_immutable_keywords = ["invariant"]\n'
        )
        src = tmp_path / "CLAUDE.md"
        src.write_text("## System Invariant\ncontent here\n## Status\n- ok\n")
        result = CliRunner().invoke(cli, ["stats", str(src)])
        assert result.exit_code == 0
        assert "immutable" in result.output.lower()

    def test_stats_without_config_uses_heuristic_classification(self, tmp_path: Path) -> None:
        """Without shrinkwrap.toml, stats uses built-in heuristics."""
        src = tmp_path / "CLAUDE.md"
        # "Invariant" alone won't trigger immutable without the config keyword
        src.write_text("## Invariant Rules\ncontent here\n")
        result = CliRunner().invoke(cli, ["stats", str(src)])
        assert result.exit_code == 0
        # No crash; output should contain classification info
        assert "immutable" in result.output.lower() or "mutable" in result.output.lower()

    def test_stats_config_classification_matches_compress_classification(
        self, tmp_path: Path
    ) -> None:
        """The classification shown in stats must agree with the one compress produces."""
        (tmp_path / "shrinkwrap.toml").write_text(
            '[shrinkwrap]\nextra_immutable_keywords = ["invariant"]\n'
        )
        src = tmp_path / "CLAUDE.md"
        src.write_text("## System Invariant\ncontent here\n")
        runner = CliRunner()
        stats_result = runner.invoke(cli, ["stats", str(src)])
        compress_result = runner.invoke(cli, ["compress", str(src)])
        assert compress_result.exit_code == 0
        out = src.with_suffix(".sw.md").read_text()
        # Both agree: immutable
        assert 'class="immutable"' in out
        assert "immutable" in stats_result.output.lower()


# ---------------------------------------------------------------------------
# 2 — drift_threshold from config must be used in drift-check
# ---------------------------------------------------------------------------


class TestDriftThresholdFromConfig:
    def test_drift_result_threshold_exceeded_uses_default(self) -> None:
        """DriftResult with score 0.4 exceeds default threshold of 0.35."""
        from shrinkwrap.drift import DriftResult

        r = DriftResult(score=0.4, changed_public_symbols=[], structure_changes=[])
        assert r.threshold_exceeded

    def test_drift_result_score_below_threshold_not_exceeded(self) -> None:
        """DriftResult with score 0.2 does not exceed default threshold."""
        from shrinkwrap.drift import DriftResult

        r = DriftResult(score=0.2, changed_public_symbols=[], structure_changes=[])
        assert not r.threshold_exceeded

    def test_drift_check_cli_respects_config_threshold(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When drift_threshold = 1.0 in config, no score should ever trigger notification."""
        import shrinkwrap.cli as cli_module
        from shrinkwrap.drift import DriftResult

        (tmp_path / "shrinkwrap.toml").write_text("[shrinkwrap]\ndrift_threshold = 1.0\n")

        # Patch score_commit to return a score that would fire at default threshold
        def fake_score_commit(
            repo_root: Path,
            commit_sha: str = "HEAD",
            watched_paths: list[str] | None = None,
        ) -> DriftResult:
            return DriftResult(
                score=0.9,
                changed_public_symbols=["some_function"],
                structure_changes=[],
            )

        monkeypatch.setattr(cli_module, "_score_commit_for_test", None, raising=False)
        monkeypatch.setattr("shrinkwrap.drift.score_commit", fake_score_commit)

        result = CliRunner().invoke(cli, ["drift-check", "--repo", str(tmp_path)])
        # With threshold = 1.0, score 0.9 must NOT fire
        assert "drift detected" not in result.output.lower()

    def test_drift_check_cli_fires_when_score_exceeds_config_threshold(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When drift_threshold = 0.5 and score = 0.8, drift notification must appear."""
        from shrinkwrap.drift import DriftResult

        (tmp_path / "shrinkwrap.toml").write_text("[shrinkwrap]\ndrift_threshold = 0.5\n")

        def fake_score_commit(
            repo_root: Path,
            commit_sha: str = "HEAD",
            watched_paths: list[str] | None = None,
        ) -> DriftResult:
            return DriftResult(
                score=0.8,
                changed_public_symbols=["new_api"],
                structure_changes=[],
            )

        monkeypatch.setattr("shrinkwrap.drift.score_commit", fake_score_commit)

        result = CliRunner().invoke(cli, ["drift-check", "--repo", str(tmp_path)])
        assert "drift detected" in result.output.lower()


# ---------------------------------------------------------------------------
# 3 — audit auto-discovers CLAUDE.md in cwd
# ---------------------------------------------------------------------------


class TestAuditAutoDiscovery:
    def test_audit_discovers_claude_md_in_cwd(self, tmp_path: Path) -> None:
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            Path("CLAUDE.md").write_text("## Status\n- ok\n")
            result = runner.invoke(cli, ["audit"])
            assert result.exit_code == 0
            assert "Status" in result.output

    def test_audit_no_arg_no_claude_md_exits_nonzero(self, tmp_path: Path) -> None:
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(cli, ["audit"])
            assert result.exit_code != 0

    def test_audit_no_arg_error_mentions_claude_md(self, tmp_path: Path) -> None:
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(cli, ["audit"])
            assert "CLAUDE.md" in result.output or "claude" in result.output.lower()

    def test_audit_explicit_arg_still_works(self, tmp_path: Path) -> None:
        src = tmp_path / "myfile.md"
        src.write_text("## Rules\nnever do X\n")
        result = CliRunner().invoke(cli, ["audit", str(src)])
        assert result.exit_code == 0
        assert "Rules" in result.output


# ---------------------------------------------------------------------------
# 4 — shrinkwrap init command
# ---------------------------------------------------------------------------


class TestInitCommand:
    def test_init_creates_shrinkwrap_toml(self, tmp_path: Path) -> None:
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(cli, ["init"])
            assert result.exit_code == 0
            assert Path("shrinkwrap.toml").exists()

    def test_init_creates_valid_toml(self, tmp_path: Path) -> None:
        import tomllib

        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            runner.invoke(cli, ["init"])
            content = Path("shrinkwrap.toml").read_text()
            parsed = tomllib.loads(content)
            assert "shrinkwrap" in parsed

    def test_init_includes_default_level(self, tmp_path: Path) -> None:
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            runner.invoke(cli, ["init"])
            content = Path("shrinkwrap.toml").read_text()
            assert "default_level" in content

    def test_init_includes_default_profile(self, tmp_path: Path) -> None:
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            runner.invoke(cli, ["init"])
            content = Path("shrinkwrap.toml").read_text()
            assert "default_profile" in content

    def test_init_includes_drift_threshold(self, tmp_path: Path) -> None:
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            runner.invoke(cli, ["init"])
            content = Path("shrinkwrap.toml").read_text()
            assert "drift_threshold" in content

    def test_init_does_not_overwrite_existing_config(self, tmp_path: Path) -> None:
        """init must refuse to overwrite an existing shrinkwrap.toml."""
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            existing = '[shrinkwrap]\ndefault_level = "condense"\n'
            Path("shrinkwrap.toml").write_text(existing)
            result = runner.invoke(cli, ["init"])
            assert result.exit_code != 0
            assert Path("shrinkwrap.toml").read_text() == existing

    def test_init_force_overwrites_existing_config(self, tmp_path: Path) -> None:
        """init --force must overwrite an existing shrinkwrap.toml."""
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            Path("shrinkwrap.toml").write_text('[shrinkwrap]\ndefault_level = "condense"\n')
            result = runner.invoke(cli, ["init", "--force"])
            assert result.exit_code == 0

    def test_init_exit_zero_on_success(self, tmp_path: Path) -> None:
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(cli, ["init"])
            assert result.exit_code == 0

    def test_init_output_mentions_shrinkwrap_toml(self, tmp_path: Path) -> None:
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(cli, ["init"])
            assert "shrinkwrap.toml" in result.output


# ---------------------------------------------------------------------------
# 5 — install-hooks guards against existing post-commit hook
# ---------------------------------------------------------------------------


class TestInstallHooksGuard:
    def _make_git_repo(self, path: Path) -> None:
        subprocess.run(["git", "init", str(path)], capture_output=True, check=True)

    def test_install_hooks_creates_hook_when_none_exists(self, tmp_path: Path) -> None:
        self._make_git_repo(tmp_path)
        result = CliRunner().invoke(cli, ["install-hooks", "--repo", str(tmp_path)])
        assert result.exit_code == 0
        assert (tmp_path / ".git" / "hooks" / "post-commit").exists()

    def test_install_hooks_refuses_to_overwrite_existing_hook(self, tmp_path: Path) -> None:
        self._make_git_repo(tmp_path)
        hook_path = tmp_path / ".git" / "hooks" / "post-commit"
        hook_path.write_text("#!/bin/sh\necho 'my hook'\n")
        result = CliRunner().invoke(cli, ["install-hooks", "--repo", str(tmp_path)])
        assert result.exit_code != 0
        # Original hook content preserved
        assert "my hook" in hook_path.read_text()

    def test_install_hooks_warns_about_existing_hook(self, tmp_path: Path) -> None:
        self._make_git_repo(tmp_path)
        hook_path = tmp_path / ".git" / "hooks" / "post-commit"
        hook_path.write_text("#!/bin/sh\necho 'my hook'\n")
        result = CliRunner().invoke(cli, ["install-hooks", "--repo", str(tmp_path)])
        out = result.output.lower()
        assert "existing" in out or "already" in out or "force" in out

    def test_install_hooks_force_overwrites_existing_hook(self, tmp_path: Path) -> None:
        self._make_git_repo(tmp_path)
        hook_path = tmp_path / ".git" / "hooks" / "post-commit"
        hook_path.write_text("#!/bin/sh\necho 'my hook'\n")
        result = CliRunner().invoke(cli, ["install-hooks", "--repo", str(tmp_path), "--force"])
        assert result.exit_code == 0
        assert "shrinkwrap" in hook_path.read_text()

    def test_install_hooks_force_exit_zero(self, tmp_path: Path) -> None:
        self._make_git_repo(tmp_path)
        hook_path = tmp_path / ".git" / "hooks" / "post-commit"
        hook_path.write_text("#!/bin/sh\necho 'my hook'\n")
        result = CliRunner().invoke(cli, ["install-hooks", "--repo", str(tmp_path), "--force"])
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# 6 — ShrinkWrapConfig.default_level must be Optional (None when unset)
# ---------------------------------------------------------------------------


class TestConfigDefaultLevelOptional:
    def test_config_default_level_is_none_when_not_in_toml(self, tmp_path: Path) -> None:
        """When shrinkwrap.toml exists but has no default_level, cfg.default_level is None."""
        from shrinkwrap.config import load_config

        (tmp_path / "shrinkwrap.toml").write_text('[shrinkwrap]\ndefault_profile = "claude"\n')
        cfg = load_config(tmp_path)
        assert cfg.default_level is None

    def test_config_default_level_is_none_when_no_toml(self, tmp_path: Path) -> None:
        """Without shrinkwrap.toml, cfg.default_level is None (not 'normalize')."""
        from shrinkwrap.config import load_config

        cfg = load_config(tmp_path)
        assert cfg.default_level is None

    def test_config_default_level_set_correctly_when_present(self, tmp_path: Path) -> None:
        from shrinkwrap.config import load_config

        (tmp_path / "shrinkwrap.toml").write_text('[shrinkwrap]\ndefault_level = "condense"\n')
        cfg = load_config(tmp_path)
        assert cfg.default_level == "condense"

    def test_compress_no_config_preserves_section_normalize_default(self, tmp_path: Path) -> None:
        """Without config, sections keep 'normalize' compression (the built-in default)."""
        src = tmp_path / "CLAUDE.md"
        src.write_text("## Status\n- ok\n")
        result = CliRunner().invoke(cli, ["compress", str(src)])
        assert result.exit_code == 0
        out = src.with_suffix(".sw.md").read_text()
        assert 'compression="normalize"' in out

    def test_compress_condense_annotation_not_overridden_without_config(
        self, tmp_path: Path
    ) -> None:
        """A section annotated condense must stay condense even without shrinkwrap.toml."""
        src = tmp_path / "CLAUDE.md"
        src.write_text("<!-- shrinkwrap: mutable compression=condense -->\n## Notes\ncontent\n")
        result = CliRunner().invoke(cli, ["compress", str(src)])
        assert result.exit_code == 0
        out = src.with_suffix(".sw.md").read_text()
        assert 'compression="condense"' in out
