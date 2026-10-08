"""catalog.csv / completed.csv / staged.json / lastscan.json handling (App path)."""
from __future__ import annotations

import csv
import json
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import (BULK_PATH_LIMIT, SCAN_PRUNE_GRACE_HOURS, blocked_path, catalog_path,
               completed_path, lastscan_path, staged_path, unverified_path)
from .fingerprints import fingerprint, is_supported_media, win_roundtrip_utc
from .media import is_file_ready
from .util import write_log

NEVER = datetime.min.replace(tzinfo=timezone.utc)
CATALOG_FIELDS = ["Fingerprint", "RelativePath", "Size", "LastWriteUtc", "Stable", "Sha256"]
COMPLETED_FIELDS = ["Fingerprint", "Sha256", "RelativePath", "Size", "CompletedUtc", "Reason"]
BLOCKED_FIELDS = ["Fingerprint", "Sha256", "RelativePath", "Size", "BatchId",
                  "StagedUtc", "BlockedUtc", "Reason"]
UNVERIFIED_FIELDS = ["Fingerprint", "Sha256", "RelativePath", "Size",
                     "FirstUnverifiedUtc", "LastAttemptUtc", "RetryAfterUtc",
                     "Attempts", "Reason"]


def _parse_iso(value: str) -> datetime:
    # Windows writes DateTime.ToString('o'); Python writes .isoformat().
    # Both parse via fromisoformat (handle trailing Z).
    v = (value or "").strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(v)
    except ValueError:
        return datetime.fromtimestamp(0, tz=timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def load_catalog(path: Path | None = None) -> list[dict]:
    p = path or catalog_path()
    if not p.exists():
        return []
    with p.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def save_catalog(entries: list[dict], path: Path | None = None) -> None:
    p = path or catalog_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=CATALOG_FIELDS)
        w.writeheader()
        w.writerows(entries)
    tmp.replace(p)


def load_staged(path: Path | None = None) -> list[dict]:
    p = path or staged_path()
    if not p.exists():
        return []
    raw = p.read_text(encoding="utf-8").strip()
    if not raw:
        return []
    data = json.loads(raw)
    return data if isinstance(data, list) else []


def save_staged(entries: list[dict], path: Path | None = None) -> None:
    p = path or staged_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(entries, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(p)


def load_completion_sets(path: Path | None = None) -> tuple[set[str], set[str]]:
    p = path or completed_path()
    fps: set[str] = set()
    hashes: set[str] = set()
    if p.exists():
        with p.open(newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                if row.get("Fingerprint"):
                    fps.add(str(row["Fingerprint"]).lower())
                if row.get("Sha256"):
                    hashes.add(str(row["Sha256"]).lower())
    return fps, hashes


def add_completion(entry: dict, fps: set[str], hashes: set[str], reason: str,
                   path: Path | None = None) -> bool:
    p = path or completed_path()
    fp = str(entry.get("Fingerprint", "")).lower()
    if not fp or fp in fps:
        return False
    row = {
        "Fingerprint": str(entry.get("Fingerprint", "")),
        "Sha256": str(entry.get("Sha256", "")),
        "RelativePath": str(entry.get("RelativePath", "")),
        "Size": str(entry.get("Size", "")),
        "CompletedUtc": datetime.now(timezone.utc).isoformat(),
        "Reason": reason,
    }
    new_file = not p.exists()
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a" if not new_file else "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=COMPLETED_FIELDS)
        if new_file:
            w.writeheader()
        w.writerow(row)
    fps.add(fp)
    if row["Sha256"]:
        hashes.add(row["Sha256"].lower())
    return True


def load_blocked(path: Path | None = None) -> list[dict]:
    p = path or blocked_path()
    if not p.exists():
        return []
    with p.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def save_blocked(entries: list[dict], path: Path | None = None) -> None:
    p = path or blocked_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=BLOCKED_FIELDS)
        w.writeheader()
        w.writerows(entries)
    tmp.replace(p)


def blocked_fingerprints(path: Path | None = None) -> set[str]:
    return {str(row.get("Fingerprint", "")).lower() for row in load_blocked(path)
            if str(row.get("Fingerprint", "")).strip()}


def append_blocked(entries: list[dict], reason: str, path: Path | None = None) -> int:
    """Record handover entries that leave the retry loop; the archive copy stays."""
    p = path or blocked_path()
    rows = load_blocked(p)
    known = {str(row.get("Fingerprint", "")).lower() for row in rows}
    stamped = datetime.now(timezone.utc).isoformat()
    added = 0
    for entry in entries:
        fp = str(entry.get("Fingerprint", "")).strip()
        if not fp or fp.lower() in known:
            continue
        known.add(fp.lower())
        rows.append({
            "Fingerprint": fp,
            "Sha256": str(entry.get("Sha256", "")),
            "RelativePath": str(entry.get("RelativePath", "")),
            "Size": str(entry.get("Size", "")),
            "BatchId": str(entry.get("BatchId", "")),
            "StagedUtc": str(entry.get("StagedUtc", "")),
            "BlockedUtc": stamped,
            "Reason": reason,
        })
        added += 1
    if not added:
        return 0
    save_blocked(rows, p)
    return added



