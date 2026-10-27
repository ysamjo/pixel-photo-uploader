"""Nachtfenster: Berliner Zeit, Zeitumstellung und belastbare Erfolgsbelege."""
import csv
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest

from app.night_report import DUPLICATE_REASON, RECEIPT_REASON, count_row, night_window
from app.store import COMPLETED_FIELDS, completion_totals


@pytest.mark.parametrize("now,start,end,hours,ongoing", [
    ("2026-10-26T11:00:00+00:00", "2026-10-25T22:00:00+01:00", "2026-10-26T08:00:00+01:00", 10, False),
    ("2026-10-25T11:00:00+00:00", "2026-10-24T22:00:00+02:00", "2026-10-25T08:00:00+01:00", 11, False),
    ("2026-03-29T11:00:00+00:00", "2026-03-28T22:00:00+01:00", "2026-03-29T08:00:00+02:00", 9, False),
    ("2026-10-26T21:00:00+00:00", "2026-10-26T22:00:00+01:00", "2026-10-27T08:00:00+01:00", 10, True),
    ("2026-10-26T00:00:00+00:00", "2026-10-25T22:00:00+01:00", "2026-10-26T08:00:00+01:00", 10, True),
    ("2026-10-26T07:00:00+00:00", "2026-10-25T22:00:00+01:00", "2026-10-26T08:00:00+01:00", 10, False),
])
def test_nachtfenster_und_zeitumstellung(now, start, end, hours, ongoing):
    report = night_window(datetime.fromisoformat(now))
    assert report["start"] == start
    assert report["end"] == end
    assert (datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds() == hours * 3600
    assert report["ongoing"] is ongoing


def test_bilanz_trennt_erfolgsbelege_duplikate_und_unbekannte(tmp_path):
    ledger = tmp_path / "completed.csv"
    rows = [
        ("2026-10-25T20:59:59Z", 1, RECEIPT_REASON),  # vor 22 Uhr
        ("2026-10-25T21:00:00Z", 100, RECEIPT_REASON),
        ("2026-10-26T06:59:59Z", 200, RECEIPT_REASON),
        ("2026-10-26T07:00:00Z", 2, RECEIPT_REASON),  # 08 Uhr ausgeschlossen
        ("2026-10-26T01:00:00Z", 400, DUPLICATE_REASON),
        ("2026-10-26T02:00:00Z", 800, "legacy"),
        ("invalid", 1600, RECEIPT_REASON),
        ("2026-10-27T01:00:00Z", 3200, RECEIPT_REASON),  # Zukunft
    ]
    with ledger.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=COMPLETED_FIELDS)
        writer.writeheader()
        for stamp, size, reason in rows:
            writer.writerow({"CompletedUtc": stamp, "Size": size, "Reason": reason})
    totals = completion_totals(ledger, datetime.fromisoformat("2026-10-26T11:00:00+00:00"), include_night=True)
    assert totals["night"] == {
        "start": "2026-10-25T22:00:00+01:00", "end": "2026-10-26T08:00:00+01:00",
        "until": "2026-10-26T08:00:00+01:00", "timezone": "Europe/Berlin", "ongoing": False,
        "receipt_bytes": 300, "receipt_count": 2,
        "duplicate_bytes": 400, "duplicate_count": 1,
        "other_bytes": 800, "other_count": 1,
    }
    assert totals["recent_bytes"] == 1503


def test_laufende_nacht_ignoriert_zukuenftige_und_defekte_buchungen():
    report = night_window(datetime.fromisoformat("2026-10-26T00:00:00+00:00"))
    for stamp, size in [("2026-10-26T00:00:00Z", 100),
                        ("2026-10-26T01:00:00Z", 200),
                        ("2026-10-25T23:00:00Z", "bad")]:
        count_row(report, {"CompletedUtc": stamp, "Size": size, "Reason": RECEIPT_REASON})
    assert report["receipt_count"] == 1
    assert report["receipt_bytes"] == 100


def test_fehlendes_ledger_liefert_leere_nacht(tmp_path):
    report = completion_totals(tmp_path / "missing.csv", include_night=True)["night"]
    assert report["receipt_count"] == report["duplicate_count"] == report["other_count"] == 0


def test_einzeldatei_laeuft_ohne_installation_und_schreibt_nicht_ins_ledger(tmp_path):
    ledger = tmp_path / "completed.csv"
    with ledger.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=COMPLETED_FIELDS)
        writer.writeheader()
        writer.writerow({"CompletedUtc": night_window()["start"],
                         "Size": 2 * 1024**3, "Reason": RECEIPT_REASON})
    before = ledger.read_bytes()
    script = Path(__file__).resolve().parents[1] / "app" / "night_report.py"
    result = subprocess.run([sys.executable, str(script), str(ledger)],
                            cwd=tmp_path, capture_output=True, text=True, check=True)
    assert json.loads(result.stdout)["receipt_gib"] == 2.0
    assert ledger.read_bytes() == before
    missing = subprocess.run([sys.executable, str(script), str(tmp_path / "missing.csv")],
                             cwd=tmp_path, capture_output=True, text=True)
    assert missing.returncode != 0
    assert missing.stdout == ""
