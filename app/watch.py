"""Polling watch loop. No FileSystemWatcher in Docker; plain intervals.

One cycle = import -> reconciliation -> receipts -> staging. Anything that
throws is logged and retried on the next pass; the loop itself never stops.
"""
from __future__ import annotations

import time

from .runner import holder, pending_request, take_request
from .sync import sync_once
from .util import write_log

# The handover folders were proven writable; re-check them after a failure only.
_folders_ok = False


def run_cycle(force_deep: bool = False, reason: str = "watch") -> bool:
    """One pass over everything. False when this pass failed or was skipped."""
    global _folders_ok
    try:
        sync_once(force_deep=force_deep, reason=reason, verify_folders=not _folders_ok)
        _folders_ok = True
        return True
    except BlockingIOError as exc:
        write_log(f"{exc} This pass is skipped.")
    except Exception as exc:  # keep the container alive, log and retry
        _folders_ok = False
        write_log(f"Cycle failed, retrying: {exc}", "ERROR")
    return False


def _wait(seconds: float) -> float:
    """Sleep, but return early when the web UI queued a run. Seconds slept."""
    started = time.monotonic()
    deadline = started + max(0.0, float(seconds))
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0 or pending_request():
            return time.monotonic() - started
        time.sleep(min(1.0, remaining))


def watch(poll_seconds: int = 60) -> None:
    interval = max(10, int(poll_seconds))
    write_log(f"Watch started (poll every {interval}s). Ctrl+C to stop.", "OK")
    while True:
        kind = take_request()
        if kind == "deep":
            write_log("Full archive pass requested from the web page.")
        run_cycle(force_deep=(kind == "deep"))
        _wait(interval)