def load_unverified(path: Path | None = None) -> list[dict]:
    p = path or unverified_path()
    if not p.exists():
        return []
    with p.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def save_unverified(entries: list[dict], path: Path | None = None) -> None:
    p = path or unverified_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=UNVERIFIED_FIELDS)
        w.writeheader()
        w.writerows(entries)
    tmp.replace(p)


def unverified_fingerprints(path: Path | None = None) -> set[str]:
    return {str(row.get("Fingerprint", "")).lower() for row in load_unverified(path)
            if str(row.get("Fingerprint", "")).strip()}


def upsert_unverified(entries: list[dict], reason: str, path: Path | None = None,
                      retry_hours: float = 24.0, now: datetime | None = None) -> int:
    """Record uncertain backup outcomes without keeping a copy on the Pixel."""
    p = path or unverified_path()
    rows = load_unverified(p)
    by_fp = {str(row.get("Fingerprint", "")).lower(): row for row in rows
             if str(row.get("Fingerprint", "")).strip()}
    stamp_dt = now or datetime.now(timezone.utc)
    stamp = stamp_dt.isoformat()
    retry_at = (stamp_dt + timedelta(hours=retry_hours)).isoformat()
    changed = 0
    for entry in entries:
        fp = str(entry.get("Fingerprint", "")).strip()
        if not fp:
            continue
        key = fp.lower()
        row = by_fp.get(key)
        if row is None:
            row = {
                "Fingerprint": fp,
                "Sha256": str(entry.get("Sha256", "")),
                "RelativePath": str(entry.get("RelativePath", "")),
                "Size": str(entry.get("Size", "")),
                "FirstUnverifiedUtc": stamp,
                "LastAttemptUtc": stamp,
                "RetryAfterUtc": retry_at,
                "Attempts": "1",
                "Reason": reason,
            }
            rows.append(row)
            by_fp[key] = row
        else:
            try:
                attempts = int(str(row.get("Attempts", "0")) or 0)
            except ValueError:
                attempts = 0
            row.update({
                "Sha256": str(entry.get("Sha256", row.get("Sha256", ""))),
                "RelativePath": str(entry.get("RelativePath", row.get("RelativePath", ""))),
                "Size": str(entry.get("Size", row.get("Size", ""))),
                "LastAttemptUtc": stamp,
                "RetryAfterUtc": retry_at,
                "Attempts": str(attempts + 1),
                "Reason": reason,
            })
            if not str(row.get("FirstUnverifiedUtc", "")).strip():
                row["FirstUnverifiedUtc"] = stamp
        changed += 1
    if changed:
        save_unverified(rows, p)
    return changed


def due_unverified(path: Path | None = None, now: datetime | None = None) -> list[dict]:
    reference = now or datetime.now(timezone.utc)
    due: list[dict] = []
    for row in load_unverified(path):
        retry = _parse_utc(row.get("RetryAfterUtc"))
        if retry == NEVER or retry <= reference:
            due.append(row)
    return due


def remove_unverified(fingerprints, path: Path | None = None) -> int:
    keys = {str(fp).lower() for fp in fingerprints if str(fp).strip()}
    if not keys:
        return 0
    p = path or unverified_path()
    rows = load_unverified(p)
    keep = [row for row in rows
            if str(row.get("Fingerprint", "")).lower() not in keys]
    removed = len(rows) - len(keep)
    if removed:
        save_unverified(keep, p)
    return removed


def _parse_utc(value) -> datetime:
    text = str(value or "").strip()
    if not text:
        return NEVER
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return NEVER
    return dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def load_scan_state(source_root: str, path: Path | None = None) -> tuple[datetime, datetime]:
    """When the archive was last walked and last walked completely.

    A missing, unreadable or foreign-root marker counts as 'never' for both.
    Markers written before the deep stamp existed keep the frontier they have.
    """
    p = path or lastscan_path()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return (NEVER, NEVER)
    if not isinstance(data, dict) or str(data.get("SourceRoot", "")) != str(source_root):
        return (NEVER, NEVER)
    return (_parse_utc(data.get("ScannedUtc")), _parse_utc(data.get("DeepScannedUtc")))


