"""App+Resilio batch handover (Batches/<id> + receipts).

Mirrors Copy-ToAppBatch / Write-AppBatchMarkers / Get-ReceiptRemovedPaths /
Confirm-AppStagedBatches / Repair-AppBatches / Select-AndStageBatch (App branch).
"""
from __future__ import annotations

import csv
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from . import APP_BATCH_FOLDER
from . import catalog_path as default_catalog_path
from . import completed_path as default_completed_path
from . import staged_path as default_staged_path
from . import blocked_path as default_blocked_path
from . import unverified_path as default_unverified_path
from .fingerprints import file_sha256
from .store import (
    COMPLETED_FIELDS, add_completion, append_blocked, blocked_fingerprints, catalog_sort_key,
    due_unverified, load_blocked, load_catalog, load_completion_sets, load_staged,
    load_unverified, remove_unverified, save_blocked, save_catalog, save_staged,
    unverified_fingerprints, upsert_unverified, _parse_iso,
)
from .util import batch_capacity_bytes, clamp, write_log
from . import MAX_BATCH_GIB, MIN_BATCH_GIB
from . import (DEFAULT_BACKUP_TIMEOUT_HOURS, MAX_BACKUP_TIMEOUT_HOURS,
               MIN_BACKUP_TIMEOUT_HOURS)

# Legacy reason for completion rows written before refusal evidence was reclassified.
ALREADY_SECURED_REASON = "Google Photos already holds this content (nothing to free up)"
REFUSAL_REASONS = ("Google Photos refused to free the file",)
UNVERIFIED_REFUSAL_REASON = "Google Photos reported nothing to free up; backup is unverified"
UNVERIFIED_RETRY_HOURS = 24.0
UNVERIFIED_RETRY_GIB = 0.5

# Resilio braucht gemessen ein paar Minuten in beide Richtungen. Die Loeschung einer
# Handreichungskopie ist also mehrere Durchlaeufe lang ohne Rueckbeleg sichtbar -
# und genau die Zeit gibt repair_batches dem Beleg, bevor aus dem Archiv nachgelegt
# wird. 600 s sind gut das Doppelte der langsamsten gemessenen Uebertragung.
REPAIR_GRACE_SECONDS = 600.0


def batch_dir(staging_root: Path, batch_id: str) -> Path:
    return staging_root / APP_BATCH_FOLDER / batch_id


def handover_dir(directory: Path) -> Path:
    """Create a handover folder the sync service can write into.

    Resilio Sync runs as its own uid, so an app-owned 0755 folder locks it out of
    the share: it has to create, replace and delete files in here in both directions.
    """
    directory.mkdir(parents=True, exist_ok=True)
    directory.chmod(0o777)
    return directory


def copy_to_batch(source: Path, directory: Path, staged_name: str) -> None:
    handover_dir(directory)
    target = directory / staged_name
    part = directory / (staged_name + ".part")
    try:
        # .part first so the phone never picks up a half-written file.
        shutil.copy2(source, part)
        if part.stat().st_size != source.stat().st_size:
            raise IOError(f"Size check failed for handover file: {staged_name}")
        # Cloud mounts hand over 0600 copies; the sync service must read them.
        part.chmod(0o644)
        if target.exists():
            target.unlink()
        part.rename(target)
    finally:
        try:
            part.unlink()
        except OSError:
            pass


