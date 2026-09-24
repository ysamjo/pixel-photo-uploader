"""Katalogzeilen: Zeitstempel-Format und Standzeit-Laeufe."""
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app import store

# 100-ns-Tick-Wert, den Windows als '2026-09-23T15:51:09.5585421Z' schreibt.
PROBE_NS = 1790178669558542156


def _archive(tmp_path: Path, monkeypatch) -> tuple[Path, Path]:
    state = tmp_path / "state"
    state.mkdir()
    monkeypatch.setenv("PPU_STATE_DIR", str(state))
    return tmp_path / "archive", state


def test_catalog_row_uses_the_net_roundtrip_format(tmp_path, monkeypatch):
    archive, state = _archive(tmp_path, monkeypatch)
    folder = archive / "2026.09"
    folder.mkdir(parents=True)
    pic = folder / "bild.jpg"
    pic.write_bytes(b"x" * 10)
    os.utime(pic, ns=(PROBE_NS, PROBE_NS))
    rows = store.update_catalog(archive, 0.0, state / "catalog.csv")
    assert [r["LastWriteUtc"] for r in rows] == ["2026-09-23T15:51:09.5585421Z"]