def save_scan_state(scanned: datetime, source_root: str, deep: datetime | None = None,
                    path: Path | None = None) -> None:
    p = path or lastscan_path()
    state = {
        "ScannedUtc": scanned.astimezone(timezone.utc).isoformat(),
        "DeepScannedUtc": (deep.astimezone(timezone.utc).isoformat()
                           if deep and deep > NEVER else ""),
        "SourceRoot": str(source_root),
    }
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(p)


def scan_decision(now: datetime, source_root: str, rescan_minutes: float,
                  deep_rescan_days: float) -> dict:
    """Which pass is due: none, one by folder write-time, or the full walk."""
    scanned, deep = load_scan_state(source_root)
    age = max(0.0, (now - scanned).total_seconds() / 60)
    deep_age = max(0.0, (now - deep).total_seconds() / 60)
    interval = max(0.0, float(rescan_minutes))
    due = age >= interval
    wait = interval if due else max(1.0, interval - age)
    # Skipping folders is only provable after a complete walk: until then no
    # folder can be claimed to have been seen, so nothing may stay closed.
    is_deep = scanned <= NEVER or deep <= NEVER or deep_age >= float(deep_rescan_days) * 1440
    prune_before = None if is_deep else scanned - timedelta(hours=SCAN_PRUNE_GRACE_HOURS)
    if is_deep:
        reason = (f"Interval of {interval:.0f} min reached, full pass due every "
                  f"{float(deep_rescan_days):.0f} days"
                  if scanned > NEVER and deep > NEVER
                  else "Archive never reconciled; full pass")
    else:
        reason = (f"Interval of {interval:.0f} min reached, last pass {age:.0f} min ago; "
                  f"folders without new write-time skipped")
    return {"age_minutes": age, "deep_age_minutes": deep_age, "due": due, "deep": is_deep,
            "prune_before": prune_before, "wait_minutes": wait, "reason": reason}


def _is_skipped_directory(name: str) -> bool:
    lowered = name.lower()
    return (lowered in ("$recycle.bin", "system volume information")
            or lowered.startswith(".sync") or lowered.startswith(".trash"))


def _parent_key(relative: str) -> str:
    key = relative.replace("/", "\\")
    index = key.rfind("\\")
    return "" if index < 0 else key[:index]


def _catalog_entry(f: Path, rel: str, old_by_fp: dict, stable_before: datetime) -> dict:
    st = f.stat()
    lw_iso = win_roundtrip_utc(st.st_mtime_ns)
    fp = fingerprint(rel, st.st_size, lw_iso)
    known = old_by_fp.get(fp)
    sha = str(known.get("Sha256", "")) if known else ""
    stable = (str(known.get("Stable", "")) == "True") if known else is_file_ready(f, stable_before)
    return {
        "Fingerprint": fp, "RelativePath": rel, "Size": str(st.st_size),
        "LastWriteUtc": lw_iso, "Stable": str(bool(stable)), "Sha256": sha,
    }


def _walk_media(source_root: Path, prune_before: datetime | None,
                walked: set[str], counters: dict[str, int]) -> list[Path]:
    """Queue walk instead of rglob: a closed folder is never listed at all."""
    pending: deque[tuple[Path, str]] = deque([(source_root, "")])
    found: list[Path] = []
    while pending:
        directory, key = pending.popleft()
        walked.add(key.lower())
        try:
            children = sorted(directory.iterdir(), key=lambda p: p.name)
        except OSError:
            counters["unreadable"] += 1
            continue
        for child in children:
            try:
                if child.is_symlink():
                    counters["unreadable"] += 1
                    continue
                if not child.is_dir() or _is_skipped_directory(child.name):
                    continue
            except OSError:
                counters["unreadable"] += 1
                continue
            if prune_before is not None:
                # Write-time is the only trace an OS leaves that something arrived
                # in a folder. Whoever restores it (a copy that keeps timestamps)
                # is seen again at the next full pass.
                try:
                    child_write = datetime.fromtimestamp(
                        child.stat().st_mtime, tz=timezone.utc)
                except OSError:
                    child_write = datetime.max.replace(tzinfo=timezone.utc)
                if child_write < prune_before:
                    counters["pruned"] += 1
                    continue
            pending.append((child, f"{key}/{child.name}" if key else child.name))
        for child in children:
            try:
                if child.is_symlink() or not child.is_file():
                    continue
            except OSError:
                continue
            if is_supported_media(child):
                found.append(child)
    return found