def write_batch_markers(staging_root: Path, batch_id: str, entries: list[dict]) -> None:
    d = handover_dir(batch_dir(staging_root, batch_id))
    total = sum(int(e.get("Size", 0)) for e in entries)
    manifest = {
        "version": 1,
        "batchId": batch_id,
        "fileCount": len(entries),
        "bytes": total,
        "createdUtc": datetime.now(timezone.utc).isoformat(),
    }
    (d / "_batch-manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (d / "_batch-ready.txt").write_text("READY\n", encoding="ascii")


def _receipt_paths(control_root: Path, field: str) -> list[str]:
    paths: list[str] = []
    if not control_root.is_dir():
        return paths
    for f in sorted(control_root.glob("receipt-*.json")):
        try:
            receipt = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            write_log(f"Skipped invalid receipt: {f.name}", "WARN")
            continue
        if not isinstance(receipt, dict) or receipt.get("version") != 1:
            continue
        for p in receipt.get(field, []) or []:
            if p:
                paths.append(str(p).replace("\\", "/"))
    return paths


def receipt_removed_paths(control_root: Path) -> list[str]:
    return _receipt_paths(control_root, "removedPaths")


def receipt_refused_paths(control_root: Path) -> list[str]:
    """Paths the Pixel hands back as never freeable.

    A refusal carries no removedPaths: nothing was freed, and the archive copy
    is what stays. The handover has to let go of the file either way.
    """
    return _receipt_paths(control_root, "refusedPaths")


def _staged_suffix_hits(paths: list[str]) -> set[str]:
    """Reduce device paths to the /Batches/<id>/<name> part staged entries carry.

    Receipt paths end with the staged suffix. One rfind per receipt replaces
    staged x receipts endswith checks; rfind (not find) keeps the semantics
    identical to endswith because neither batch id nor staged name can contain
    a second anchor.
    """
    anchor = ("/" + APP_BATCH_FOLDER + "/").lower()
    hits: set[str] = set()
    for path in paths:
        lowered = path.lower()
        at = lowered.rfind(anchor)
        if at >= 0:
            hits.add(lowered[at:])
    return hits


def _remove_batch_dir(staging_root: Path, batch_id: str) -> None:
    target = batch_dir(staging_root, batch_id)
    parent = (staging_root / APP_BATCH_FOLDER).resolve()
    try:
        resolved = target.resolve()
    except OSError:
        return
    try:
        resolved.relative_to(parent)
    except ValueError:
        raise ValueError("Batch dir safety check failed")
    if resolved == parent or target.name != batch_id:
        raise ValueError("Batch dir safety check failed")
    if target.is_dir():
        shutil.rmtree(target)
        write_log(f"Removed completed batch dir: {target}", "OK")


def _retarget_batch(staging_root: Path, batch_id: str, keep: list[dict]) -> None:
    """Leave a batch holding exactly what still waits.

    The Pixel only accepts a batch whose content matches its manifest, so a
    shrunk batch needs new markers or its leftovers are never offered again.
    """
    if not keep:
        _remove_batch_dir(staging_root, batch_id)
        return
    write_batch_markers(staging_root, batch_id, keep)


def confirm_staged(cfg: dict, staged_file: Path | None = None) -> int:
    staged_file = staged_file or default_staged_path()
    staged = load_staged(staged_file)
    if not staged:
        return 0
    removed = receipt_removed_paths(Path(str(cfg["ControlRoot"])))
    if not removed:
        return 0
    hit_suffixes = _staged_suffix_hits(removed)
    fps, hashes = load_completion_sets()
    remaining: list[dict] = []
    confirmed_by_batch: dict[str, list[dict]] = {}
    unconfirmed_by_batch: dict[str, list[dict]] = {}
    done = 0
    for entry in staged:
        batch_id = str(entry.get("BatchId", ""))
        suffix = str(entry.get("PixelSuffix", ""))
        if not suffix:
            write_log(f"Staged entry from ADB run stays unresolved: {entry.get('RelativePath')}", "ERROR")
            remaining.append(entry)
            if batch_id:
                unconfirmed_by_batch.setdefault(batch_id, []).append(entry)
            continue
        if suffix.lower() in hit_suffixes:
            add_completion(entry, fps, hashes, "Android receipt after confirmed Google Photos free-up")
            done += 1
            if batch_id:
                confirmed_by_batch.setdefault(batch_id, []).append(entry)
        else:
            remaining.append(entry)
            if batch_id:
                unconfirmed_by_batch.setdefault(batch_id, []).append(entry)
    save_staged(remaining, staged_file)
    if done:
        remove_unverified([e.get("Fingerprint", "") for entries in confirmed_by_batch.values() for e in entries])
        write_log(f"{done} files confirmed via Android receipts.", "OK")
    staging_root = Path(str(cfg["StagingRoot"]))
    for batch_id, confirmed in confirmed_by_batch.items():
        rest = unconfirmed_by_batch.get(batch_id, [])
        d = batch_dir(staging_root, batch_id)
        for entry in confirmed:
            name = str(entry.get("StagedName", ""))
            if name and (d / name).is_file():
                (d / name).unlink()
        _retarget_batch(staging_root, batch_id, rest)
        if rest:
            write_log(f"Batch {batch_id} shrunk to {len(rest)} remaining files.", "OK")
    if remaining:
        write_log(f"{len(remaining)} files still wait for their Android receipt.")
    return done


def backup_timeout_hours(cfg: dict) -> float:
    return clamp(float(cfg.get("BackupTimeoutHours", DEFAULT_BACKUP_TIMEOUT_HOURS)),
                 MIN_BACKUP_TIMEOUT_HOURS, MAX_BACKUP_TIMEOUT_HOURS)


def _valid_staged_time(value: str) -> bool:
    raw = str(value or "").strip()
    if not raw:
        return False
    try:
        datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return True
    except ValueError:
        return False


def _release_staged(cfg: dict, staged: list[dict], released: list[dict],
                    reason: str, staged_file: Path, blocked_file: Path | None = None,
                    record=None) -> int:
    """Let go of staged entries: book them, and shrink every batch around the rest.

    Only the handover copy goes; the archive keeps its copy and Resilio removes
    the Pixel copy. The ledger is written before the handover file is unlinked:
    a deletion the sync service sees first reads as a free-up by Google Photos.
    """
    if record is None:
        append_blocked(released, reason, blocked_file)
    else:
        record(released)
    keep = [e for e in staged if e not in released]
    save_staged(keep, staged_file)

    staging_root = Path(str(cfg["StagingRoot"]))
    kept_by_batch: dict[str, list[dict]] = {}
    for entry in keep:
        if str(entry.get("BatchId", "")):
            kept_by_batch.setdefault(str(entry["BatchId"]), []).append(entry)
    touched: set[str] = set()
    for entry in released:
        batch_id = str(entry.get("BatchId", ""))
        if not batch_id:
            continue
        touched.add(batch_id)
        staged_p = batch_dir(staging_root, batch_id) / str(entry.get("StagedName", ""))
        if staged_p.is_file():
            staged_p.unlink()
    for batch_id in sorted(touched):
        _retarget_batch(staging_root, batch_id, kept_by_batch.get(batch_id, []))
    return len(released)


def expire_staged(cfg: dict, staged_file: Path | None = None,
                  blocked_file: Path | None = None,
                  now: datetime | None = None,
                  unverified_file: Path | None = None) -> int:
    """Release handovers that never got a receipt so they cannot fill the Pixel."""
    staged_file = staged_file or default_staged_path()
    blocked_file = blocked_file or default_blocked_path()
    unverified_file = unverified_file or default_unverified_path()
    staged = load_staged(staged_file)
    if not staged:
        return 0
    hours = backup_timeout_hours(cfg)
    reference = now or datetime.now(timezone.utc)
    expired = [e for e in staged
               if e.get("State") == "Staged"
               and _valid_staged_time(str(e.get("StagedUtc", "")))
               and (reference - _parse_iso(str(e["StagedUtc"]))).total_seconds() / 3600 >= hours]
    if not expired:
        return 0

    def record(entries: list[dict]) -> None:
        retries = [e for e in entries if bool(e.get("VerificationRetry"))]
        ordinary = [e for e in entries if not bool(e.get("VerificationRetry"))]
        if ordinary:
            append_blocked(ordinary, f"No receipt within {hours:g} h", blocked_file)
        if retries:
            upsert_unverified(retries,
                              f"Verification retry got no receipt within {hours:g} h",
                              unverified_file, retry_hours=UNVERIFIED_RETRY_HOURS)

    count = _release_staged(cfg, staged, expired, f"No receipt within {hours:g} h",
                            staged_file, record=record)
    retry_count = sum(1 for e in expired if bool(e.get("VerificationRetry")))
    blocked_count = count - retry_count
    if blocked_count:
        write_log(f"{blocked_count} files got no receipt within {hours:g} h and are now "
                  f"blocked; their handover copies were released.", "WARN")
    if retry_count:
        write_log(f"{retry_count} verification retries got no receipt; their Pixel copies "
                  f"were released and they remain unverified.", "WARN")
    return count

def settle_refused(cfg: dict, staged_file: Path | None = None,
                   unverified_file: Path | None = None) -> int:
    """Release a refusal from the Pixel but keep it as retryable, unverified work."""
    staged_file = staged_file or default_staged_path()
    unverified_file = unverified_file or default_unverified_path()
    staged = load_staged(staged_file)
    if not staged:
        return 0
    hits = _staged_suffix_hits(receipt_refused_paths(Path(str(cfg["ControlRoot"]))))
    if not hits:
        return 0
    refused = [e for e in staged
               if str(e.get("PixelSuffix", "")).lower() in hits]
    if not refused:
        return 0

    def record(entries: list[dict]) -> None:
        upsert_unverified(entries, UNVERIFIED_REFUSAL_REASON, unverified_file,
                          retry_hours=UNVERIFIED_RETRY_HOURS)

    count = _release_staged(cfg, staged, refused, UNVERIFIED_REFUSAL_REASON,
                            staged_file, record=record)
    write_log(f"{count} files are unverified after a Google Photos refusal; "
              f"their handover copies were released and will be retried later.", "WARN")
    return count


def migrate_refusal_blocks(blocked_file: Path | None = None,
                           completed_file: Path | None = None,
                           unverified_file: Path | None = None) -> int:
    """Move legacy false-success/refusal rows into the retryable unverified ledger."""
    blocked_file = blocked_file or default_blocked_path()
    completed_file = completed_file or default_completed_path()
    unverified_file = unverified_file or default_unverified_path()

    blocked_rows = load_blocked(blocked_file)
    legacy_blocked = [r for r in blocked_rows
                      if str(r.get("Reason", "")) in REFUSAL_REASONS
                      or str(r.get("Reason", "")) == UNVERIFIED_REFUSAL_REASON]
    if legacy_blocked:
        save_blocked([r for r in blocked_rows if r not in legacy_blocked], blocked_file)

    completed_rows: list[dict] = []
    if completed_file.exists():
        with completed_file.open(newline="", encoding="utf-8") as fh:
            completed_rows = list(csv.DictReader(fh))
    unverified_hashes = {str(r.get("Sha256", "")).lower() for r in completed_rows
                         if str(r.get("Reason", "")) == ALREADY_SECURED_REASON
                         and str(r.get("Sha256", "")).strip()}
    verified_hashes = {str(r.get("Sha256", "")).lower() for r in completed_rows
                       if str(r.get("Reason", "")) != ALREADY_SECURED_REASON
                       and str(r.get("Reason", "")) != "Identical content already completed"
                       and str(r.get("Sha256", "")).strip()}
    legacy_completed: list[dict] = []
    kept: list[dict] = []
    for row in completed_rows:
        reason = str(row.get("Reason", ""))
        sha = str(row.get("Sha256", "")).lower()
        if (reason == ALREADY_SECURED_REASON
                or (reason == "Identical content already completed"
                    and sha in unverified_hashes
                    and sha not in verified_hashes)):
            legacy_completed.append(row)
        else:
            kept.append(row)

    if legacy_completed:
        tmp = completed_file.with_suffix(completed_file.suffix + ".tmp")
        with tmp.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=COMPLETED_FIELDS)
            writer.writeheader()
            writer.writerows(kept)
        tmp.replace(completed_file)

    migrated = legacy_blocked + legacy_completed
    if migrated:
        upsert_unverified(migrated, UNVERIFIED_REFUSAL_REASON, unverified_file,
                          retry_hours=UNVERIFIED_RETRY_HOURS)
        write_log(f"{len(migrated)} legacy unverified entries moved into the retry ledger; "
                  "their archive copies remain and no Pixel space is held.", "WARN")
    return len(migrated)

