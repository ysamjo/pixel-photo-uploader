"""ADB-Waechter: Fortschritt messen, Fotos einmal neu starten, danach melden.

Keine Geraeteneustarts, Dateiloeschungen, MediaScans oder automatischen Belege.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

PHOTOS = "com.google.android.apps.photos"
COMPANION = "de.pixelphotouploader.companion"
PIXEL_SERIAL = "FA69M0305152"
STALL_SECONDS = 30 * 60
COOLDOWN_SECONDS = 60 * 60
MIN_TX_PROGRESS = 8 * 1024 * 1024

# Bekannte Speicherfresser auf dem dedizierten Pixel. `/data` ist die harte Kante;
# die uebrigen Pfade beantworten die Frage, wohin der Platz gegangen ist, ohne dass
# jemand sich per Kabel einloggen muss. Google-Fotos' interner Cache unter
# /data/data/... ist fuer die Shell nicht lesbar — nur sein externer Anteil.
STORAGE_HOGS = {
    "share": "/sdcard/DCIM/PixelSync",
    "staging": "/sdcard/DCIM/PixelSync/staging",
    "photos_external": "/sdcard/Android/data/com.google.android.apps.photos",
    "thumbnails": "/sdcard/DCIM/.thumbnails",
    "lost_dir": "/sdcard/LOST.DIR",
    "trashed": "/sdcard/DCIM/.trashed",
    "local_tmp": "/data/local/tmp",
}


@dataclass(frozen=True)
class Sample:
    batch: str
    tx_bytes: int
    remaining: int | None = None


def advance(state: dict, sample: Sample, now: float) -> tuple[dict, str]:
    """Persistenter Automat; ein Neustartbudget pro Batch, auch nach Prozessneustart."""
    s = dict(state)
    if s.get("batch") != sample.batch:
        s = {"batch": sample.batch, "stage": "tracking", "last_progress": now,
             "tx_anchor": sample.tx_bytes, "remaining": sample.remaining, "last_sample": now}
        return s, "tracking"
    # Offline-Zeit, Schlaf des Hosts und Uhrspruenge sind kein nachgewiesener Stillstand.
    if now < s.get("last_sample", now) or now - s.get("last_sample", now) > 150:
        s.update(last_progress=now, tx_anchor=sample.tx_bytes, remaining=sample.remaining)
        if s.get("stage") == "cooldown":
            s["cooldown_until"] = now + COOLDOWN_SECONDS
    s["last_sample"] = now
    if sample.tx_bytes < s["tx_anchor"]:
        s.update(tx_anchor=sample.tx_bytes, last_progress=now)
    old_remaining = s.get("remaining")
    progressed = (sample.tx_bytes - s["tx_anchor"] >= MIN_TX_PROGRESS
                  or (sample.remaining is not None and old_remaining is not None
                      and sample.remaining < old_remaining))
    if sample.remaining is not None:
        s["remaining"] = sample.remaining
    if progressed:
        s.update(last_progress=now, tx_anchor=sample.tx_bytes)
        if s["stage"] == "cooldown":
            s["stage"] = "restarted"
    if s["stage"] == "alert":
        return s, "alert"
    if s["stage"] == "cooldown":
        if now >= s["cooldown_until"]:
            s["stage"] = "alert"
            return s, "alert"
        return s, "cooldown"
    if now - s["last_progress"] >= STALL_SECONDS:
        if s["stage"] == "tracking":
            # Vor dem ADB-Aufruf persistieren: auch ein Crash darf keine Neustartschleife erzeugen.
            s.update(stage="restarted", last_progress=now, tx_anchor=sample.tx_bytes)
            return s, "restart"
        s.update(stage="cooldown", cooldown_until=now + COOLDOWN_SECONDS)
        return s, "cooldown"
    return s, s["stage"]


def wifi_tx(text: str, uid: int) -> int:
    active = False
    found = False
    total = 0
    for line in text.splitlines():
        if "ident=" in line:
            active = ("type=WIFI" in line and f"uid={uid} " in line and "tag=0x0" in line)
            found |= active
        if active:
            match = re.search(r"\bst=\d+.*?\btb=(\d+)", line)
            if match:
                total += int(match[1])
    if not found:
        raise ValueError("Keine verlässliche WLAN-Messung für Google Fotos verfügbar")
    return total


def preferences(xml: str) -> dict:
    result = {}
    for e in ET.fromstring(xml):
        raw = (e.text or "") if e.tag == "string" else e.get("value", "")
        if e.tag == "boolean":
            raw = raw == "true"
        elif e.tag in {"int", "long"}:
            raw = int(raw)
        result[e.get("name")] = raw
    return result


def eligible(prefs: dict, now: float) -> bool:
    # Freigabe- und Belegphasen nie unterbrechen; Pausieren und harte Fehler respektieren.
    phase = prefs.get("phase")
    detail = str(prefs.get("detail", "")).lower()
    transient_error = phase == "ERROR" and ("seit 30 minuten" in detail or "backup paused" in detail)
    return bool(prefs.get("enabled") and prefs.get("safetyAccepted")
                and prefs.get("batchPaths") and prefs.get("batchStartedAt", 0) > 0
                and 0 <= now * 1000 - prefs["batchStartedAt"] < 72 * 60 * 60 * 1000
                and (phase == "WAIT_BACKUP" or transient_error)
                and not prefs.get("pendingReceiptPaths") and not prefs.get("pendingReceiptRefused"))


def batch_key(prefs: dict) -> str:
    return hashlib.sha256((str(prefs["batchStartedAt"]) + "\n" + prefs["batchPaths"]).encode()).hexdigest()


def parse_df(text: str) -> dict | None:
    """`df -k`-Ausgabe in Bytes. Android zaehlt 1K-Bloecke in Feld 1..3.

    Die letzte Zeile mit drei Zahlen gewinnt: Android stellt manchen Mounts noch
    eine zweite Zeile voran, und eine feste Zeilennummer waere geraten.
    """
    for line in reversed(text.splitlines()):
        fields = line.split()
        if len(fields) < 4:
            continue
        try:
            used, available = int(fields[2]), int(fields[3])
        except ValueError:
            continue
        return {"freeBytes": available * 1024, "totalBytes": (used + available) * 1024}
    return None


def _first_int(lines: list[str]) -> int | None:
    for line in lines:
        value = line.strip().split()[0] if line.strip() else ""
        try:
            return int(value)
        except ValueError:
            continue
    return None


def parse_storage(text: str) -> dict:
    """ADB-Ausgabe in ein Speicherobjekt. Unbekanntes fehlt, statt geraten zu werden."""
    sections: dict[str, list[str]] = {}
    current = ""
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("@@"):
            current = line[2:].strip()
            sections[current] = []
            continue
        if current:
            sections[current].append(line)

    result: dict = {"hogs": {}}
    result.update(parse_df("\n".join(sections.get("df", []))) or {})
    for name in STORAGE_HOGS:
        kb = _first_int(sections.get(name, []))
        if kb is not None:
            result["hogs"][name] = kb * 1024
    for key, section in (("partialCount", "partial_count"), ("tempCount", "temp_count")):
        value = _first_int(sections.get(section, []))
        if value is not None:
            result[key] = value
    partial_kb = _first_int(sections.get("partial_kb", []))
    if partial_kb is not None:
        result["partialBytes"] = partial_kb * 1024
    return result


class Adb:
    def __init__(self, binary: str, device: str):
        self.binary, self.device = binary, device

    def run(self, *args: str, data: str | None = None) -> str:
        p = subprocess.run([self.binary, "-s", self.device, *args], input=data,
                           text=True, capture_output=True, timeout=30, check=True)
        output = p.stdout.strip()
        if output.startswith(("Error:", "Permission Denial")):
            raise ValueError(output)
        return output

    def connect(self) -> None:
        if ":" in self.device:
            subprocess.run([self.binary, "connect", self.device], capture_output=True,
                           text=True, timeout=15, check=True)
        if (self.run("shell", "getprop", "ro.serialno") != PIXEL_SERIAL
                or self.run("shell", "getprop", "ro.product.model") != "Pixel"):
            raise ValueError("Ziel ist nicht das dedizierte Upload-Pixel; keine Aktion erlaubt")

    def sample(self, now: float) -> Sample | None:
        prefs = preferences(self.run("shell", "run-as", COMPANION, "cat",
                                    "shared_prefs/pixel_photo_companion.xml"))
        if not eligible(prefs, now):
            return None
        package = self.run("shell", "dumpsys", "package", PHOTOS)
        match = re.search(r"\buserId=(\d+)", package)
        if not match:
            raise ValueError("Google Fotos fehlt oder seine UID ist unbekannt")
        # Android 10 gibt bei --poll nur 'Forced poll' aus: getrennt abfragen.
        self.run("shell", "dumpsys", "netstats", "--poll")
        tx = wifi_tx(self.run("shell", "dumpsys", "netstats", "--full", "--uid"), int(match[1]))
        remaining = prefs.get("photosRemaining")
        observed = prefs.get("photosRemainingAt", 0)
        if not 0 <= now * 1000 - observed <= 120_000:
            remaining = None
        # Keine Dateinamen im Status; erst ein neuer Batch stellt das Neustartbudget wieder her.
        batch = batch_key(prefs)
        return Sample(batch, tx, remaining)

    def storage(self) -> dict:
        """Freier Speicher und bekannte Fresser in einem einzigen ADB-Aufruf.

        Ohne Wurzelrechte nicht messbar: Googles interner App-Cache unter
        /data/data/<paket> — deshalb der externe Anteil. `du` laeuft ueber die
        Freigabe, ist also der teure Teil; er bleibt ohne Einfluss auf das
        Neustartbudget und darf fehlschlagen.
        """
        lines = ["echo '@@df'", "df -k /data"]
        for name, path in STORAGE_HOGS.items():
            lines += [f"echo '@@{name}'", f"du -sk {path} 2>/dev/null"]
        lines += [
            "echo '@@partial_count'",
            "find /sdcard/DCIM/PixelSync -name '*.!sync' -type f 2>/dev/null | wc -l",
            "echo '@@partial_kb'",
            # Kein Glob: die Teilkopien liegen unterschiedlich tief (staging/Batches/<id>/x.!sync),
            # und ein Glob auf feste Tiefe meldete still 0 Byte. `find -exec du` bricht mit
            # dem tieferen Ordner nicht und meldet nur, was wirklich da ist.
            "find /sdcard/DCIM/PixelSync -name '*.!sync' -type f -exec du -k {} ';' "
            "2>/dev/null | awk '{s+=$1} END {print s+0}'",
            "echo '@@temp_count'",
            "find /sdcard/DCIM/PixelSync/control -name '.receipt-*.tmp' -type f 2>/dev/null | wc -l",
        ]
        return parse_storage(self.run("shell", "; ".join(lines)))

    def restart_photos(self, expected_batch: str) -> None:
        self.connect()
        # Unmittelbar vor Eingriff nochmals pruefen: kein inzwischen begonnener Freigabedialog.
        prefs = preferences(self.run("shell", "run-as", COMPANION, "cat",
                                    "shared_prefs/pixel_photo_companion.xml"))
        if not eligible(prefs, time.time()) or batch_key(prefs) != expected_batch:
            raise ValueError("Neustart ausgelassen: Sicherung ist pausiert oder in einer Freigabephase")
        self.run("shell", "am", "force-stop", PHOTOS)
        self.run("shell", "am", "start", "-n", PHOTOS + "/.home.HomeActivity")

    def report(self, status: dict) -> None:
        # Debug-Companion zeigt diese Meldung in Status und Vordergrundbenachrichtigung.
        self.run("shell", f"run-as {COMPANION} sh -c 'cat > files/photos-watchdog-status.tmp && mv files/photos-watchdog-status.tmp files/photos-watchdog-status.json'",
                 data=json.dumps(status, ensure_ascii=False))


def save(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


MESSAGES = {
    "tracking": "Uploadfortschritt wird überwacht.",
    "restarted": "Google Fotos wurde einmal neu gestartet; Fortschritt wird geprüft.",
    "restart": "30 Minuten ohne Fortschritt: Google Fotos wird einmal neu gestartet.",
    "cooldown": "Erneuter Stillstand: eine Stunde Wartezeit, kein weiterer Neustart.",
    "alert": "Google Fotos bleibt ohne Fortschritt. Bitte prüfen; kein weiterer automatischer Neustart.",
    "inactive": "Kein aktiver Sicherungsbatch; kein Eingriff.",
    "offline": "Upload-Pixel nicht messbar: ADB-Verbindung oder Freigabe prüfen. Kein Eingriff.",
}


def storage_sample(adb: Adb) -> dict | None:
    """Speichermessung darf den Fortschrittswaechter nie anhalten.

    Ein fehlgeschlagenes `du` ist kein Stillstand von Google Fotos: dann fehlt nur
    die Speicherzahl, der Neustart-Automat laeuft unveraendert weiter.
    """
    try:
        return adb.storage()
    except (subprocess.SubprocessError, OSError, ValueError):
        return None


def cycle(adb: Adb, state_path: Path, allow_restart: bool, now: float | None = None) -> dict:
    now = time.time() if now is None else now
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    storage = None
    try:
        adb.connect()
        storage = storage_sample(adb)
        if storage is not None:
            storage["observedAt"] = now
        sample = adb.sample(now)
        if sample is None:
            action = "inactive"  # Budget nicht loeschen: Pausieren ist kein neuer Batch.
        else:
            state, action = advance(state, sample, now)
            if action == "restart" and not allow_restart:
                state["stage"] = "alert"
                action = "alert"
            save(state_path, state)
            if action == "restart":
                adb.restart_photos(sample.batch)
        status = {"state": action, "message": MESSAGES[action], "observedAt": now,
                  "txBytes": sample.tx_bytes if sample else None,
                  "remaining": sample.remaining if sample else None,
                  "cooldownUntil": state.get("cooldown_until"),
                  "storage": storage}
        adb.report(status)
    except (subprocess.SubprocessError, OSError, ValueError, ET.ParseError) as exc:
        status = {"state": "offline", "message": MESSAGES["offline"], "observedAt": now,
                  "error": str(exc), "storage": storage}
    save(state_path.with_name("photos-watchdog-status.json"), status)
    print(json.dumps(status, ensure_ascii=False), flush=True)
    return status


def main(argv: list[str] | None = None) -> None:
    from . import state_root
    parser = argparse.ArgumentParser(description="Google-Fotos-Wächter; niemals Geräteneustarts")
    parser.add_argument("--device", required=True, help="ADB-Transport des Pixel 1, z.B. IP:5555")
    parser.add_argument("--adb", default="adb")
    parser.add_argument("--state-dir", type=Path, default=state_root() / "photos-watchdog")
    parser.add_argument("--allow-restart", action="store_true", help="Ein Google-Fotos-Neustart pro Batch erlaubt")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args(argv)
    args.state_dir.mkdir(parents=True, exist_ok=True)
    # Mac und NAS: nur eine Instanz darf das persistente Neustartbudget verwalten.
    import fcntl
    with (args.state_dir / "watchdog.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        adb = Adb(args.adb, args.device)
        while True:
            status = cycle(adb, args.state_dir / "photos-watchdog.json", args.allow_restart)
            if args.once:
                break
            time.sleep(60)


if __name__ == "__main__":
    main()
