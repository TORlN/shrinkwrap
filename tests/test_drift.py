"""Tests for drift.py — all should be RED until implemented."""

from __future__ import annotations

from shrinkwrap.drift import (
    DriftResult,
    compute_symbol_drift,
    extract_public_symbols,
)

# ---------------------------------------------------------------------------
# extract_public_symbols
# ---------------------------------------------------------------------------

class TestExtractPublicSymbols:
    def test_top_level_function(self) -> None:
        source = "def my_function():\n    pass\n"
        assert "my_function" in extract_public_symbols(source)

    def test_top_level_class(self) -> None:
        source = "class MyClass:\n    pass\n"
        assert "MyClass" in extract_public_symbols(source)

    def test_private_function_excluded(self) -> None:
        source = "def _private():\n    pass\ndef public():\n    pass\n"
        symbols = extract_public_symbols(source)
        assert "_private" not in symbols
        assert "public" in symbols

    def test_dunder_excluded(self) -> None:
        source = "def __init__(self):\n    pass\n"
        assert "__init__" not in extract_public_symbols(source)

    def test_nested_function_excluded(self) -> None:
        source = "def outer():\n    def inner():\n        pass\n"
        symbols = extract_public_symbols(source)
        assert "outer" in symbols
        assert "inner" not in symbols

    def test_async_function_included(self) -> None:
        source = "async def fetch_data():\n    pass\n"
        assert "fetch_data" in extract_public_symbols(source)

    def test_empty_source_returns_empty(self) -> None:
        assert extract_public_symbols("") == set()

    def test_syntax_error_returns_empty(self) -> None:
        assert extract_public_symbols("def broken(:\n    pass\n") == set()

    def test_multiple_symbols(self) -> None:
        source = (
            "def alpha(): pass\n"
            "def beta(): pass\n"
            "class Gamma: pass\n"
        )
        symbols = extract_public_symbols(source)
        assert symbols == {"alpha", "beta", "Gamma"}


# ---------------------------------------------------------------------------
# compute_symbol_drift
# ---------------------------------------------------------------------------

class TestComputeSymbolDrift:
    def test_new_function_is_added(self) -> None:
        before = "def alpha(): pass\n"
        after = "def alpha(): pass\ndef beta(): pass\n"
        added, removed, renamed = compute_symbol_drift(before, after)
        assert "beta" in added
        assert removed == []

    def test_removed_function_detected(self) -> None:
        before = "def alpha(): pass\ndef beta(): pass\n"
        after = "def alpha(): pass\n"
        added, removed, renamed = compute_symbol_drift(before, after)
        assert "beta" in removed
        assert added == []

    def test_no_change_returns_empty(self) -> None:
        source = "def alpha(): pass\n"
        added, removed, renamed = compute_symbol_drift(source, source)
        assert added == []
        assert removed == []
        assert renamed == []

    def test_implementation_only_change_no_drift(self) -> None:
        before = "def alpha():\n    return 1\n"
        after = "def alpha():\n    return 2\n"
        added, removed, renamed = compute_symbol_drift(before, after)
        assert added == []
        assert removed == []
        assert renamed == []

    def test_class_added(self) -> None:
        before = "def alpha(): pass\n"
        after = "def alpha(): pass\nclass NewService: pass\n"
        added, removed, _ = compute_symbol_drift(before, after)
        assert "NewService" in added

    def test_both_added_and_removed(self) -> None:
        before = "def old_func(): pass\n"
        after = "def new_func(): pass\n"
        added, removed, _ = compute_symbol_drift(before, after)
        assert "new_func" in added
        assert "old_func" in removed


# ---------------------------------------------------------------------------
# DriftResult
# ---------------------------------------------------------------------------

class TestDriftResult:
    def test_threshold_exceeded_above_0_35(self) -> None:
        result = DriftResult(score=0.5, changed_public_symbols=[], structure_changes=[])
        assert result.threshold_exceeded is True

    def test_threshold_not_exceeded_below_0_35(self) -> None:
        result = DriftResult(score=0.2, changed_public_symbols=[], structure_changes=[])
        assert result.threshold_exceeded is False

    def test_threshold_exactly_at_boundary(self) -> None:
        result = DriftResult(score=0.35, changed_public_symbols=[], structure_changes=[])
        assert result.threshold_exceeded is True
