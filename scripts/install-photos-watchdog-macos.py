#!/usr/bin/env python3
"""Installiert den gewaehlten Mac-Waechter als Benutzer-LaunchAgent, ohne sudo."""
import argparse
import os
import plistlib
import subprocess
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Mac-Fortschrittswächter einrichten")
    parser.add_argument("--device", required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    python = root / ".venv/bin/python"
    adb = Path.home() / ".local/bin/adb"
    if not python.exists() or not adb.exists():
        raise SystemExit("Python-Umgebung oder ADB fehlt; kein Dienst installiert.")
    label = "de.pixelphotouploader.photos-watchdog"
    state = Path.home() / ".pixel-photo-uploader/photos-watchdog"
    state.mkdir(parents=True, exist_ok=True)
    path = Path.home() / "Library/LaunchAgents" / (label + ".plist")
    path.parent.mkdir(parents=True, exist_ok=True)
    plist = {"Label": label, "ProgramArguments": [str(python), "-m", "app.photos_watchdog",
              "--adb", str(adb), "--device", args.device, "--state-dir", str(state),
              "--allow-restart", "--notify-macos"], "WorkingDirectory": str(root),
             "RunAtLoad": True, "KeepAlive": True, "ThrottleInterval": 60,
             "ProcessType": "Background", "StandardOutPath": str(state / "watchdog.log"),
             "StandardErrorPath": str(state / "watchdog-error.log")}
    with path.open("wb") as output:
        plistlib.dump(plist, output)
    domain = f"gui/{os.getuid()}"
    loaded = subprocess.run(["launchctl", "print", domain + "/" + label], capture_output=True)
    if loaded.returncode == 0:
        subprocess.run(["launchctl", "bootout", domain + "/" + label], check=True)
    subprocess.run(["launchctl", "bootstrap", domain, str(path)], check=True)
    print(path)


if __name__ == "__main__":
    main()
