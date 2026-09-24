"""Import + sort pipeline (Dropbox -> Inbox -> Archive/YYYY.MM).

Mirrors Invoke-ImportPipeline + Move-MediaFile from the PS1, minus the
Windows-only exclusive-lock check (see media.is_file_ready).
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .fingerprints import file_sha256, is_supported_media
from .media import is_file_ready, media_category, media_date
from .util import write_log


def _unique_destination(folder: Path, name: str) -> Path:
    cand = folder / name
    if not cand.exists():
        return cand
    stem, suffix = Path(name).stem, Path(name).suffix
    i = 1
    while True:
        cand = folder / f"{stem} ({i}){suffix}"
        if not cand.exists():
            return cand
        i += 1


def _find_duplicate(source: Path, folder: Path) -> Path | None:
    size = source.stat().st_size
    candidates = [f for f in folder.iterdir()
                  if f.is_file() and not f.is_symlink() and f.stat().st_size == size]
    if not candidates:
        return None
    src_hash = file_sha256(source)
    for cand in candidates:
        if file_sha256(cand) == src_hash:
            return cand
    return None


def move_media_file(source: Path, folder: Path, reason: str) -> tuple[str, Path | None]:
    folder.mkdir(parents=True, exist_ok=True)
    dup = _find_duplicate(source, folder)
    if dup is not None:
        source.unlink()
        write_log(f"Duplicate removed ({reason}): {source}; identical to {dup}", "OK")
        return ("Duplicate", None)
    dest = _unique_destination(folder, source.name)
    source.rename(dest)
    write_log(f"Moved ({reason}): {source} -> {dest}", "OK")
    return ("Moved", dest)


def run_import(cfg: dict) -> dict:
    if not cfg.get("ImportEnabled"):
        return {"moved": 0, "duplicates": 0, "archive_paths": []}
    dropbox = Path(str(cfg["DropboxRoot"]))
    inbox = Path(str(cfg["InboxRoot"]))
    archive = Path(str(cfg["SourceRoot"]))
    for p in (dropbox, inbox, archive):
        if not p.is_dir():
            raise FileNotFoundError(f"Import folder not reachable: {p}")
    stable_before = datetime.now(timezone.utc) - timedelta(
        minutes=float(cfg.get("StableMinutes", 2.0)))
    moved, dups = 0, 0
    archive_paths: list[str] = []

    write_log("Importing stable media from Dropbox to inbox ...")
    sweep_started = time.monotonic()
    for f in sorted(dropbox.rglob("*")):
        if not f.is_file() or f.is_symlink() or not is_supported_media(f):
            continue
        if not is_file_ready(f, stable_before):
            continue
        result, _ = move_media_file(f, inbox, "Dropbox -> Inbox")
        moved += 1 if result == "Moved" else 0
        dups += 1 if result == "Duplicate" else 0
    sweep_seconds = time.monotonic() - sweep_started

    write_log("Sorting inbox ...")
    sort_started = time.monotonic()
    for f in sorted([p for p in inbox.iterdir() if p.is_file() and not p.is_symlink()]):
        if not is_supported_media(f) or not is_file_ready(f, stable_before):
            continue
        category = media_category(f)
        if category in ("Screenshots", "Memes"):
            dest_folder = inbox / category
        else:
            dest_folder = archive / media_date(f).strftime("%Y.%m")
        result, dest = move_media_file(f, dest_folder, f"Sort: {category}")
        if result == "Moved":
            moved += 1
            try:
                if dest is not None and dest.resolve().is_relative_to(archive.resolve()):
                    archive_paths.append(str(dest))
            except OSError:
                pass
        else:
            dups += 1
    sort_seconds = time.monotonic() - sort_started
    write_log(f"Import/sort done: {moved} moved, {dups} SHA-256 duplicates removed. "
              f"Dropbox sweep {sweep_seconds:.1f} s, sorting {sort_seconds:.1f} s.", "OK")
    return {"moved": moved, "duplicates": dups, "archive_paths": archive_paths}
