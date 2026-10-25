#!/usr/bin/env python3
"""Lokaler Deploy auf die bestehende ZimaOS-Installation und das Upload-Pixel."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import shlex
import subprocess
import sys
import tarfile
import time
import urllib.request
import uuid
import xml.etree.ElementTree as ET

import yaml

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "de.pixelphotouploader.companion"
SERIAL = "FA69M0305152"
SERVICES = ("server", "watcher", "photos-watchdog")
COMPOSE_RELEASE = "v2.40.3"
# Fixierte Hashes aus dem offiziellen docker:28.5.2-cli Image-Build:
# https://hub.docker.com/layers/library/docker/28.5.2-cli/images/sha256-46614afd2a03924b7e855830c9213ac0018635283e2142c154a497bf343cf0e4
COMPOSE_SHA256 = {
    "x86_64": "dba9d98e1ba5bfe11d88c99b9bd32fc4a0624a30fafe68eea34d61a3e42fd372",
    "aarch64": "d26373b19e89160546d15407516cc59f453030d9bc5b43ba7faf16f7b4980137",
}
COMPOSE_PLUGIN_DIRS = (
    "/usr/local/lib/docker/cli-plugins", "/usr/local/libexec/docker/cli-plugins",
    "/usr/lib/docker/cli-plugins", "/usr/libexec/docker/cli-plugins",
)


def run(args, *, data=None, capture=True, timeout=120):
    result = subprocess.run(args, input=data, stdout=subprocess.PIPE if capture else None,
                            check=True, timeout=timeout)
    return result.stdout if capture else b""


def authenticate_sudo(ssh, host):
    """Bei Bedarf sudo interaktiv authentifizieren, solange noch nichts gestoppt ist."""
    command = ["ssh", "-tt", "-o", "ConnectTimeout=10", "-i", ssh[-2], host, "sudo -v"]
    print("Die NAS benötigt ein sudo-Passwort, um ihre ZimaOS-Compose-Datei zu aktualisieren.",
          flush=True)
    print("Gib das NAS-Passwort in der folgenden SSH-Abfrage ein; es wird nicht gespeichert.",
          flush=True)
    subprocess.run(command, check=True, timeout=120)


def preferences(raw):
    result = {}
    for item in ET.fromstring(raw):
        result[item.get("name")] = item.get("value", item.text or "")
    return result


def updated_compose(original, image, version):
    """Nur Images und Versionsmetadatum aendern; insbesondere alle Mounts erhalten."""
    config = yaml.safe_load(original)
    if not isinstance(config, dict) or not isinstance(config.get("services"), dict):
        raise RuntimeError("Ungültige vorhandene Compose-Datei.")
    for service in SERVICES:
        if service not in config["services"]:
            raise RuntimeError(f"{service} fehlt in der bestehenden Compose-Datei.")
        config["services"][service]["image"] = image
    config.setdefault("x-casaos", {})["version"] = version
    return yaml.safe_dump(config, allow_unicode=True, sort_keys=False).encode()


def compose_cli(remote):
    """ZimaOS kann Compose als eigenstaendiges Programm statt als Plugin liefern."""
    for command in (("docker", "compose"), ("docker-compose",)):
        try:
            remote(*command, "version")
            return list(command)
        except subprocess.CalledProcessError:
            continue
    for directory in COMPOSE_PLUGIN_DIRS:
        path = directory + "/docker-compose"
        try:
            remote("test", "-x", path)
            remote(path, "version")
            return [path]
        except subprocess.CalledProcessError:
            continue
    raise RuntimeError("Auf der NAS ist weder docker compose noch docker-compose verfügbar.")


def download_bytes(url):
    with urllib.request.urlopen(url, timeout=120) as response:
        return response.read()


def provision_compose(remote, fetch=download_bytes):
    """Gepruefte Linux-Binaerdatei im eigenen Deploy-Verzeichnis bereitstellen."""
    if remote("uname", "-s").strip() != b"Linux":
        raise RuntimeError("Automatische Compose-Bereitstellung benötigt eine Linux-NAS.")
    arch = remote("uname", "-m").decode().strip()
    arch = {"amd64": "x86_64", "arm64": "aarch64"}.get(arch, arch)
    if arch not in COMPOSE_SHA256:
        raise RuntimeError(f"Keine geprüfte Compose-Datei für NAS-Architektur {arch} hinterlegt.")
    directory = "/DATA/AppData/pixel-photo-uploader/deploy-tools"
    target = f"{directory}/docker-compose-{COMPOSE_RELEASE}-{arch}"
    expected = COMPOSE_SHA256[arch]
    try:
        remote("test", "-x", target)
        digest = remote("sha256sum", target).decode().split()[0]
        if digest == expected:
            remote(target, "version")
            return [target]
    except subprocess.CalledProcessError:
        pass
    url = f"https://github.com/docker/compose/releases/download/{COMPOSE_RELEASE}/docker-compose-linux-{arch}"
    print(f"Lade geprüfte Compose-Version {COMPOSE_RELEASE} für NAS/{arch} auf den Mac …", flush=True)
    binary = fetch(url)
    if hashlib.sha256(binary).hexdigest() != expected:
        raise RuntimeError("Compose-Prüfsumme stimmt nicht; die Datei wird nicht installiert.")
    remote("mkdir", "-p", directory)
    remote("chmod", "700", directory)
    temporary = target + ".part-" + uuid.uuid4().hex
    remote("sh", "-c", 'set -eu\numask 077\ncat > "$1"\nchmod 700 "$1"\nmv -f "$1" "$2"',
           "sh", temporary, target, data=binary)
    if remote("sha256sum", target).decode().split()[0] != expected:
        raise RuntimeError("Compose-Prüfsumme auf der NAS stimmt nicht; kein Deploy gestartet.")
    remote(target, "version")
    return [target]


def compose_up_options(remote, compose):
    """Alte Compose-Versionen kennen die Option --pull never noch nicht."""
    help_text = remote(*compose, "up", "--help").decode()
    options = ["up", "-d", "--no-build"]
    if "--pull" in help_text and "never" in help_text:
        options += ["--pull", "never"]
    return options


def compose_writer(remote, path, authenticate=None):
    """Vorab feststellen, ob die bestehende ZimaOS-Datei beschrieben werden kann."""
    try:
        remote("test", "-w", path)
        return "user"
    except subprocess.CalledProcessError:
        try:
            remote("sudo", "-n", "test", "-w", path)
            return "sudo"
        except subprocess.CalledProcessError as error:
            if authenticate is not None:
                authenticate()
                remote("sudo", "-n", "test", "-w", path)
                return "sudo"
            raise RuntimeError(
                f"{path} ist schreibgeschützt und sudo -n darf sie nicht ändern. "
                "Keine Dienste wurden angehalten.") from error


def replace_compose(remote, writer, path, staged_path, ownership):
    """Die aktive Compose-Datei atomar ersetzen und Mode/Owner erhalten."""
    if writer == "sudo":
        uid, gid, mode = ownership.split(":")
        remote("sudo", "-n", "install", "-o", uid, "-g", gid, "-m", mode,
               staged_path, path)
    else:
        data = remote("cat", staged_path)
        remote("sh", "-c", 'cat > "$1"', "sh", path, data=data)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="ysamjo@192.168.178.162")
    parser.add_argument("--identity", default=str(Path.home() / ".ssh/id_ed25519_zimaos"))
    parser.add_argument("--pixel-device", default="192.168.178.53:5555")
    args = parser.parse_args()
    ssh = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "-i", args.identity, args.host]

    def remote(*command, data=None, capture=True, timeout=120):
        return run(ssh + [shlex.join(command)], data=data, capture=capture, timeout=timeout)

    desired = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
    image = desired["services"]["server"]["image"]
    version = desired["x-casaos"]["version"]
    apk_dir = ROOT / "android/PixelPhotoCompanion/app/build/outputs/apk/debug"
    apk = apk_dir / "app-debug.apk"
    metadata = json.loads((apk_dir / "output-metadata.json").read_text())["elements"][0]
    if not apk.is_file():
        raise RuntimeError("Debug-APK fehlt; zuerst Gradle-Build ausführen.")
    java_root = ROOT / "android/PixelPhotoCompanion/app/src/main"
    sources = [p for p in java_root.rglob("*") if p.is_file()]
    sources += [ROOT / "android/PixelPhotoCompanion/app/build.gradle"]
    if any(p.stat().st_mtime > apk.stat().st_mtime for p in sources):
        raise RuntimeError("Android-Quellen sind neuer als die APK; zuerst neu bauen.")

    print("Prüfe NAS und dediziertes Upload-Pixel …", flush=True)
    ids = remote("docker", "ps", "-aq").decode().split()
    containers = json.loads(remote("docker", "inspect", *ids)) if ids else []
    candidates = [c for c in containers if (c["Config"].get("Labels") or {}).get(
        "com.docker.compose.service") == "server" and
        c["Config"]["Image"].split(":")[0].endswith("pixel-photo-uploader")]
    if len(candidates) != 1:
        raise RuntimeError("Uploader-Projekt auf der NAS ist nicht eindeutig.")
    server = candidates[0]
    labels = server["Config"]["Labels"]
    project = labels["com.docker.compose.project"]
    config_files = labels["com.docker.compose.project.config_files"].split(",")
    if len(config_files) != 1 or not config_files[0].startswith("/"):
        raise RuntimeError("Mehrere oder relative Compose-Dateien: manueller Abgleich erforderlich.")
    config_path = config_files[0]
    writer = compose_writer(remote, config_path,
                            authenticate=lambda: authenticate_sudo(ssh, args.host))
    ownership = remote("stat", "-c", "%u:%g:%a", config_path).decode().strip()
    live = {c["Config"]["Labels"].get("com.docker.compose.service"): c for c in containers
            if (c["Config"].get("Labels") or {}).get("com.docker.compose.project") == project}
    for service in SERVICES:
        if service not in live or not live[service]["State"]["Running"]:
            raise RuntimeError(f"{service} läuft nicht; bestehende Pause zuerst prüfen.")
    original = remote("cat", config_path)
    updated = updated_compose(original, image, version)
    project_dir = labels.get("com.docker.compose.project.working_dir", str(Path(config_path).parent))
    try:
        cli = compose_cli(remote)
    except RuntimeError:
        cli = provision_compose(remote)
    print(f"Verwende {' '.join(cli)} auf der NAS.", flush=True)
    compose = [*cli, "--project-name", project,
               "--project-directory", project_dir, "-f", config_path]
    up_options = compose_up_options(remote, compose)
    state_dirs = []
    for service in ("server", "watcher"):
        env = dict(v.split("=", 1) for v in live[service]["Config"]["Env"] if "=" in v)
        state_path = env.get("PPU_STATE_DIR", "/data/state")
        mounts = [m["Source"] for m in live[service]["Mounts"] if m["Destination"] == state_path
                  and m["Type"] == "bind"]
        if len(mounts) != 1:
            raise RuntimeError("State-Bind-Mount ist nicht eindeutig.")
        state_dirs += mounts
    if state_dirs[0] != state_dirs[1]:
        raise RuntimeError("Server und Watcher verwenden verschiedene Zustandsordner.")

    transports = run(["adb", "devices"]).decode().splitlines()
    device = SERIAL if any(line.startswith(SERIAL + "\tdevice") for line in transports) else args.pixel_device
    if device != SERIAL and ":" in device:
        run(["adb", "connect", device], capture=False)

    def adb(*command, capture=True):
        return run(["adb", "-s", device, *command], capture=capture)

    if (adb("shell", "getprop", "ro.product.model").strip() != b"Pixel"
            or adb("shell", "getprop", "ro.serialno").strip() != SERIAL.encode()):
        raise RuntimeError("ADB-Ziel ist nicht das dedizierte Upload-Pixel.")
    pref_args = ("shell", "run-as", PACKAGE, "cat", "shared_prefs/pixel_photo_companion.xml")
    old_prefs = adb(*pref_args)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = f"/DATA/AppData/pixel-photo-uploader/deploy-backups/{stamp}"
    work = backup + "/source"
    remote("mkdir", "-p", work)
    remote("chmod", "700", backup)
    remote("sh", "-c", 'umask 077; cat > "$1"', "sh", backup + "/compose-before.yml", data=original)
    remote("sh", "-c", 'umask 077; cat > "$1"', "sh", backup + "/pixel-preferences-before.xml", data=old_prefs)
    remote("sh", "-c", 'cat > "$1"', "sh", backup + "/compose-new.yml", data=updated)
    candidate = [*cli, "--project-name", project, "--project-directory",
                 project_dir,
                 "-f", backup + "/compose-new.yml"]
    remote(*candidate, "config", "--quiet")
    payload = io.BytesIO()
    with tarfile.open(fileobj=payload, mode="w:gz") as archive:
        for name in ("Dockerfile", "requirements.txt", "app"):
            archive.add(ROOT / name, arcname=name,
                        filter=lambda item: None if "__pycache__" in item.name or item.name.endswith(".pyc") else item)
    remote("tar", "-xzf", "-", "-C", work, data=payload.getvalue())
    print(f"Baue {image} auf der NAS; bestehende Dienste laufen weiter …", flush=True)
    remote("docker", "build", "-t", image, work, capture=False, timeout=1800)
    remote("docker", "run", "--rm", "--entrypoint", "python", image,
           "-c", f"from app import APP_VERSION; assert APP_VERSION == {version!r}")

    print(f"Sichere Zustand nach {backup}; aktualisiere Companion und Container …", flush=True)
    stopped = False
    started = False
    try:
        stopped = True
        remote(*compose, "stop", "--timeout", "120", *SERVICES, capture=False, timeout=180)
        remote("tar", "-czf", backup + "/state-before.tar.gz", "-C", state_dirs[0], ".", timeout=300)
        # Installieren erhaelt App-Daten. MainActivity nimmt nur zuvor aktivierte Ueberwachung wieder auf.
        adb("install", "-r", str(apk), capture=False)
        adb("shell", "am", "start", "-n", PACKAGE + "/.MainActivity", capture=False)
        installed = adb("shell", "dumpsys", "package", PACKAGE).decode()
        if f"versionName={metadata['versionName']}" not in installed:
            raise RuntimeError("Installierte Companion-Version stimmt nicht.")
        after = preferences(adb(*pref_args))
        before = preferences(old_prefs)
        for key in ("enabled", "safetyAccepted"):
            if after.get(key) != before.get(key):
                raise RuntimeError(f"Companion-Einstellung {key} wurde unerwartet verändert.")
        replace_compose(remote, writer, config_path, backup + "/compose-new.yml", ownership)
        remote(*compose, *up_options, *SERVICES,
               capture=False, timeout=180)
        started = True
    except BaseException:
        if stopped and not started:
            print("Deploy unterbrochen; stelle ursprüngliche Compose-Datei und Container wieder her. "
                  "Ledger bleiben erhalten.", flush=True)
            replace_compose(remote, writer, config_path, backup + "/compose-before.yml", ownership)
            remote(*compose, *up_options, *SERVICES,
                   capture=False, timeout=180)
        raise

    # Nach Recreate die aktuellen Container-IDs abfragen.
    current = {s: remote(*compose, "ps", "-q", s).decode().strip() for s in SERVICES}
    for service, container in current.items():
        if not container:
            raise RuntimeError(f"{service}: kein laufender Container nach Deploy.")
        actual = remote("docker", "exec", container, "python", "-c",
                        "from app import APP_VERSION; print(APP_VERSION)").decode().strip()
        if actual != version:
            raise RuntimeError(f"{service}: unerwartete Version {actual}.")
    status_code = ("import json,urllib.request; "
                   "print(json.dumps(json.load(urllib.request.urlopen('http://127.0.0.1:8000/api/status', timeout=30))))")
    status = None
    for attempt in range(6):
        try:
            status = json.loads(remote("docker", "exec", current["server"], "python", "-c", status_code))
            break
        except subprocess.CalledProcessError:
            time.sleep(5)
    if not status or status.get("version") != version or not status.get("configured"):
        raise RuntimeError("Status-API nach Deploy nicht gesund oder nicht konfiguriert.")
    remote("sh", "-c", 'cat > "$1"', "sh", backup + "/status-after.json",
           data=json.dumps(status, ensure_ascii=False, indent=2).encode())
    if preferences(old_prefs).get("enabled") == "true":
        first = preferences(adb(*pref_args))
        print("Prüfe zwei Companion-Lebenszeichen mit 35 Sekunden Abstand …", flush=True)
        time.sleep(35)
        second = preferences(adb(*pref_args))
        services = adb("shell", "dumpsys", "activity", "services", PACKAGE + "/.BackupMonitorService").decode()
        if (int(second.get("updatedAt", "0")) <= int(first.get("updatedAt", "0"))
                or not any("app=ProcessRecord" in line for line in services.splitlines())):
            raise RuntimeError("Neue Versionen sind installiert, Companion-Lebenszeichen ist noch nicht bestätigt.")
        print(f"Companion lebt: Phase {second.get('phase')}, Status {second.get('serviceStatus')}")
    print(f"Deploy bestätigt: alle drei NAS-Dienste {version}, Companion {metadata['versionName']}.")
    print(f"Sicherung und Status: {backup}")
    print("Ein vollständiger Upload-Zyklus ist damit noch nicht nachgewiesen.")


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
        print(f"Deploy nicht abgeschlossen: {error}", file=sys.stderr)
        sys.exit(1)
