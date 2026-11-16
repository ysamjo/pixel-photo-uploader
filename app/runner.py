"""One run at a time + the web UI's request to the watcher.

The watcher is the only process that changes state, so the API never runs a
cycle itself: it drops a request file and the loop picks it up. The lock lives
in a file because watcher and API run as separate container services.
"""
from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import state_root
from .util import write_log

# A cycle that cannot finish in half an hour is a crashed process, not a busy one.
LOCK_STALE = timedelta(minutes=30)
HEARTBEAT_DISK_INTERVAL = 10.0

_hb_lock = threading.Lock()
_hb_mono = time.monotonic()
_hb_phase = "init"
_hb_disk_mono = 0.0


def lock_path() -> Path:
    return state_root() / "sync.lock"


def heartbeat_path() -> Path:
    return state_root() / "watcher-heartbeat.json"


def touch_heartbeat(phase: str | None = None, *, force_disk: bool = False,
                    path: Path | None = None) -> None:
    """Record watcher progress in memory and throttled to disk for healthchecks."""
    global _hb_mono, _hb_phase, _hb_disk_mono
    now_mono = time.monotonic()
    with _hb_lock:
        _hb_mono = now_mono
        if phase is not None:
            _hb_phase = str(phase)
        current_phase = _hb_phase
        write_disk = force_disk or (now_mono - _hb_disk_mono >= HEARTBEAT_DISK_INTERVAL)
        if write_disk:
            _hb_disk_mono = now_mono
    if not write_disk:
        return
    p = path or heartbeat_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(f"{p.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps({
            "pid": os.getpid(),
            "phase": current_phase,
            "epoch": time.time(),
            "updatedUtc": datetime.now(timezone.utc).isoformat(),
        }) + "\n", encoding="utf-8")
        tmp.replace(p)
    except OSError:
        pass


def heartbeat_age() -> tuple[float, str]:
    """Seconds since last progress heartbeat and the active phase name."""
    with _hb_lock:
        return max(0.0, time.monotonic() - _hb_mono), _hb_phase


def is_heartbeat_fresh(max_age_seconds: float = 900.0, path: Path | None = None) -> bool:
    """True when the persisted watcher heartbeat is newer than max_age_seconds."""
    data = _read(path or heartbeat_path())
    try:
        epoch = float(data.get("epoch", 0) or 0)
    except (TypeError, ValueError):
        return False
    if epoch <= 0:
        return False
    age = time.time() - epoch
    return age <= float(max_age_seconds)


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


def _proc_starttime(pid: int) -> int:
    """Clock ticks since boot when the process started, -1 when unknown.

    A container restart hands pid 1 out again, so the number alone says nothing
    about whether the lock's writer is still the same process.
    """
    try:
        fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        return int(fields[19])
    except (OSError, IndexError, ValueError):
        return -1


def _pid_alive(pid: int, started: int | None = None) -> bool:
    if pid <= 0:
        return False
    # A lock without a recorded start time cannot prove its holder is the
    # process that now answers to that pid - after a container restart the pid
    # is handed out again, typically as pid 1.
    if started is None:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except (OSError, OverflowError, ValueError):
        return False
    if started != -1:
        current = _proc_starttime(pid)
        if current != -1 and current != started:
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
        raw_started = current.get("started")
        alive = _pid_alive(_as_pid(current.get("pid")),
                           None if raw_started is None else _as_pid(raw_started))
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
        json.dump({"pid": os.getpid(), "started": _proc_starttime(os.getpid()),
                   "reason": reason,
                   "takenUtc": datetime.now(timezone.utc).isoformat()}, fh)
    return True


def release(path: Path | None = None) -> None:
    p = path or lock_path()
    data = _read(p)
    mine = data.get("pid") == os.getpid()
    if mine and _as_pid(data.get("started")) != -1:
        mine = _as_pid(data.get("started")) == _proc_starttime(os.getpid())
    if mine:
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
