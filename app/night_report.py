"""Nachtbilanz aus Erfolgsbelegen; auch allein mit Python ausfuehrbar."""
from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

RECEIPT_REASON = "Android receipt after confirmed Google Photos free-up"
DUPLICATE_REASON = "Identical content already completed"


def night_window(now: datetime | None = None) -> dict:
    """Letzte oder laufende Nacht, 22 bis 08 Uhr in Europe/Berlin."""
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("now needs a timezone")
    local = current.astimezone(ZoneInfo("Europe/Berlin"))
    end_day = local.date() + timedelta(days=int(local.hour >= 22))
    start = datetime.combine(end_day - timedelta(days=1), time(22), local.tzinfo)
    end = datetime.combine(end_day, time(8), local.tzinfo)
    return {"start": start.isoformat(), "end": end.isoformat(),
            "until": min(current, end).astimezone(local.tzinfo).isoformat(),
            "timezone": "Europe/Berlin", "ongoing": current < end,
            "receipt_bytes": 0, "receipt_count": 0,
            "duplicate_bytes": 0, "duplicate_count": 0,
            "other_bytes": 0, "other_count": 0}


def count_row(report: dict, row: dict) -> None:
    """Nur Buchungen im halboffenen Nachtfenster und bis jetzt zaehlen."""
    try:
        stamp = datetime.fromisoformat(str(row.get("CompletedUtc", "")).replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        size = max(0, int(row.get("Size", "") or 0))
    except (ValueError, TypeError):
        return
    if not (datetime.fromisoformat(report["start"]) <= stamp
            < datetime.fromisoformat(report["end"])
            and stamp <= datetime.fromisoformat(report["until"])):
        return
    reason = row.get("Reason", "")
    group = ("receipt" if reason == RECEIPT_REASON else
             "duplicate" if reason == DUPLICATE_REASON else "other")
    report[group + "_bytes"] += size
    report[group + "_count"] += 1


def main() -> None:
    parser = argparse.ArgumentParser(description="Nachtbilanz: 22–08 Uhr Europe/Berlin, nur lesend")
    parser.add_argument("ledger", type=Path, help="Pfad zu completed.csv")
    args = parser.parse_args()
    report = night_window()
    # Fehlendes Ledger ist kein gemessener Null-Upload.
    with args.ledger.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        if not {"CompletedUtc", "Size", "Reason"}.issubset(reader.fieldnames or []):
            parser.error("Ledger braucht CompletedUtc, Size und Reason")
        for row in reader:
            count_row(report, row)
    report["receipt_gib"] = round(report["receipt_bytes"] / 1024**3, 2)
    report["duplicate_gib"] = round(report["duplicate_bytes"] / 1024**3, 2)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
