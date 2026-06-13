"""Tests for config.py — all RED until implemented."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from shrinkwrap.config import ShrinkWrapConfig, load_config


class TestLoadConfigDefaults:
    def test_missing_file_returns_defaults(self, tmp_path: Path) -> None:
        cfg = load_config(tmp_path)
        assert isinstance(cfg, ShrinkWrapConfig)

    def test_default_level_is_none_when_unset(self, tmp_path: Path) -> None:
        assert load_config(tmp_path).default_level is None

    def test_default_profile_is_claude(self, tmp_path: Path) -> None:
        assert load_config(tmp_path).default_profile == "claude"

    def test_default_drift_threshold(self, tmp_path: Path) -> None:
        assert load_config(tmp_path).drift_threshold == pytest.approx(0.35)

    def test_default_watched_paths_empty(self, tmp_path: Path) -> None:
        assert load_config(tmp_path).watched_paths == []

    def test_default_extra_immutable_keywords_empty(self, tmp_path: Path) -> None:
        assert load_config(tmp_path).extra_immutable_keywords == []

    def test_default_extra_mutable_keywords_empty(self, tmp_path: Path) -> None:
        assert load_config(tmp_path).extra_mutable_keywords == []


class TestLoadConfigFromFile:
    def _write(self, tmp_path: Path, content: str) -> ShrinkWrapConfig:
        (tmp_path / "shrinkwrap.toml").write_text(textwrap.dedent(content))
        return load_config(tmp_path)

    def test_level_override(self, tmp_path: Path) -> None:
        cfg = self._write(tmp_path, """\
            [shrinkwrap]
            default_level = "condense"
        """)
        assert cfg.default_level == "condense"

    def test_profile_override(self, tmp_path: Path) -> None:
        cfg = self._write(tmp_path, """\
            [shrinkwrap]
            default_profile = "cursor"
        """)
        assert cfg.default_profile == "cursor"

    def test_drift_threshold_override(self, tmp_path: Path) -> None:
        cfg = self._write(tmp_path, """\
            [shrinkwrap]
            drift_threshold = 0.5
        """)
        assert cfg.drift_threshold == pytest.approx(0.5)

    def test_watched_paths(self, tmp_path: Path) -> None:
        cfg = self._write(tmp_path, """\
            [shrinkwrap]
            watched_paths = ["src/", "lib/"]
        """)
        assert "src/" in cfg.watched_paths
        assert "lib/" in cfg.watched_paths

    def test_extra_immutable_keywords(self, tmp_path: Path) -> None:
        cfg = self._write(tmp_path, """\
            [shrinkwrap]
            extra_immutable_keywords = ["invariant", "contract"]
        """)
        assert "invariant" in cfg.extra_immutable_keywords

    def test_extra_mutable_keywords(self, tmp_path: Path) -> None:
        cfg = self._write(tmp_path, """\
            [shrinkwrap]
            extra_mutable_keywords = ["roadmap", "backlog"]
        """)
        assert "backlog" in cfg.extra_mutable_keywords

    def test_invalid_toml_falls_back_to_defaults(self, tmp_path: Path) -> None:
        (tmp_path / "shrinkwrap.toml").write_text("this is not : valid toml :")
        cfg = load_config(tmp_path)
        assert cfg.default_level is None

    def test_unknown_keys_ignored(self, tmp_path: Path) -> None:
        cfg = self._write(tmp_path, """\
            [shrinkwrap]
            default_level = "condense"
            totally_unknown_key = "whatever"
        """)
        assert cfg.default_level == "condense"

    def test_invalid_level_value_falls_back_to_none(self, tmp_path: Path) -> None:
        cfg = self._write(tmp_path, """\
            [shrinkwrap]
            default_level = "turbo_ultra_compress"
        """)
        assert cfg.default_level is None


class TestConfigInfluencesClassification:
    """Config extra keywords must actually affect parser classification."""

    def test_extra_immutable_keyword_classifies_section(self, tmp_path: Path) -> None:
        from shrinkwrap.parser import parse

        (tmp_path / "shrinkwrap.toml").write_text(
            "[shrinkwrap]\nextra_immutable_keywords = [\"invariant\"]\n"
        )
        cfg = load_config(tmp_path)
        doc = parse("## Invariant Properties\nsome content\n", config=cfg)
        s = next(s for s in doc.sections if s.heading == "Invariant Properties")
        assert s.classification == "immutable"

    def test_extra_mutable_keyword_classifies_section(self, tmp_path: Path) -> None:
        from shrinkwrap.parser import parse

        (tmp_path / "shrinkwrap.toml").write_text(
            "[shrinkwrap]\nextra_mutable_keywords = [\"roadmap\"]\n"
        )
        cfg = load_config(tmp_path)
        doc = parse("## Product Roadmap\nsome content\n", config=cfg)
        s = next(s for s in doc.sections if s.heading == "Product Roadmap")
        assert s.classification == "mutable"
