"""Uebergabe-Modi: der Sync-Dienst läuft unter einer anderen uid als der Uploader."""
from pathlib import Path

from app.batches import copy_to_batch, handover_dir
from app.sync import preflight


def _mode(p: Path) -> int:
    return p.stat().st_mode & 0o777


def test_uebergabe_ordner_sind_fuer_den_sync_dienst_schreibbar(tmp_path):
    d = tmp_path / "staging" / "Batches" / "b1"
    handover_dir(d)
    assert _mode(d) == 0o777


def test_vorbelegung_macht_kontrollordner_fuer_den_sync_dienst_schreibbar(tmp_path, monkeypatch):
    monkeypatch.setenv("PPU_STATE_DIR", str(tmp_path / "state"))
    staging = tmp_path / "staging"
    control = tmp_path / "control"
    for p in (staging, control):
        p.mkdir()
        p.chmod(0o755)
    preflight({"StagingRoot": str(staging), "ControlRoot": str(control)})
    assert _mode(control) == 0o777
    assert _mode(staging / "Batches") == 0o777


def test_uebergabe_kopie_ist_fuer_den_sync_dienst_lesbar(tmp_path):
    source = tmp_path / "archiv" / "bild.jpg"
    source.parent.mkdir()
    source.write_bytes(b"x" * 32)
    source.chmod(0o600)
    directory = tmp_path / "staging" / "Batches" / "b1"
    copy_to_batch(source, directory, "000001-bild.jpg")
    assert _mode(directory / "000001-bild.jpg") == 0o644