def update_catalog(source_root: Path, stable_minutes: float, catalog_file: Path | None = None,
                   prune_before: datetime | None = None, only_paths=(), reason: str = "") -> list[dict]:
    """Reconcile the catalog. RelativePath is stored POSIX-style.

    prune_before set  -> folders that stayed shut keep their rows unseen.
    only_paths set    -> just those reports are followed, no walk at all.
    """
    started = datetime.now(timezone.utc)
    if not source_root.is_dir():
        write_log(f"Source dir missing: {source_root}", "WARN")
        return []
    old = load_catalog(catalog_file)
    old_by_fp = {str(e.get("Fingerprint", "")): e for e in old}
    stable_before = started - timedelta(minutes=float(stable_minutes))

    only = [str(p) for p in tuple(only_paths or ()) if str(p).strip()]
    if only and len(only) <= BULK_PATH_LIMIT:
        return _update_from_paths(source_root, stable_before, old, only, started, catalog_file)

    note = f" ({reason})" if reason.strip() else ""
    write_log(f"Searching {source_root} recursively for new or changed media{note} ...")
    walked: set[str] = set()
    counters = {"unreadable": 0, "pruned": 0}
    entries: list[dict] = []
    new_count = 0
    total = 0
    for f in _walk_media(source_root, prune_before, walked, counters):
        try:
            entry = _catalog_entry(f, f.relative_to(source_root).as_posix(),
                                   old_by_fp, stable_before)
        except OSError:
            continue
        if str(entry["Fingerprint"]) not in old_by_fp:
            new_count += 1
        entries.append(entry)
        total += int(entry["Size"])

    kept_outside = 0
    if prune_before is not None:
        # What sits in a closed folder cannot be judged: neither a deletion nor a
        # fingerprint change. Its row stays as it was.
        kept = [e for e in old
                if _parent_key(str(e.get("RelativePath", ""))).lower() not in walked]
        kept_outside = len(kept)
        entries = kept + entries

    save_catalog(entries, catalog_file)
    # The start of the pass is stamped, not its end: what arrived while it ran
    # has to be seen by the next one.
    deep = prune_before is None
    _, previous_deep = load_scan_state(str(source_root))
    save_scan_state(started, str(source_root), deep=started if deep else previous_deep)

    notes = []
    if kept_outside:
        notes.append(f"{kept_outside} entries in closed folders stayed put")
    if counters["pruned"]:
        notes.append(f"{counters['pruned']} unchanged folders skipped")
    if counters["unreadable"]:
        notes.append(f"{counters['unreadable']} folders not entered")
    suffix = f"; {', '.join(notes)}" if notes else ""
    seconds = (datetime.now(timezone.utc) - started).total_seconds()
    write_log(f"Catalog: {len(entries)} files, {total / 1024**3:.2f} GiB; "
              f"{new_count} new or changed fingerprints; pass {seconds:.1f} s{suffix}.", "OK")
    return entries


def _update_from_paths(source_root: Path, stable_before: datetime, old: list[dict],
                       only: list[str], started: datetime,
                       catalog_file: Path | None) -> list[dict]:
    entries = list(old)
    old_by_fp = {str(e.get("Fingerprint", "")): e for e in old}
    position = {str(e.get("RelativePath", "")): i for i, e in enumerate(entries)}
    removed: set[int] = set()
    changed = 0
    for raw in only:
        path = Path(raw)
        try:
            rel = path.relative_to(source_root).as_posix()
        except ValueError:
            continue
        if _is_skipped_directory(rel.split("/")[0]):
            continue
        known = rel in position
        if path.is_file() and is_supported_media(path):
            try:
                entry = _catalog_entry(path, rel, old_by_fp, stable_before)
            except OSError:
                continue
            if known:
                entries[position[rel]] = entry
            else:
                position[rel] = len(entries)
                entries.append(entry)
            changed += 1
            continue
        # An existing folder reports nothing about its contents and may delete
        # nothing; a gone path means everything below it is gone too.
        if path.is_dir():
            continue
        if known:
            removed.add(position[rel])
            changed += 1
        nested = rel + "/"
        for i, entry in enumerate(entries):
            if str(entry.get("RelativePath", "")).startswith(nested):
                removed.add(i)
                changed += 1

    seconds = (datetime.now(timezone.utc) - started).total_seconds()
    if not changed:
        write_log(f"Catalog checked without a walk: {len(only)} reports, "
                  f"nothing changed ({seconds:.1f} s).")
        return entries
    if removed:
        entries = [e for i, e in enumerate(entries) if i not in removed]
    save_catalog(entries, catalog_file)
    write_log(f"Catalog updated without a recursive walk: {len(only)} reports, "
              f"{changed} entries changed, now {len(entries)} files ({seconds:.1f} s).", "OK")
    return entries


def catalog_sort_key(entry: dict):
    return (-_parse_iso(str(entry.get("LastWriteUtc", ""))).timestamp(),
            str(entry.get("RelativePath", "")))