def repair_batches(cfg: dict, staged_file: Path | None = None) -> None:
    staged_file = staged_file or default_staged_path()
    staged = load_staged(staged_file)
    by_batch: dict[str, list[dict]] = {}
    for entry in staged:
        if str(entry.get("BatchId", "")):
            by_batch.setdefault(str(entry["BatchId"]), []).append(entry)
    changed = False
    now = datetime.now(timezone.utc)
    staging_root = Path(str(cfg["StagingRoot"]))
    archive = Path(str(cfg["SourceRoot"]))
    for batch_id, entries in by_batch.items():
        d = batch_dir(staging_root, batch_id)
        for entry in entries:
            staged_p = d / str(entry.get("StagedName", ""))
            if entry.get("State") == "Staged" and staged_p.is_file():
                if entry.pop("MissingSinceUtc", None) is not None:
                    changed = True
                continue
            if entry.get("State") == "Staged":
                # Complete and gone again: the phone freed it and Resilio carried the
                # deletion back before the receipt could travel. Restocking here would
                # undo a Google Photos free-up with our own hands, so the receipt gets
                # the grace period first. An interrupted copy ("Copying") has never
                # reached the phone and is still replaced at once.
                missing_since = entry.get("MissingSinceUtc")
                if not missing_since:
                    entry["MissingSinceUtc"] = now.isoformat()
                    changed = True
                    write_log(f"Handover copy is gone; waiting for its receipt before "
                              f"restocking: {entry.get('RelativePath')}", "WARN")
                    continue
                if (now - _parse_iso(str(missing_since))).total_seconds() < REPAIR_GRACE_SECONDS:
                    continue
            src = archive / str(entry.get("RelativePath", ""))
            if not src.is_file():
                raise FileNotFoundError(f"Cannot resume batch handover; source missing: {src}")
            copy_to_batch(src, d, str(entry["StagedName"]))
            entry["State"] = "Staged"
            # Preserve the first successful handover time: repair cycles must not
            # extend the configured timeout. Copying rows have no such timestamp.
            if not _valid_staged_time(str(entry.get("StagedUtc", ""))):
                entry["StagedUtc"] = now.isoformat()
            entry.pop("MissingSinceUtc", None)
            changed = True
            write_log(f"Re-provided handover file: {entry.get('RelativePath')}", "OK")
        if (d / "_batch-manifest.json").is_file() and (d / "_batch-ready.txt").is_file():
            continue
        if all(e.get("State") == "Staged" for e in entries):
            write_batch_markers(staging_root, batch_id, entries)
    if changed:
        save_staged(staged, staged_file)


