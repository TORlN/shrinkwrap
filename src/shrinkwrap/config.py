from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .parser import COMPRESSION

_VALID_LEVELS = frozenset(["normalize", "condense", "aggressive"])
_VALID_PROFILES = frozenset(["claude", "cursor", "generic"])


@dataclass
class ShrinkWrapConfig:
    default_level: COMPRESSION | None = None  # None = "use section's own default"
    default_profile: str = "claude"
    drift_threshold: float = 0.35
    watched_paths: list[str] = field(default_factory=list)
    extra_immutable_keywords: list[str] = field(default_factory=list)
    extra_mutable_keywords: list[str] = field(default_factory=list)


def load_config(project_root: Path) -> ShrinkWrapConfig:
    """Load shrinkwrap.toml from project_root. Falls back to defaults on any error."""
    config_path = project_root / "shrinkwrap.toml"
    if not config_path.exists():
        return ShrinkWrapConfig()

    import tomllib  # stdlib since Python 3.11

    try:
        raw: dict[str, Any] = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except Exception as exc:
        warnings.warn(
            f"shrinkwrap.toml could not be parsed ({exc}); using default settings.",
            UserWarning,
            stacklevel=2,
        )
        return ShrinkWrapConfig()

    section: dict[str, Any] = raw.get("shrinkwrap", {})
    if not isinstance(section, dict):
        return ShrinkWrapConfig()

    cfg = ShrinkWrapConfig()

    level = section.get("default_level")
    if level in _VALID_LEVELS:
        cfg.default_level = level

    profile = section.get("default_profile", "claude")
    if profile in _VALID_PROFILES:
        cfg.default_profile = profile

    threshold = section.get("drift_threshold", 0.35)
    if isinstance(threshold, (int, float)):
        cfg.drift_threshold = max(0.0, min(1.0, float(threshold)))

    watched = section.get("watched_paths", [])
    if isinstance(watched, list):
        cfg.watched_paths = [str(p) for p in watched]

    extra_imm = section.get("extra_immutable_keywords", [])
    if isinstance(extra_imm, list):
        cfg.extra_immutable_keywords = [str(k) for k in extra_imm]

    extra_mut = section.get("extra_mutable_keywords", [])
    if isinstance(extra_mut, list):
        cfg.extra_mutable_keywords = [str(k) for k in extra_mut]

    return cfg
