"""sync_once: der Grundabgleich folgt dem Intervall, nicht jedem Zyklus."""
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app import batches, store, sync
from app.config import DEFAULTS, save_config_atomic


def _roots(tmp_path, monkeypatch, **over) -> tuple[Path, Path]:
    state = tmp_path / "state"
    state.mkdir(exist_ok=True)
    monkeypatch.setenv("PPU_STATE_DIR", str(state))
    archive = tmp_path / "archive"
    for name in ("archive", "staging", "control", "dropbox", "inbox"):
        (tmp_path / name).mkdir(exist_ok=True)
    cfg = dict(DEFAULTS)
    cfg.update({
        "SourceRoot": str(archive), "StagingRoot": str(tmp_path / "staging"),
        "ControlRoot": str(tmp_path / "control"), "StableMinutes": 0,
    })
    cfg.update(over)
    save_config_atomic(cfg)
    return archive, state


def _paths() -> set[str]:
    return {str(r["RelativePath"]) for r in store.load_catalog()}


def test_lauf_ohne_faelliges_intervall_sucht_nicht(tmp_path, monkeypatch):
    archive, _ = _roots(tmp_path, monkeypatch)
    (archive / "2026.09").mkdir(parents=True)
    (archive / "2026.09" / "a.jpg").write_bytes(b"a" * 10)
    sync.sync_once()
    assert _paths() == {"2026.09/a.jpg"}

    (archive / "2026.09" / "b.jpg").write_bytes(b"b" * 10)
    sync.sync_once()
    assert _paths() == {"2026.09/a.jpg"}


def test_faelliger_lauf_oeffnet_nur_unveraenderte_ordner_nicht(tmp_path, monkeypatch):
    archive, _ = _roots(tmp_path, monkeypatch)
    (archive / "2026.09").mkdir(parents=True)
    (archive / "2026.09" / "a.jpg").write_bytes(b"a" * 10)
    sync.sync_once()

    quiet = archive / "2020.01"
    quiet.mkdir()
    (quiet / "alt.jpg").write_bytes(b"c" * 10)
    long_ago = int((datetime.now(timezone.utc) - timedelta(days=3)).timestamp())
    os.utime(quiet, ns=(long_ago * 10**9, long_ago * 10**9))
    (archive / "2026.09" / "b.jpg").write_bytes(b"b" * 10)

    _roots(tmp_path, monkeypatch, RescanMinutes=0)
    sync.sync_once()
    assert _paths() == {"2026.09/a.jpg", "2026.09/b.jpg"}

    sync.sync_once(force_deep=True)
    assert _paths() == {"2026.09/a.jpg", "2026.09/b.jpg", "2020.01/alt.jpg"}


def test_gemeldete_pfade_ohne_rekursivlauf(tmp_path, monkeypatch):
    archive, _ = _roots(tmp_path, monkeypatch, ImportEnabled=True, RescanMinutes=99999,
                        DropboxRoot=str(tmp_path / "dropbox"),
                        InboxRoot=str(tmp_path / "inbox"))
    dropbox = tmp_path / "dropbox"
    old = int((datetime.now(timezone.utc) - timedelta(days=2)).timestamp())

    first = dropbox / "IMG_20260901_120000.jpg"
    first.write_bytes(b"z" * 12)
    os.utime(first, ns=(old * 10**9, old * 10**9))
    sync.sync_once()
    assert _paths() == {"2026.09/IMG_20260901_120000.jpg"}

    second = dropbox / "IMG_20260902_120000.jpg"
    second.write_bytes(b"y" * 12)
    os.utime(second, ns=(old * 10**9, old * 10**9))
    sync.sync_once()
    assert _paths() == {"2026.09/IMG_20260901_120000.jpg",
                        "2026.09/IMG_20260902_120000.jpg"}


def test_rueckbeleg_wird_vor_der_reprovision_gelesen(tmp_path, monkeypatch):
    """Der Beleg ist schon da, die Handreichungskopie fehlt laenger als die
    Schonfrist. sync_once muss abrechnen, bevor es auffuellt - sonst legt es eine
    gerade freigegebene Datei zurueck aufs Telefon."""
    archive, state = _roots(tmp_path, monkeypatch)
    (archive / "2026.09").mkdir(parents=True)
    (archive / "2026.09" / "a.jpg").write_bytes(b"a" * 100)
    sync.sync_once()
    staged = store.load_staged(state / "staged.json")
    assert len(staged) == 1
    entry = staged[0]
    copy = batches.batch_dir(tmp_path / "staging", entry["BatchId"]) / entry["StagedName"]
    copy.unlink()
    aged = store.load_staged(state / "staged.json")
    aged[0]["MissingSinceUtc"] = (datetime.now(timezone.utc)
                                  - timedelta(hours=1)).isoformat()
    store.save_staged(aged, state / "staged.json")
    (tmp_path / "control" / "receipt-1.json").write_text(
        json.dumps({"version": 1, "removedPaths": [entry["PixelSuffix"]]}), encoding="utf-8")

    sync.sync_once()

    # "Re-provided" ist der Beleg dafuer, dass die NAS zurueckkopiert hat, obwohl
    # der Beleg schon im control-Ordner lag.
    assert "Re-provided" not in (state / "PixelPhotoUploader.log").read_text(encoding="utf-8")
    assert store.load_staged(state / "staged.json") == []
    assert entry["Fingerprint"] in store.load_completion_sets()[0]
