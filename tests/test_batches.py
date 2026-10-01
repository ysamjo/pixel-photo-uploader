"""Batch handover + receipt confirm incl. v3.3.9 partial-confirm shrink."""
import json
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
