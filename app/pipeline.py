"""Import + sort pipeline (Dropbox -> Inbox -> Archive/YYYY.MM).

Mirrors Invoke-ImportPipeline + Move-MediaFile from the PS1, minus the
Windows-only exclusive-lock check (see media.is_file_ready).
"""
from __future__ import annotations

import errno
import shutil
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .fingerprints import file_sha256, is_supported_media
from .media import is_file_ready, media_category, media_date
from .util import write_log

# Cloud mounts (rclone/FUSE, e.g. via ZimaOS Files) and sync clients leave
# debris that must never enter the archive or a handover batch. The Dropbox
# sweep and the inbox sort both skip these; the archive walk keeps them out
# via is_supported_media, but a stale ".sync" copy of a photo carries a valid
# extension, so the directory check below is the load-bearing one.
SKIP_DIR_NAMES = frozenset({
    ".sync", "@eaDir", ".stfolder", ".stversions", ".Trash-1000", ".dropbox.cache",
})
SKIP_SUFFIXES = frozenset({".tmp", ".part", ".crdownload", ".!sync", ".download"})
SKIP_PREFIXES = ("~", ".~")
SKIP_FILENAMES = frozenset({"Thumbs.db", ".DS_Store", "desktop.ini"})


def is_ignorable(path: Path) -> bool:
    """True for sync debris, partial downloads and OS thumbnails."""
    name = path.name
    if name in SKIP_FILENAMES or name.startswith(SKIP_PREFIXES):
        return True
    if Path(name).suffix.lower() in SKIP_SUFFIXES:
        return True
    lowered = name.lower()
    if ".sync-conflict" in lowered or ".syncthing" in lowered:
        return True
    return any(part in SKIP_DIR_NAMES for part in path.parts)


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


def _find_duplicate(source: Path, folder: Path,
                    index: "_DestinationIndex | None" = None) -> Path | None:
    size = source.stat().st_size
    if index is None:
        candidates = [f for f in folder.iterdir()
                      if f.is_file() and not f.is_symlink() and f.stat().st_size == size]
    else:
        candidates = index.candidates(folder, size)
    if not candidates:
        return None
    src_hash = file_sha256(source)
    for cand in candidates:
        if file_sha256(cand) == src_hash:
            return cand
    return None


def _relocate(source: Path, dest: Path) -> None:
    """Move within one filesystem, copy+delete across filesystems.

    Cloud mounts (ZimaOS Files links for Dropbox/OneDrive) live on a different
    filesystem than the local archive, so Path.rename raises EXDEV there.
    The copy is size-checked before the source is removed.
    """
    try:
        source.rename(dest)
        return
    except OSError as exc:
        if exc.errno not in (errno.EXDEV, None) and "Invalid cross-device" not in str(exc):
            raise
    shutil.copy2(source, dest)
    if dest.stat().st_size != source.stat().st_size:
        try:
            dest.unlink()
        except OSError:
            pass
        raise IOError(f"Size check failed moving {source} -> {dest}")
    source.unlink()


class _DestinationIndex:
    """One size listing per destination folder per import run.

    Without it, moving N files into the same folder lists and stats that
    folder N times (quadratic in bulk imports); with it, once, plus one
    append per moved file. Entries only ever grow during a run (moves land,
    nothing leaves a destination), so the index cannot go stale mid-run.
    """

    def __init__(self) -> None:
        self._by_folder: dict[str, dict[int, list[Path]]] = {}

    def candidates(self, folder: Path, size: int) -> list[Path]:
        by_size = self._by_folder.get(str(folder))
        if by_size is None:
            by_size = {}
            try:
                children = list(folder.iterdir())
            except OSError:
                children = []
            for child in children:
                try:
                    if child.is_file() and not child.is_symlink():
                        by_size.setdefault(child.stat().st_size, []).append(child)
                except OSError:
                    continue
            self._by_folder[str(folder)] = by_size
        return list(by_size.get(size, []))

    def note_moved(self, folder: Path, path: Path, size: int) -> None:
        self._by_folder.setdefault(str(folder), {}).setdefault(size, []).append(path)


def move_media_file(source: Path, folder: Path, reason: str,
                    index: "_DestinationIndex | None" = None) -> tuple[str, Path | None]:
    folder.mkdir(parents=True, exist_ok=True)
    dup = _find_duplicate(source, folder, index)
    if dup is not None:
        source.unlink()
        write_log(f"Duplicate removed ({reason}): {source}; identical to {dup}", "OK")
        return ("Duplicate", None)
    dest = _unique_destination(folder, source.name)
    size = source.stat().st_size
    _relocate(source, dest)
    if index is not None:
        index.note_moved(folder, dest, size)
    write_log(f"Moved ({reason}): {source} -> {dest}", "OK")
    return ("Moved", dest)


def run_import(cfg: dict) -> dict:
    if not cfg.get("ImportEnabled"):
        return {"moved": 0, "duplicates": 0, "archive_paths": []}
    inbox = Path(str(cfg["InboxRoot"]))
    archive = Path(str(cfg["SourceRoot"]))
    for p in (inbox, archive):
        if not p.is_dir():
            raise FileNotFoundError(f"Import folder not reachable: {p}")

    cloud_sources: list[tuple[Path, str]] = []
    if cfg.get("DropboxRoot"):
        cloud_sources.append((Path(str(cfg["DropboxRoot"])), "Dropbox"))
    if cfg.get("OneDriveRoot"):
        cloud_sources.append((Path(str(cfg["OneDriveRoot"])), "OneDrive"))

    for p, name in cloud_sources:
        if not p.is_dir():
            raise FileNotFoundError(f"Import folder not reachable: {p}")

    stable_before = datetime.now(timezone.utc) - timedelta(
        minutes=float(cfg.get("StableMinutes", 2.0)))
    moved, dups = 0, 0
    archive_paths: list[str] = []
    sweep_seconds = 0.0
    index = _DestinationIndex()

    for folder, name in cloud_sources:
        write_log(f"Importing stable media from {name} to inbox ...")
        sweep_started = time.monotonic()
        for f in sorted(folder.rglob("*")):
            if not f.is_file() or f.is_symlink() or not is_supported_media(f):
                continue
            if is_ignorable(f):
                continue
            if not is_file_ready(f, stable_before):
                continue
            result, _ = move_media_file(f, inbox, f"{name} -> Inbox", index)
            moved += 1 if result == "Moved" else 0
            dups += 1 if result == "Duplicate" else 0
        sweep_seconds += time.monotonic() - sweep_started

    write_log("Sorting inbox ...")
    sort_started = time.monotonic()
    for f in sorted([p for p in inbox.iterdir() if p.is_file() and not p.is_symlink()]):
        if not is_supported_media(f) or is_ignorable(f) or not is_file_ready(f, stable_before):
            continue
        category = media_category(f)
        if category in ("Screenshots", "Memes"):
            dest_folder = inbox / category
        else:
            dest_folder = archive / media_date(f).strftime("%Y.%m")
        result, dest = move_media_file(f, dest_folder, f"Sort: {category}", index)
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
    sweep_desc = " / ".join(f"{name} sweep" for _, name in cloud_sources) if cloud_sources else "Sweep"
    write_log(f"Import/sort done: {moved} moved, {dups} SHA-256 duplicates removed. "
              f"{sweep_desc} {sweep_seconds:.1f} s, sorting {sort_seconds:.1f} s.", "OK")
    return {"moved": moved, "duplicates": dups, "archive_paths": archive_paths}
