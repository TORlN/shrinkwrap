from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CompressionMetrics:
    """Unified metrics returned by compress_with_metrics and consolidate_with_metrics."""

    files_processed: int
    tokens_before: int
    tokens_after: int
    tokens_saved: int
    compression_pct: float
    duplicate_sections_removed: int
    duplicate_bullets_removed: int
