"""Batch handover + receipt confirm incl. v3.3.9 partial-confirm shrink."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app import batches, store


def _cfg(tmp: Path) -> dict:
    archive = tmp / "archive"
    staging = tmp / "staging"
    control = tmp / "control"
    for d in (archive, staging, control):
        d.mkdir(parents=True)
    return {
        "SourceRoot": str(archive), "StagingRoot": str(staging),
        "ControlRoot": str(control), "BatchGiB": 5.0, "StableMinutes": 0.0,
        "BackupTimeoutHours": 72,
    }


def test_full_confirm_removes_batch_dir(tmp_path: Path, monkeypatch):
    cfg = _cfg(tmp_path)
    state = tmp_path / "state"
    state.mkdir()
    monkeypatch.setenv("PPU_STATE_DIR", str(state))
    src = Path(cfg["SourceRoot"]) / "pic.jpg"
    src.write_bytes(b"a" * 100)
    catalog_file = state / "catalog.csv"
    staged_file = state / "staged.json"
    completed_file = state / "completed.csv"
    store.save_catalog([{
        "Fingerprint": "fp1", "RelativePath": "pic.jpg", "Size": "100",
        "LastWriteUtc": "2024-01-01T00:00:00+00:00", "Stable": "True", "Sha256": "",
    }], catalog_file)
    store.save_staged([], staged_file)
    n = batches.select_and_stage_batch(cfg, catalog_file, staged_file)
    assert n == 1
    staged = store.load_staged(staged_file)
    batch_id = staged[0]["BatchId"]
    # Receipt confirms the file -> batch dir is removed (full confirm).
    (Path(cfg["ControlRoot"]) / "receipt-1.json").write_text(json.dumps({
        "version": 1, "removedPaths": [staged[0]["PixelSuffix"]]}))
    done = batches.confirm_staged(cfg, staged_file)
    assert done == 1
    assert not batches.batch_dir(Path(cfg["StagingRoot"]), batch_id).exists()
    assert completed_file.exists()


def test_partial_confirm_shrinks_manifest(tmp_path: Path, monkeypatch):
    cfg = _cfg(tmp_path)
    state = tmp_path / "state"
    state.mkdir()
    monkeypatch.setenv("PPU_STATE_DIR", str(state))
    for name in ("a.jpg", "b.jpg"):
        (Path(cfg["SourceRoot"]) / name).write_bytes(os_bytes(name))
    catalog_file = state / "catalog.csv"
    staged_file = state / "staged.json"
    store.save_catalog([{
        "Fingerprint": f"fp-{n}", "RelativePath": n, "Size": str(len(os_bytes(n))),
        "LastWriteUtc": "2024-01-01T00:00:00+00:00", "Stable": "True", "Sha256": "",
    } for n in ("a.jpg", "b.jpg")], catalog_file)
    store.save_staged([], staged_file)
    assert batches.select_and_stage_batch(cfg, catalog_file, staged_file) == 2
    staged = store.load_staged(staged_file)
    first, second = staged
    (Path(cfg["ControlRoot"]) / "receipt-1.json").write_text(json.dumps({
        "version": 1, "removedPaths": [first["PixelSuffix"]]}))
    assert batches.confirm_staged(cfg, staged_file) == 1
    rest = store.load_staged(staged_file)
    assert [e["RelativePath"] for e in rest] == [second["RelativePath"]]
    manifest = json.loads((batches.batch_dir(
        Path(cfg["StagingRoot"]), second["BatchId"]) / "_batch-manifest.json").read_text())
    assert manifest["fileCount"] == 1  # v3.3.9: manifest rewritten to leftovers


def os_bytes(name: str) -> bytes:
    return (name * 50).encode()[:200]


def _state(tmp_path: Path, monkeypatch) -> tuple[dict, Path, Path]:
    cfg = _cfg(tmp_path)
    state = tmp_path / "state"
    state.mkdir()
    monkeypatch.setenv("PPU_STATE_DIR", str(state))
    return cfg, state / "catalog.csv", state / "staged.json"


def test_katalogzeile_ohne_pfad_feld_knackt_nicht(tmp_path, monkeypatch):
    cfg, catalog_file, staged_file = _state(tmp_path, monkeypatch)
    catalog_file.write_text(
        "Fingerprint,Size,LastWriteUtc,Stable,Sha256\n"
        "fp1,100,2024-01-01T00:00:00.0000000Z,True,\n", encoding="utf-8")
    store.save_staged([], staged_file)
    assert batches.select_and_stage_batch(cfg, catalog_file, staged_file) == 0


def test_katalogzeile_ohne_fingerabdruck_knackt_nicht(tmp_path, monkeypatch):
    cfg, catalog_file, staged_file = _state(tmp_path, monkeypatch)
    (Path(cfg["SourceRoot"]) / "pic.jpg").write_bytes(b"a" * 100)
    catalog_file.write_text(
        "RelativePath,Size,LastWriteUtc,Stable,Sha256\n"
        "pic.jpg,100,2024-01-01T00:00:00.0000000Z,True,\n", encoding="utf-8")
    store.save_staged([], staged_file)
    assert batches.select_and_stage_batch(cfg, catalog_file, staged_file) == 0


def test_confirm_matches_absolute_pixel_paths_and_keeps_adb_entries(tmp_path, monkeypatch):
    """Suffix-Set statt staged x receipts endswith: echte absolute Pixel-Pfade,
    bloße Suffixe, unpassende Belege und suffixlose ADB-Einträge."""
    cfg, catalog_file, staged_file = _state(tmp_path, monkeypatch)
    for name in ("a.jpg", "b.jpg"):
        (Path(cfg["SourceRoot"]) / name).write_bytes(os_bytes(name))
    store.save_catalog([{
        "Fingerprint": f"fp-{n}", "RelativePath": n, "Size": str(len(os_bytes(n))),
        "LastWriteUtc": "2024-01-01T00:00:00+00:00", "Stable": "True", "Sha256": "",
    } for n in ("a.jpg", "b.jpg")], catalog_file)
    store.save_staged([], staged_file)
    assert batches.select_and_stage_batch(cfg, catalog_file, staged_file) == 2
    staged = store.load_staged(staged_file)
    first, second = staged
    absolute = "/storage/emulated/0/DCIM/PixelSync/staging" + first["PixelSuffix"]
    (Path(cfg["ControlRoot"]) / "receipt-abs.json").write_text(json.dumps({
        "version": 1, "removedPaths": [absolute]}))
    (Path(cfg["ControlRoot"]) / "receipt-noise.json").write_text(json.dumps({
        "version": 1, "removedPaths": ["/storage/emulated/0/DCIM/Camera/IMG_x.jpg"]}))
    adb_entry = dict(second)
    adb_entry["PixelSuffix"] = ""
    store.save_staged([first, adb_entry], staged_file)
    assert batches.confirm_staged(cfg, staged_file) == 1
    rest = store.load_staged(staged_file)
    assert [e["RelativePath"] for e in rest] == [second["RelativePath"]]


def test_staging_checkpoint_writes_all_states(tmp_path, monkeypatch):
    """Checkpoint alle 25 Dateien + Schlusssave: 30 Dateien, alle Staged."""
    cfg, catalog_file, staged_file = _state(tmp_path, monkeypatch)
    names = [f"p{i:03d}.jpg" for i in range(30)]
    for n in names:
        (Path(cfg["SourceRoot"]) / n).write_bytes(os_bytes(n))
    store.save_catalog([{
        "Fingerprint": f"fp-{n}", "RelativePath": n, "Size": str(len(os_bytes(n))),
        "LastWriteUtc": "2024-01-01T00:00:00+00:00", "Stable": "True", "Sha256": "",
    } for n in names], catalog_file)
    store.save_staged([], staged_file)
    assert batches.select_and_stage_batch(cfg, catalog_file, staged_file) == 30
    staged = store.load_staged(staged_file)
    assert len(staged) == 30 and all(e["State"] == "Staged" for e in staged)


def _two_in_one_batch(tmp_path, monkeypatch):
    """Archive mit a.jpg + b.jpg, beide als ein Batch uebergeben."""
    cfg, catalog_file, staged_file = _state(tmp_path, monkeypatch)
    for name in ("a.jpg", "b.jpg"):
        (Path(cfg["SourceRoot"]) / name).write_bytes(os_bytes(name))
    store.save_catalog([{
        "Fingerprint": f"fp-{n}", "RelativePath": n, "Size": str(len(os_bytes(n))),
        "LastWriteUtc": "2024-01-01T00:00:00+00:00", "Stable": "True", "Sha256": "",
    } for n in ("a.jpg", "b.jpg")], catalog_file)
    store.save_staged([], staged_file)
    assert batches.select_and_stage_batch(cfg, catalog_file, staged_file) == 2
    return cfg, staged_file, tmp_path / "state" / "blocked.csv"


def _age(staged_file: Path, fingerprint: str, when: datetime) -> None:
    entries = store.load_staged(staged_file)
    for entry in entries:
        if entry["Fingerprint"] == fingerprint:
            entry["StagedUtc"] = when.isoformat()
    store.save_staged(entries, staged_file)


def test_abgelaufene_uebergabe_blockiert_und_schrumpft_den_batch(tmp_path, monkeypatch):
    cfg, staged_file, blocked_file = _two_in_one_batch(tmp_path, monkeypatch)
    old = datetime(2026, 1, 1, tzinfo=timezone.utc)
    before = {e["Fingerprint"]: e for e in store.load_staged(staged_file)}
    _age(staged_file, "fp-a.jpg", old)

    assert batches.expire_staged(cfg, staged_file, blocked_file,
                                 now=old + timedelta(hours=73)) == 1

    rest = store.load_staged(staged_file)
    assert [e["RelativePath"] for e in rest] == ["b.jpg"]
    rows = store.load_blocked(blocked_file)
    assert [r["RelativePath"] for r in rows] == ["a.jpg"]
    assert rows[0]["Fingerprint"] == "fp-a.jpg" and rows[0]["BatchId"]

    d = batches.batch_dir(Path(cfg["StagingRoot"]), rest[0]["BatchId"])
    assert (d / before["fp-a.jpg"]["StagedName"]).is_file() is False
    assert (d / rest[0]["StagedName"]).is_file()
    manifest = json.loads((d / "_batch-manifest.json").read_text(encoding="utf-8"))
    assert manifest["fileCount"] == 1 and (d / "_batch-ready.txt").is_file()


def test_alles_abgelaufen_entfernt_den_batch_ordner(tmp_path, monkeypatch):
    cfg, staged_file, blocked_file = _two_in_one_batch(tmp_path, monkeypatch)
    old = datetime(2026, 1, 1, tzinfo=timezone.utc)
    batch_id = store.load_staged(staged_file)[0]["BatchId"]
    for name in ("fp-a.jpg", "fp-b.jpg"):
        _age(staged_file, name, old)

    assert batches.expire_staged(cfg, staged_file, blocked_file,
                                 now=old + timedelta(hours=72, minutes=1)) == 2

    assert store.load_staged(staged_file) == []
    assert len(store.load_blocked(blocked_file)) == 2
    assert not batches.batch_dir(Path(cfg["StagingRoot"]), batch_id).exists()


def test_blockierte_dateien_laufen_nicht_wieder_ein(tmp_path, monkeypatch):
    cfg, staged_file, blocked_file = _two_in_one_batch(tmp_path, monkeypatch)
    old = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for name in ("fp-a.jpg", "fp-b.jpg"):
        _age(staged_file, name, old)
    batches.expire_staged(cfg, staged_file, blocked_file, now=old + timedelta(hours=80))
    batches_dir = Path(cfg["StagingRoot"]) / "Batches"
    assert list(batches_dir.iterdir()) == []
    assert store.load_completion_sets(tmp_path / "state" / "completed.csv")[0] == set()

    assert batches.select_and_stage_batch(cfg, tmp_path / "state" / "catalog.csv",
                                          staged_file) == 0
    assert list(batches_dir.iterdir()) == []
    assert store.load_staged(staged_file) == []


def test_frische_uebergabe_bleibt_unangetastet(tmp_path, monkeypatch):
    cfg, staged_file, blocked_file = _two_in_one_batch(tmp_path, monkeypatch)
    now = datetime(2026, 1, 5, tzinfo=timezone.utc)
    for name in ("fp-a.jpg", "fp-b.jpg"):
        _age(staged_file, name, now - timedelta(hours=1))

    assert batches.expire_staged(cfg, staged_file, blocked_file,
                                 now=now) == 0
    assert len(store.load_staged(staged_file)) == 2
    assert not blocked_file.exists()


def test_leere_datei_laeuft_sofort_aus_statt_den_batch_aufzuhalten(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    state = tmp_path / "state"
    state.mkdir()
    monkeypatch.setenv("PPU_STATE_DIR", str(state))
    (Path(cfg["SourceRoot"]) / "full.jpg").write_bytes(b"x" * 50)
    (Path(cfg["SourceRoot"]) / "empty.jpg").write_bytes(b"")
    catalog_file, staged_file = state / "catalog.csv", state / "staged.json"
    store.save_catalog([
        {"Fingerprint": "fp-empty", "RelativePath": "empty.jpg", "Size": "0",
         "LastWriteUtc": "2024-01-01T00:00:00+00:00", "Stable": "True", "Sha256": ""},
        {"Fingerprint": "fp-full", "RelativePath": "full.jpg", "Size": "50",
         "LastWriteUtc": "2024-01-01T00:00:00+00:00", "Stable": "True", "Sha256": ""},
    ], catalog_file)
    store.save_staged([], staged_file)

    assert batches.select_and_stage_batch(cfg, catalog_file, staged_file) == 1

    rows = store.load_blocked(state / "blocked.csv")
    assert [r["RelativePath"] for r in rows] == ["empty.jpg"]
    staged = store.load_staged(staged_file)
    assert [e["RelativePath"] for e in staged] == ["full.jpg"]
    d = batches.batch_dir(Path(cfg["StagingRoot"]), staged[0]["BatchId"])
    manifest = json.loads((d / "_batch-manifest.json").read_text(encoding="utf-8"))
    assert manifest["fileCount"] == 1
    assert sorted(p.name for p in d.iterdir()) == sorted(
        ["_batch-manifest.json", "_batch-ready.txt", staged[0]["StagedName"]])


def _refusal_receipt(cfg: dict, entries: list[dict]) -> None:
    (Path(cfg["ControlRoot"]) / "receipt-refusal.json").write_text(json.dumps({
        "version": 1, "removedPaths": [], "remainingCount": len(entries),
        "refusedPaths": [e["PixelSuffix"] for e in entries],
    }), encoding="utf-8")


def test_absage_rueckbeleg_gehoert_nicht_zum_erfolg(tmp_path, monkeypatch):
    cfg, staged_file, blocked_file = _two_in_one_batch(tmp_path, monkeypatch)
    staged = store.load_staged(staged_file)
    before = {e["Fingerprint"]: e for e in staged}
    _refusal_receipt(cfg, staged[:1])

    assert batches.release_refused(cfg, staged_file, blocked_file) == 1

    rest = store.load_staged(staged_file)
    assert [e["RelativePath"] for e in rest] == ["b.jpg"]
    rows = store.load_blocked(blocked_file)
    assert [r["RelativePath"] for r in rows] == ["a.jpg"]
    assert rows[0]["Reason"] == "Google Photos refused to free the file"
    assert store.load_completion_sets(tmp_path / "state" / "completed.csv")[0] == set()
    d = batches.batch_dir(Path(cfg["StagingRoot"]), rest[0]["BatchId"])
    assert (d / before["fp-a.jpg"]["StagedName"]).is_file() is False
    manifest = json.loads((d / "_batch-manifest.json").read_text(encoding="utf-8"))
    assert manifest["fileCount"] == 1


def test_absage_haelt_keinen_neuen_batch_auf(tmp_path, monkeypatch):
    cfg, staged_file, blocked_file = _two_in_one_batch(tmp_path, monkeypatch)
    batch_id = store.load_staged(staged_file)[0]["BatchId"]
    _refusal_receipt(cfg, store.load_staged(staged_file))

    assert batches.release_refused(cfg, staged_file, blocked_file) == 2
    assert store.load_staged(staged_file) == []
    assert not batches.batch_dir(Path(cfg["StagingRoot"]), batch_id).exists()

    catalog_file = tmp_path / "state" / "catalog.csv"
    (Path(cfg["SourceRoot"]) / "c.jpg").write_bytes(os_bytes("c.jpg"))
    store.save_catalog(store.load_catalog(catalog_file) + [{
        "Fingerprint": "fp-c.jpg", "RelativePath": "c.jpg", "Size": str(len(os_bytes("c.jpg"))),
        "LastWriteUtc": "2024-01-01T00:00:00+00:00", "Stable": "True", "Sha256": "",
    }], catalog_file)

    assert batches.select_and_stage_batch(cfg, catalog_file, staged_file) == 1
    assert [e["RelativePath"] for e in store.load_staged(staged_file)] == ["c.jpg"]


def test_loesch_rueckbeleg_ist_keine_absage(tmp_path, monkeypatch):
    cfg, staged_file, blocked_file = _two_in_one_batch(tmp_path, monkeypatch)
    staged = store.load_staged(staged_file)
    (Path(cfg["ControlRoot"]) / "receipt-1.json").write_text(json.dumps({
        "version": 1, "removedPaths": [staged[0]["PixelSuffix"]]}), encoding="utf-8")

    assert batches.release_refused(cfg, staged_file, blocked_file) == 0
    assert len(store.load_staged(staged_file)) == 2
    assert not blocked_file.exists()
