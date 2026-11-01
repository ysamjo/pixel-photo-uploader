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
        "verified_bytes": 0, "verified_count": 0,
        "assumed_bytes": 0, "assumed_count": 0,
        "recent_verified_bytes": 0, "recent_assumed_bytes": 0,
        "window_hours": 24.0,
    }


def test_requeue_assumed_schiebt_zeilen_zurueck_in_die_pruefung(tmp_path, monkeypatch):
    """Stichprobe: angenommene Zeilen verlassen das Ledger und werden sofort faellig."""
    state = tmp_path / "state"
    state.mkdir()
    monkeypatch.setenv("PPU_STATE_DIR", str(state))
    completed = state / "completed.csv"
    completed.write_text(
        "Fingerprint,Sha256,RelativePath,Size,CompletedUtc,Reason\n"
        "fp-belegt,,a.jpg,100,2026-10-01T00:00:00+00:00,"
        "Android receipt after confirmed Google Photos free-up\n"
        "fp-angenommen,,b.jpg,200,2026-10-02T00:00:00+00:00,"
        "Assumed completed after 1 unverified attempts (Google Photos refuses free-up)\n",
        encoding="utf-8")
    rows = store.requeue_assumed(limit=5, path=completed, unverified=state / "unverified.csv")
    assert [r["RelativePath"] for r in rows] == ["b.jpg"]
    rest = completed.read_text(encoding="utf-8")
    assert "a.jpg" in rest and "b.jpg" not in rest
    due = store.due_unverified(state / "unverified.csv")
    assert [r["Fingerprint"] for r in due] == ["fp-angenommen"]
    assert due[0]["Attempts"] == "1"
