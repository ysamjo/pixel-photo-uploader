"""Single sync run + preflight + status (App path only)."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from . import APP_BATCH_FOLDER
from .batches import (confirm_staged, expire_staged, handover_dir, migrate_refusal_blocks,
                      repair_batches, select_and_stage_batch, settle_refused)
from .config import load_config
from .pipeline import run_import
from .runner import acquire, holder, release
from .store import load_catalog, scan_decision, update_catalog
from .util import clamp, write_log
from . import MAX_DEEP_RESCAN_DAYS, MIN_DEEP_RESCAN_DAYS


def preflight(cfg: dict) -> dict:
    staging, control = Path(str(cfg["StagingRoot"])), Path(str(cfg["ControlRoot"]))
    if not str(cfg["StagingRoot"]).strip() or not str(cfg["ControlRoot"]).strip():
        raise FileNotFoundError("Staging or control folder missing. Re-run setup.")
    for p in (staging, control):
        if not p.is_dir():
            raise FileNotFoundError(f"Android-app folder missing: {p}")
    probe = staging / ".ppu-write-probe"
    probe.write_text("probe", encoding="ascii")
    probe.unlink(missing_ok=True)
    for p in (staging, control, staging / APP_BATCH_FOLDER):
        handover_dir(p)
    batches = [d for d in (staging / APP_BATCH_FOLDER).iterdir() if d.is_dir()]
    receipts = list(control.glob("receipt-*.json"))
    write_log(f"Handover folder writable ({staging}); {len(batches)} batches, "
              f"{len(receipts)} receipts arrived.", "OK")
    if not receipts:
        write_log("No receipt synced yet. Is the Pixel companion app running "
                  "and Resilio syncing the control folder?", "WARN")
    return {"batches": len(batches), "receipts": len(receipts)}


def deep_rescan_days(cfg: dict) -> float:
    return clamp(float(cfg.get("DeepRescanDays", 7)), MIN_DEEP_RESCAN_DAYS, MAX_DEEP_RESCAN_DAYS)


def reconcile(cfg: dict, archive_paths=(), force_deep: bool = False) -> list[dict]:
    """Walk the archive only when the last pass is old; else follow reported paths."""
    root = Path(str(cfg["SourceRoot"]))
    rescan_minutes = float(cfg.get("RescanMinutes", 360))
    decision = scan_decision(datetime.now(timezone.utc), str(root),
                             rescan_minutes, deep_rescan_days(cfg))
    if force_deep:
        decision = {**decision, "due": True, "deep": True, "prune_before": None,
                    "reason": "forced"}
    if decision["due"]:
        return update_catalog(root, float(cfg.get("StableMinutes", 2.0)),
                              prune_before=decision["prune_before"],
                              reason=decision["reason"])
    paths = [str(p) for p in tuple(archive_paths or ()) if str(p).strip()]
    if paths:
        write_log(f"Last reconciliation {decision['age_minutes']:.0f} min ago; the archive is "
                  f"not walked again, {len(paths)} reported paths follow.")
        return update_catalog(root, float(cfg.get("StableMinutes", 2.0)), only_paths=paths)
    return load_catalog()


def sync_once(force_deep: bool = False, reason: str = "sync",
              verify_folders: bool = True) -> dict:
    """One pass over everything. Raises BlockingIOError while another pass runs.

    The watcher skips the write probe after the first pass: a probe file every
    minute would keep Resilio busy in the handover folder.
    """
    if not acquire(reason):
        raise BlockingIOError(f"A {holder() or 'other'} run still holds the lock.")
    try:
        cfg = load_config()
        if verify_folders:
            preflight(cfg)
        result = run_import(cfg)
        catalog = reconcile(cfg, result.get("archive_paths", ()), force_deep=force_deep)
        migrate_refusal_blocks()
        confirmed = confirm_staged(cfg)
        refused = settle_refused(cfg)
        blocked = expire_staged(cfg)
        # Belege zuerst, dann auffuellen: was gerade abgerechnet ist, braucht keine
        # Kopie zurueck ins Archiv-Regal.
        repair_batches(cfg)
        staged_count = select_and_stage_batch(cfg)
        return {"import": result, "catalog_files": len(catalog),
                "confirmed": confirmed, "refused": refused, "blocked": blocked,
                "staged": staged_count}
    finally:
        release()


def status() -> dict:
    from .server import overview

    cfg = load_config()
    info = overview(cfg)
    print(f"Archive:      {info['archive']}")
    print(f"Staging:      {info['staging']}")
    print(f"Receipts:     {info['control']}")
    print(f"Batch:        {info['batch_gib']:.2f} GiB - Stabilitaet: "
          f"{info['stable_seconds']:.0f} s - Grundabgleich: alle "
          f"{info['rescan_minutes']} min - Vollabgleich: alle "
          f"{info['deep_rescan_days']:.0f} Tage")
    print(f"Katalog:      {info['catalog_files']} Dateien")
    print(f"Abgeschlossen:{info['completed']} Fingerabdruecke")
    print(f"Auf Pixel:    {info['staged']} Dateien")
    print(f"Blockiert:    {info['blocked']} Dateien (kein Rueckbeleg, Archiv bleibt)")
    print(f"Offen:        {info['open_stable']} Dateien / "
          f"{info['open_bytes'] / 1024**3:.2f} GiB")
    if info["running"]:
        print(f"Sperre:       {info['running']} laeuft gerade")
    if info["pending"]:
        print(f"Eingereiht:   {info['pending']}")
    return info
