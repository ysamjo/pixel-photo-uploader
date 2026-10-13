"""Katalogzeilen: Zeitstempel-Format und Standzeit-Laeufe."""
import csv
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


def test_completion_totals_trennt_das_zeitfenster(tmp_path, monkeypatch):
    _, state = _archive(tmp_path, monkeypatch)
    now = datetime(2026, 10, 13, 16, 0, tzinfo=timezone.utc)
    ledger = [
        ("a", "100", (now - timedelta(hours=1)).isoformat()),
        ("b", "200", (now - timedelta(hours=25)).isoformat()),
        ("c", "300", ""),
    ]
    with (state / "completed.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=store.COMPLETED_FIELDS)
        w.writeheader()
        for fp, size, stamp in ledger:
            w.writerow({"Fingerprint": fp, "Sha256": "", "RelativePath": f"{fp}.jpg",
                        "Size": size, "CompletedUtc": stamp, "Reason": "test"})
    got = store.completion_totals(now=now)
    assert (got["count"], got["bytes"]) == (3, 600)
    assert (got["recent_count"], got["recent_bytes"]) == (1, 100)


def test_completion_totals_ohne_ledger_ist_null(tmp_path, monkeypatch):
    _archive(tmp_path, monkeypatch)
    assert store.completion_totals() == {
        "bytes": 0, "count": 0, "recent_bytes": 0, "recent_count": 0,
        "window_hours": 24.0,
    }
