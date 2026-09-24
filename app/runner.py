"""One run at a time + the web UI's request to the watcher.

The watcher is the only process that changes state, so the API never runs a
cycle itself: it drops a request file and the loop picks it up. The lock lives
in a file because watcher and API run as separate container services.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import state_root
from .util import write_log

# A cycle that cannot finish in half an hour is a crashed process, not a busy one.
LOCK_STALE = timedelta(minutes=30)


def lock_path() -> Path:
    return state_root() / "sync.lock"


def request_path() -> Path:
    return state_root() / "sync-request.json"


def _utc(value) -> datetime:
    try:
        dt = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _read(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def holder() -> str:
    """Who holds the lock ('' when nobody does) - shown on the status page."""
    data = _read(lock_path())
    if not data:
        return ""
    return str(data.get("reason", "run"))


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except (OSError, OverflowError, ValueError):
        return False
    return True


def _as_pid(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return -1


def acquire(reason: str = "run", path: Path | None = None) -> bool:
    p = path or lock_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    current = _read(p)
    if current:
        taken = _utc(current.get("takenUtc"))
        fresh = datetime.now(timezone.utc) - taken < LOCK_STALE
        alive = _pid_alive(_as_pid(current.get("pid")))
        if fresh and alive:
            return False
        write_log(f"Lock of '{current.get('reason', '?')}' from {taken:%Y-%m-%d %H:%M} "
                  "is stale; taking over.", "WARN")
        try:
            p.unlink()
        except OSError:
            return False
    try:
        fd = os.open(str(p), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError:
        return False
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump({"pid": os.getpid(), "reason": reason,
                   "takenUtc": datetime.now(timezone.utc).isoformat()}, fh)
    return True


def release(path: Path | None = None) -> None:
    p = path or lock_path()
    if _read(p).get("pid") == os.getpid():
        try:
            p.unlink()
        except OSError:
            pass


def request_sync(kind: str = "sync") -> None:
    kind = "deep" if str(kind).lower() == "deep" else "sync"
    p = request_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps({"kind": kind,
                               "requestedUtc": datetime.now(timezone.utc).isoformat()})
                   + "\n", encoding="utf-8")
    tmp.replace(p)


def pending_request() -> str:
    return str(_read(request_path()).get("kind", "") or "")


def take_request(path: Path | None = None) -> str | None:
    """Hand the pending request to the caller, once. None when nothing waits."""
    p = path or request_path()
    kind = pending_request()
    if not kind:
        return None
    try:
        p.unlink()
    except OSError:
        return None
    return kind
