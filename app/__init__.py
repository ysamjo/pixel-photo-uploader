"""Shared paths + constants. Windows PS1 stays untouched; this is the Umbrel port."""
from __future__ import annotations

import os
from pathlib import Path

APP_VERSION = "3.3.16"
APP_BATCH_FOLDER = "Batches"

MIN_BATCH_GIB = 0.25
MAX_BATCH_GIB = 10.0
MAX_STABLE_SECONDS = 43200
# Folders whose write-time is older than the last pass stay closed; the surplus
# is the buffer for clock shifts, suspend and the OS write-back cache.
SCAN_PRUNE_GRACE_HOURS = 24
MIN_DEEP_RESCAN_DAYS = 1
MAX_DEEP_RESCAN_DAYS = 365
# A rejected file must not hold the whole queue: after this many hours without a
# receipt it leaves the handover and is recorded as blocked.
DEFAULT_BACKUP_TIMEOUT_HOURS = 72
MIN_BACKUP_TIMEOUT_HOURS = 1
MAX_BACKUP_TIMEOUT_HOURS = 720
# A handful of reports is cheaper to follow than to re-walk the whole archive.
BULK_PATH_LIMIT = 500


def state_root() -> Path:
    raw = os.environ.get("PPU_STATE_DIR", "").strip()
    if raw:
        return Path(raw).expanduser()
    # Umbrel mounts app-data at /data; local dev falls back to home dir.
    if Path("/data").is_dir():
        return Path("/data") / "pixel-photo-uploader"
    return Path.home() / ".pixel-photo-uploader"


def config_path() -> Path:
    return state_root() / "config.json"


def catalog_path() -> Path:
    return state_root() / "catalog.csv"


def completed_path() -> Path:
    return state_root() / "completed.csv"


def staged_path() -> Path:
    return state_root() / "staged.json"


def blocked_path() -> Path:
    return state_root() / "blocked.csv"


def lastscan_path() -> Path:
    return state_root() / "lastscan.json"


def log_path() -> Path:
    return state_root() / "PixelPhotoUploader.log"