def select_and_stage_batch(cfg: dict, catalog_file: Path | None = None,
                            staged_file: Path | None = None,
                            unverified_file: Path | None = None) -> int:
    catalog = load_catalog(catalog_file)
    staged = load_staged(staged_file)
    unverified_file = unverified_file or default_unverified_path()
    capacity = batch_capacity_bytes(float(cfg.get("BatchGiB", 5.0)), MIN_BATCH_GIB, MAX_BATCH_GIB)
    held_bytes = sum(int(str(e.get("Size", "0")) or 0) for e in staged)
    room = capacity - held_bytes
    if room <= 0:
        write_log(f"{len(staged)} files already hold the whole "
                  f"{capacity / 1024**3:.2f} GiB handover capacity; nothing new staged.")
        return 0

    staged_fps = {str(e.get("Fingerprint", "")).lower() for e in staged}
    fps, hashes = load_completion_sets()
    blocked = blocked_fingerprints()
    unverified = unverified_fingerprints(unverified_file)
    archive = Path(str(cfg["SourceRoot"]))
    selected: list[dict] = []
    retry_fps: set[str] = set()
    selected_bytes = 0
    retry_bytes = 0
    retry_budget = min(room, int(UNVERIFIED_RETRY_GIB * 1024**3))
    catalog_changed = False

    # Verification retries are deliberately small and go first. They are not part
    # of the normal queue, so a large uncertain backlog cannot refill the Pixel.
    due = sorted(due_unverified(unverified_file),
                 key=lambda e: (str(e.get("RetryAfterUtc", "")),
                                str(e.get("FirstUnverifiedUtc", "")),
                                str(e.get("RelativePath", ""))))
    for entry in due:
        rel = str(entry.get("RelativePath", "")).strip()
        fp = str(entry.get("Fingerprint", "")).strip()
        key = fp.lower()
        if not rel or not fp or key in fps or key in blocked or key in staged_fps:
            continue
        try:
            size = int(str(entry.get("Size", "0")) or 0)
        except ValueError:
            continue
        if size > capacity or selected_bytes + size > room:
            continue
        if retry_fps and retry_bytes + size > retry_budget:
            continue
        src = archive / rel
        if not src.is_file():
            continue
        if src.stat().st_size == 0:
            append_blocked([entry], "Empty file - nothing for Google Photos to back up")
            remove_unverified([fp], unverified_file)
            unverified.discard(key)
            continue
        sha = str(entry.get("Sha256", "")).strip()
        if not sha:
            write_log(f"Checksum for verification retry: {rel}")
            sha = file_sha256(src)
            entry["Sha256"] = sha
        if sha.lower() in hashes:
            add_completion(entry, fps, hashes, "Identical content already completed")
            remove_unverified([fp], unverified_file)
            unverified.discard(key)
            write_log(f"Unverified content is now proven by an identical completion: {rel}", "OK")
            continue
        selected.append(entry)
        retry_fps.add(key)
        selected_bytes += size
        retry_bytes += size

    for entry in sorted(catalog, key=catalog_sort_key):
        rel = str(entry.get("RelativePath", "")).strip()
        fp = str(entry.get("Fingerprint", "")).strip()
        key = fp.lower()
        if not rel or not fp:
            write_log(f"Catalog row without path or fingerprint skipped "
                      f"(fields: {sorted(entry.keys())})", "ERROR")
            continue
        if str(entry.get("Stable")) != "True" or key in fps or key in blocked:
            continue
        if key in unverified or key in staged_fps or key in retry_fps:
            continue
        size = int(entry.get("Size", 0))
        if size > capacity:
            write_log(f"Single file larger than batch capacity, skipped: {rel}", "WARN")
            continue
        if selected_bytes + size > room:
            continue
        src = archive / rel
        if not src.is_file():
            continue
        if src.stat().st_size == 0:
            append_blocked([entry], "Empty file - nothing for Google Photos to back up")
            write_log(f"Empty file, released from the queue: {rel}", "WARN")
            continue
        if not entry.get("Sha256"):
            write_log(f"Checksum: {rel}")
            entry["Sha256"] = file_sha256(src)
            catalog_changed = True
        if str(entry.get("Sha256", "")).lower() in hashes:
            add_completion(entry, fps, hashes, "Identical content already completed")
            write_log(f"Already completed content under new path: {rel}", "OK")
            catalog_changed = True
            continue
        selected.append(entry)
        selected_bytes += size

    if catalog_changed:
        save_catalog(catalog, catalog_file)
    if not selected:
        return 0

    batch_id = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    write_log(f"Staging batch with {len(selected)} files, {selected_bytes / 1024**3:.2f} GiB"
              f" ({len(retry_fps)} verification retries).")
    staging_root = Path(str(cfg["StagingRoot"]))
    d = batch_dir(staging_root, batch_id)
    new_records: list[dict] = []
    try:
        for i, entry in enumerate(selected, start=1):
            ext = Path(str(entry["RelativePath"])).suffix.lower()
            fp_key = str(entry["Fingerprint"]).lower()
            staged_name = f"{i:06d}-{str(entry['Fingerprint'])[:12]}{ext}"
            suffix = f"/{APP_BATCH_FOLDER}/{batch_id}/{staged_name}"
            rec = {
                "Fingerprint": str(entry["Fingerprint"]), "Sha256": str(entry.get("Sha256", "")),
                "RelativePath": str(entry["RelativePath"]), "Size": str(entry.get("Size", "")),
                "RemotePath": suffix, "BatchId": batch_id, "StagedName": staged_name,
                "PixelSuffix": suffix, "State": "Copying", "StagedUtc": "",
                "VerificationRetry": fp_key in retry_fps,
            }
            new_records.append(rec)
            write_log(f"Handing over via Resilio folder: {entry.get('RelativePath')}")
            copy_to_batch(archive / str(entry["RelativePath"]), d, staged_name)
            rec["State"] = "Staged"
            rec["StagedUtc"] = datetime.now(timezone.utc).isoformat()
            if i % 25 == 0:
                save_staged(staged + new_records, staged_file)
    except Exception as exc:
        save_staged(staged + new_records, staged_file)
        write_log(f"Transfer failed: {exc}", "ERROR")
        raise
    save_staged(staged + new_records, staged_file)
    write_batch_markers(staging_root, batch_id, selected)
    write_log(f"Batch ready in handover folder: {d}", "OK")
    return len(selected)

def batch_gib_clamped(cfg: dict) -> float:
    return clamp(float(cfg.get("BatchGiB", 5.0)), MIN_BATCH_GIB, MAX_BATCH_GIB)
