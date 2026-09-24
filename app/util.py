"""Logging + small helpers. Single log file, same path layout as Windows."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from . import log_path


def write_log(message: str, level: str = "INFO") -> None:
    line = f"{datetime.now(timezone.utc).astimezone():%Y-%m-%d %H:%M:%S} [{level}] {message}"
    try:
        p: Path = log_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass
    print(line)


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def batch_capacity_bytes(batch_gib: float, min_gib: float, max_gib: float) -> int:
    return int(clamp(float(batch_gib), min_gib, max_gib) * (1024**3))
