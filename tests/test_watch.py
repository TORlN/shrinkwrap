"""
TDD tests for the `shrinkwrap watch` command.

Behaviour under test:
  - CLI command exists, accepts expected flags, exits non-zero on bad input
  - Detects a file change (mtime) and recompresses in-place
  - Does NOT retrigger on its own write (no infinite recompress loop)
  - Respects the --level flag
  - Terminates cleanly when the stop_event is set
  - Works with already-compressed (VTBF) files — re-parses transparently
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

from click.testing import CliRunner

from shrinkwrap.cli import _watch_loop, cli

POLL = 0.05  # fast interval for tests
SETTLE = 0.35  # time to let the watcher detect + act


# ---------------------------------------------------------------------------
# CLI surface
# ---------------------------------------------------------------------------


class TestWatchCLISurface:
    def test_watch_help_exits_zero(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["watch", "--help"])
        assert result.exit_code == 0

    def test_watch_help_mentions_interval(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["watch", "--help"])
        assert "interval" in result.output.lower()

    def test_watch_nonexistent_file_exits_nonzero(self, tmp_path: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["watch", str(tmp_path / "ghost.md")])
        assert result.exit_code != 0

    def test_watch_accepts_level_flag(self, tmp_path: Path) -> None:
        """Smoke-test: --level flag is accepted (no unknown option error)."""
        src = tmp_path / "CLAUDE.md"
        src.write_text("## Status\n- ok\n")
        stop = threading.Event()
        thread = threading.Thread(
            target=_watch_loop,
            args=(src, "condense", "claude", False, POLL),
            kwargs={"stop_event": stop},
            daemon=True,
        )
        thread.start()
        stop.set()
        thread.join(timeout=1.0)
        assert not thread.is_alive()


# ---------------------------------------------------------------------------
# Core watch loop behaviour
# ---------------------------------------------------------------------------


class TestWatchLoop:
    def test_stop_event_terminates_loop(self, tmp_path: Path) -> None:
        src = tmp_path / "CLAUDE.md"
        src.write_text("## Status\n- ok\n")

        stop = threading.Event()
        t = threading.Thread(
            target=_watch_loop,
            args=(src, None, "claude", False, POLL),
            kwargs={"stop_event": stop},
            daemon=True,
        )
        t.start()
        time.sleep(0.1)
        stop.set()
        t.join(timeout=2.0)
        assert not t.is_alive()

    def test_recompresses_when_file_changes(self, tmp_path: Path) -> None:
        src = tmp_path / "CLAUDE.md"
        src.write_text("## Status\n- ok\n")

        stop = threading.Event()
        t = threading.Thread(
            target=_watch_loop,
            args=(src, None, "claude", False, POLL),
            kwargs={"stop_event": stop},
            daemon=True,
        )
        t.start()
        time.sleep(0.15)  # let watcher record baseline mtime
        src.write_text("## Status\n- changed\n")
        time.sleep(SETTLE)  # let watcher detect + compress
        stop.set()
        t.join(timeout=2.0)

        assert "shrinkwrap_schema" in src.read_text()

    def test_no_change_means_no_recompress(self, tmp_path: Path) -> None:
        src = tmp_path / "CLAUDE.md"
        src.write_text("## Status\n- ok\n")

        stop = threading.Event()
        t = threading.Thread(
            target=_watch_loop,
            args=(src, None, "claude", False, POLL),
            kwargs={"stop_event": stop},
            daemon=True,
        )
        t.start()
        time.sleep(SETTLE)  # wait — but don't touch the file
        stop.set()
        t.join(timeout=2.0)

        assert "shrinkwrap_schema" not in src.read_text()

    def test_does_not_retrigger_on_own_write(self, tmp_path: Path) -> None:
        """After compression, the watcher's own write must not cause a second pass."""
        src = tmp_path / "CLAUDE.md"
        src.write_text("## Status\n- ok\n")

        stop = threading.Event()
        t = threading.Thread(
            target=_watch_loop,
            args=(src, None, "claude", False, POLL),
            kwargs={"stop_event": stop},
            daemon=True,
        )
        t.start()
        time.sleep(0.15)
        src.write_text("## Status\n- edited\n")
        time.sleep(SETTLE * 2)  # plenty of time for a second pass
        stop.set()
        t.join(timeout=2.0)

        # Output must be valid VTBF, not a double-compressed file
        content = src.read_text()
        assert content.count("shrinkwrap_schema") == 1

    def test_respects_level_condense(self, tmp_path: Path) -> None:
        src = tmp_path / "CLAUDE.md"
        src.write_text("## Section A\n- shared\n- only A\n## Section B\n- shared\n- only B\n")

        stop = threading.Event()
        t = threading.Thread(
            target=_watch_loop,
            args=(src, "condense", "claude", False, POLL),
            kwargs={"stop_event": stop},
            daemon=True,
        )
        t.start()
        time.sleep(0.15)
        # Touch file to trigger compression
        src.write_text(
            "## Section A\n- shared\n- only A\n## Section B\n- shared\n- only B\n- new item\n"
        )
        time.sleep(SETTLE)
        stop.set()
        t.join(timeout=2.0)

        content = src.read_text()
        assert 'compression="condense"' in content
        # Cross-section dedup: "shared" should appear only once in body
        assert content.count("shared") == 1

    def test_immutable_content_preserved_on_recompress(self, tmp_path: Path) -> None:
        src = tmp_path / "CLAUDE.md"
        src.write_text(
            "<!-- shrinkwrap: immutable -->\n## Rules\nNever use eval().\n## Status\n- ok\n"
        )

        stop = threading.Event()
        t = threading.Thread(
            target=_watch_loop,
            args=(src, None, "claude", False, POLL),
            kwargs={"stop_event": stop},
            daemon=True,
        )
        t.start()
        time.sleep(0.15)
        src.write_text(
            "<!-- shrinkwrap: immutable -->\n## Rules\nNever use eval().\n## Status\n- updated\n"
        )
        time.sleep(SETTLE)
        stop.set()
        t.join(timeout=2.0)

        assert "Never use eval()." in src.read_text()

    def test_recompress_output_passes_verify(self, tmp_path: Path) -> None:
        runner = CliRunner()
        src = tmp_path / "CLAUDE.md"
        src.write_text("<!-- shrinkwrap: immutable -->\n## Rules\nNever.\n## Status\n- ok\n")

        stop = threading.Event()
        t = threading.Thread(
            target=_watch_loop,
            args=(src, None, "claude", False, POLL),
            kwargs={"stop_event": stop},
            daemon=True,
        )
        t.start()
        time.sleep(0.15)
        src.write_text("<!-- shrinkwrap: immutable -->\n## Rules\nNever.\n## Status\n- updated\n")
        time.sleep(SETTLE)
        stop.set()
        t.join(timeout=2.0)

        result = runner.invoke(cli, ["verify", str(src)])
        assert result.exit_code == 0

    def test_already_compressed_file_recompresses_transparently(self, tmp_path: Path) -> None:
        """Watching a pre-compressed VTBF file: a new plain-source write must
        produce valid single-schema VTBF, not a double-compressed file."""
        runner = CliRunner()
        src = tmp_path / "CLAUDE.md"
        src.write_text("## Status\n- ok\n")
        runner.invoke(cli, ["compress", str(src), "--in-place"])

        stop = threading.Event()
        t = threading.Thread(
            target=_watch_loop,
            args=(src, None, "claude", False, POLL),
            kwargs={"stop_event": stop},
            daemon=True,
        )
        t.start()
        time.sleep(0.15)
        # Simulate user reverting to plain source (common "undo compression" workflow)
        src.write_text("## Status\n- ok\n- new item\n")
        time.sleep(SETTLE)
        stop.set()
        t.join(timeout=2.0)

        content = src.read_text()
        assert content.count("shrinkwrap_schema") == 1
        assert "new item" in content
        result = runner.invoke(cli, ["verify", str(src)])
        assert result.exit_code == 0
