"""Polling watch loop. No FileSystemWatcher in Docker; plain intervals.

One cycle = import -> reconciliation -> receipts -> staging. Anything that
throws is logged and retried on the next pass; a stall watchdog exits the
container if no progress heartbeat arrives within hang_seconds so Docker restarts it.
"""
from __future__ import annotations

import faulthandler
import os
import sys
import threading
import time
from collections.abc import Callable

from . import log_path
from .runner import heartbeat_age, holder, pending_request, release, take_request, touch_heartbeat
from .sync import sync_once
from .util import write_log

# The handover folders were proven writable; re-check them after a failure only.
_folders_ok = False

DEFAULT_HANG_SECONDS = 900.0


def _hang_seconds(explicit: float | None = None) -> float:
    if explicit is not None:
        return max(0.05, float(explicit))
    raw = os.environ.get("PPU_WATCH_HANG_SECONDS", "").strip()
    if raw:
        try:
            return max(60.0, float(raw))
        except ValueError:
            pass
    return DEFAULT_HANG_SECONDS


def _dump_stacks() -> None:
    try:
        faulthandler.dump_traceback(file=sys.stderr, all_threads=True)
    except Exception:
        pass
    try:
        p = log_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as fh:
            faulthandler.dump_traceback(file=fh, all_threads=True)
    except OSError:
        pass


def _start_stall_watchdog(hang_seconds: float, *,
                          check_interval: float | None = None,
                          on_hang: Callable[[], None] | None = None) -> threading.Event:
    stop = threading.Event()
    interval = check_interval if check_interval is not None else min(15.0, max(0.02, hang_seconds / 4.0))
    action = on_hang or (lambda: os._exit(1))

    def _monitor() -> None:
        while not stop.wait(interval):
            age, phase = heartbeat_age()
            if age <= hang_seconds:
                continue
            write_log(
                f"Watcher hung in phase '{phase}' for {age:.1f}s without progress; "
                "dumping stacks and restarting.",
                "ERROR",
            )
            _dump_stacks()
            release()
            action()
            return

    threading.Thread(target=_monitor, name="watcher-stall-watchdog", daemon=True).start()
    return stop


def run_cycle(force_deep: bool = False, reason: str = "watch") -> bool:
    """One pass over everything. False when this pass failed or was skipped."""
    global _folders_ok
    touch_heartbeat("cycle")
    try:
        sync_once(force_deep=force_deep, reason=reason, verify_folders=not _folders_ok)
        _folders_ok = True
        return True
    except BlockingIOError as exc:
        write_log(f"{exc} This pass is skipped.")
    except Exception as exc:  # keep the container alive, log and retry
        _folders_ok = False
        write_log(f"Cycle failed, retrying: {exc}", "ERROR")
    finally:
        touch_heartbeat("idle", force_disk=True)
    return False


def _wait(seconds: float) -> float:
    """Sleep, but return early when the web UI queued a run. Seconds slept."""
    started = time.monotonic()
    deadline = started + max(0.0, float(seconds))
    while True:
        touch_heartbeat("idle")
        remaining = deadline - time.monotonic()
        if remaining <= 0 or pending_request():
            return time.monotonic() - started
        time.sleep(min(1.0, remaining))


def watch(poll_seconds: int = 60, hang_seconds: float | None = None, *,
          on_hang: Callable[[], None] | None = None,
          max_cycles: int | None = None) -> None:
    interval = max(10, int(poll_seconds)) if max_cycles is None else max(0, int(poll_seconds))
    limit = _hang_seconds(hang_seconds)
    touch_heartbeat("startup", force_disk=True)
    stop = _start_stall_watchdog(limit, on_hang=on_hang)
    write_log(f"Watch started (poll every {interval}s, stall timeout {limit:.0f}s). Ctrl+C to stop.", "OK")
    cycles = 0
    try:
        while max_cycles is None or cycles < max_cycles:
            kind = take_request()
            if kind == "deep":
                write_log("Full archive pass requested from the web page.")
            run_cycle(force_deep=(kind == "deep"))
            cycles += 1
            if max_cycles is not None and cycles >= max_cycles:
                break
            _wait(interval)
    finally:
        stop.set()
