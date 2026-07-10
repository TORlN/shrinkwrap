"""Regression tests for forcing UTF-8 stdio (Windows console codepage mangling)."""

from __future__ import annotations

from shrinkwrap.cli import _ensure_utf8_stdio


class _FakeStream:
    def __init__(self, encoding: str, *, raise_on_reconfigure: Exception | None = None) -> None:
        self.encoding = encoding
        self.reconfigure_calls: list[dict[str, str]] = []
        self._raise = raise_on_reconfigure

    def reconfigure(self, **kwargs: str) -> None:
        if self._raise is not None:
            raise self._raise
        self.reconfigure_calls.append(kwargs)
        self.encoding = kwargs.get("encoding", self.encoding)


def test_reconfigures_stdout_and_stderr_to_utf8(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    fake_stdout = _FakeStream("cp1252")
    fake_stderr = _FakeStream("cp1252")
    monkeypatch.setattr("shrinkwrap.cli.sys.stdout", fake_stdout)
    monkeypatch.setattr("shrinkwrap.cli.sys.stderr", fake_stderr)

    _ensure_utf8_stdio()

    assert fake_stdout.reconfigure_calls == [{"encoding": "utf-8", "errors": "replace"}]
    assert fake_stderr.reconfigure_calls == [{"encoding": "utf-8", "errors": "replace"}]
    assert fake_stdout.encoding == "utf-8"
    assert fake_stderr.encoding == "utf-8"


def test_noop_when_stream_lacks_reconfigure(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    class _NoReconfigure:
        pass

    monkeypatch.setattr("shrinkwrap.cli.sys.stdout", _NoReconfigure())
    monkeypatch.setattr("shrinkwrap.cli.sys.stderr", _NoReconfigure())

    _ensure_utf8_stdio()  # must not raise


def test_swallows_reconfigure_errors(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    fake_stdout = _FakeStream("cp1252", raise_on_reconfigure=ValueError("already reading input"))
    fake_stderr = _FakeStream("cp1252")
    monkeypatch.setattr("shrinkwrap.cli.sys.stdout", fake_stdout)
    monkeypatch.setattr("shrinkwrap.cli.sys.stderr", fake_stderr)

    _ensure_utf8_stdio()  # must not raise despite stdout's reconfigure() failing

    assert fake_stderr.reconfigure_calls == [{"encoding": "utf-8", "errors": "replace"}]
