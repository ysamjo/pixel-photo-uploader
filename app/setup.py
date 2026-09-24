"""Setup as one plain function: CLI form and web form share it.

Nothing is written before every value passed, so a rejected form cannot leave a
half-configured install behind.
"""
from __future__ import annotations

from pathlib import Path

from . import (APP_BATCH_FOLDER, MAX_BATCH_GIB, MAX_DEEP_RESCAN_DAYS, MAX_STABLE_SECONDS,
               MIN_BATCH_GIB, MIN_DEEP_RESCAN_DAYS)
from .config import DEFAULTS, _validate_roots, ensure_state_dir, save_config_atomic
from .util import clamp, write_log

ROOTS = ("DropboxRoot", "InboxRoot", "SourceRoot", "StagingRoot", "ControlRoot")


def _folder(values: dict, name: str) -> str:
    return str(values.get(name, "")).strip()


def _number(values: dict, name: str, default: float, errors: list[str]) -> float:
    raw = str(values.get(name, "")).strip()
    if not raw:
        return float(default)
    try:
        return float(raw.replace(",", "."))
    except ValueError:
        errors.append(f"{name} is not a number: {raw!r}")
        return float(default)


def apply_setup(values: dict) -> dict:
    errors: list[str] = []
    folders = {name: _folder(values, name) for name in ROOTS}
    for name in ("SourceRoot", "StagingRoot", "ControlRoot"):
        if not folders[name]:
            errors.append(f"{name} is required.")
    has_dropbox, has_inbox = bool(folders["DropboxRoot"]), bool(folders["InboxRoot"])
    if has_dropbox != has_inbox:
        errors.append("Import needs both cloud folders, DropboxRoot and InboxRoot "
                      "(leave both empty to import nothing).")

    batch = clamp(_number(values, "BatchGiB", 5.0, errors), MIN_BATCH_GIB, MAX_BATCH_GIB)
    stable_s = clamp(_number(values, "StableSeconds", 120.0, errors), 0, MAX_STABLE_SECONDS)
    rescan = max(0.0, _number(values, "RescanMinutes", 360.0, errors))
    deep_days = clamp(_number(values, "DeepRescanDays", 7.0, errors),
                      MIN_DEEP_RESCAN_DAYS, MAX_DEEP_RESCAN_DAYS)

    cfg = dict(DEFAULTS)
    cfg.update({
        "TransportMode": "App", "ConnectionMode": "App",
        "ImportEnabled": has_dropbox and has_inbox,
        "DropboxRoot": folders["DropboxRoot"], "InboxRoot": folders["InboxRoot"],
        "SourceRoot": folders["SourceRoot"], "StagingRoot": folders["StagingRoot"],
        "ControlRoot": folders["ControlRoot"],
        "BatchGiB": batch, "StableMinutes": stable_s / 60,
        "RescanMinutes": int(rescan), "DeepRescanDays": int(deep_days),
    })
    if not errors:
        try:
            _validate_roots(cfg)
        except ValueError as exc:
            errors.append(str(exc))
    if errors:
        return {"ok": False, "errors": errors}

    for name in ROOTS:
        if folders[name]:
            Path(folders[name]).mkdir(parents=True, exist_ok=True)
    (Path(folders["StagingRoot"]) / APP_BATCH_FOLDER).mkdir(parents=True, exist_ok=True)
    ensure_state_dir()
    save_config_atomic(cfg)
    write_log("Setup saved. Handover folder: "
              f"{folders['StagingRoot']}/{APP_BATCH_FOLDER}", "OK")
    return {"ok": True, "errors": [], "config": cfg}
