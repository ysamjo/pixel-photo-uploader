# Pixel Photo Uploader — UmbrelOS-Port (App + Resilio)

Gleiche Logik wie das eingefrorene Windows-Skript (`PixelPhotoUploader.ps1`
3.3.12, siehe `../Archiv/Windows-PS1-eingefroren-3.3.12/`), nur der
**App + Resilio-Weg** (kein ADB, kein USB-Kabel). Container-Stand 3.3.14:
Import über Dateisystemgrenzen (EXDEV-Fallback für Cloud-Mounts) plus
Sync-Rest-Filter, dazu lineare Duplikatprüfung (Größen-Index), lineare
Rückbeleg-Abrechnung (Suffix-Set) und Checkpoint-Saves bei großen Batches.
Gepflegt wird nur noch der Container; die Windows-Variante ist archiviert
(siehe `../Archiv/Windows-PS1-eingefroren-3.3.12/` mit Migrationshinweis).

Einrichtung, Zähler und "Jetzt synchronisieren" laufen im Web-UI der App —
SSH ist im Regelbetrieb nicht noetig.

## Paket

```
umbrel-app.yml        Manifest (id = Ordnername)
docker-compose.yml    server (Web-UI) + watcher (Zyklen) + app_proxy
Dockerfile            python:3.12-slim, läuft als uid/gid 1000
app/                  Python-Kern
  config.py           config.json v3, Wurzel- und Schachtelprüfung
  fingerprints.py     Windows-kompatibler Zeitstempel + Fingerabdruck
  store.py            catalog/completed/staged + lastscan + Grundabgleich
  pipeline.py         Dropbox -> Inbox -> Archiv/YYYY.MM
  batches.py          Uebergabe in WindowsBatches/ + Rueckbelege
  sync.py             ein Durchlauf, Vorabcheck, Zahlen fuer CLI und Web
  runner.py           Sperre + "jetzt sincronisieren"-Bitte an den watcher
  watch.py            Poll-Schleife (weckt frueher, wenn etwas eingereiht ist)
  server.py           Statusseite, Setup-Formular, API
  cli.py              setup / sync / status / preflight / watch
data/...              legefreie Ordner fuer die Bind-Mounts (nur .gitkeep)
tests/                pytest, 48 Tests ohne Docker und ohne Netz
```

## Fingerabdruck kompatibel zum Windows-Katalog

`RelativePath` steht POSIX-Style (`a/b.jpg`), der Fingerabdruck normalisiert wie
der PS1 auf Backslash + Kleinbuchstaben. Der Zeitstempel liegt im
.NET-Format `'o'` vor (7 Nachkommastellen + `Z`), damit ein uebernommener
`catalog.csv` dieselben Fingerabdruecke erzeugt wie unter Windows.

## Grundabgleich statt Dauer-Suchen

- Ein Zyklus laeuft alle `RescanMinutes` (Standard 360) durch den
  Archiv-Ordner — aber nur durch Ordner, deren Schreibzeit seit dem letzten
  Lauf aelter als 24 h ist, als "geschlossen" behandelt wird.
- Neue Dateien in geschlossenen Ordnern findet der naechste **Vollabgleich**,
  spaetestens alle `DeepRescanDays` (Standard 7).
- Was der Import selbst ins Archiv legt, wird ohne Rekursivlauf nachgetragen.
- `lastscan.json` haftet an einem `SourceRoot`: anderer Archivordner =>
  sofort Vollabgleich.

## Resilio-Freigabe (Ein-Ordner-Prinzip)

Nur noch **ein einziger gemeinsamer Ordner** in Resilio Sync:

| Freigabe | auf dem Pixel | auf dem Server (Umbrel) | im Container |
| --- | --- | --- | --- |
| **PixelSync** (bidirektional) | `/storage/emulated/0/DCIM/PixelSync` | `${APP_DATA_DIR}/data/pixelsync` | `/data/pixelsync` |

Darin liegen automatisch zwei Unterordner:
- `staging/WindowsBatches/` (wird vom Uploader befüllt; im Container als `/data/staging` eingebunden)
- `control/` (Rückbelege `receipt-*.json` der Companion-App; im Container als `/data/control` eingebunden)

Die Companion-App auf dem Pixel überwacht `/storage/emulated/0/DCIM/PixelSync`, scannt die Batches unter `staging`, ignoriert `control/` und `.sync/`, und schreibt nach Bestätigung durch Google Fotos den Rückbeleg in `/storage/emulated/0/DCIM/PixelSync/control`.

Das Archiv (`/data/archive`) liegt **ausserhalb** der Freigaben: hierher wird
nur sortiert, daraus wird nur kopiert. Geloescht werden ausschliesslich
abgeschlossene Batch-Ordner unter `staging/WindowsBatches/`.

## Installation auf umbrelOS

1. Ordner `pixel-photo-uploader/` in den Community-App-Store legen (oder
   `~/umbrel/system/app-store/` bzw. per `umbrel-app-store`-Config).
2. Das Image kommt aus dem Repository-Build (`.github/workflows/publish.yml`,
   Tag `v3.3.14` -> `ghcr.io/ysamjo/pixel-photo-uploader:3.3.14`). In
   `docker-compose.yml` steht der Digest des manifest lists, weil der offizielle
   Store kein `build:` zulaesst. Selbst nach einem Digest schauen:

   ```sh
   docker buildx imagetools inspect ghcr.io/ysamjo/pixel-photo-uploader:3.3.14
   # image: ghcr.io/ysamjo/pixel-photo-uploader:3.3.14@sha256:<digest>
   ```

   Zum Bauen ohne ghcr-Zugang: `docker buildx build --platform linux/amd64,linux/arm64
   -t <registry>/pixel-photo-uploader:3.3.14 --push .`

   Ohne Registry reicht auf dem Umbrel einmalig:
   `docker build -t pixel-photo-uploader:3.3.14 .`
3. App starten, im Web-UI **Einrichtung** oeffnen und die Pfade setzen
   (`/data/archive`, `/data/staging`, `/data/control`; Dropbox/Inbox leer
   lassen, wenn nichts importiert werden soll), dann **Speichern**.
4. "Sync jetzt" oder "Vollabgleich jetzt" druecken — der watcher uebernimmt,
   die Seite zeigt "eingereiht" und danach die neuen Zahlen.

Fuer eine echte Einreichung im offiziellen Store fehlen noch Icon und
Gallery-Bilder (die kommen ins `umbrel-apps`-Repository, nicht in dieses Paket),
und `submission` muss auf die PR dort zeigen.

## Ohne Docker (Entwicklung)

```sh
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
PPU_STATE_DIR=~/.ppu-test python -m app.cli setup
PPU_STATE_DIR=~/.ppu-test python -m app.cli sync
PPU_STATE_DIR=~/.ppu-test python -m app.cli sync --deep
PPU_STATE_DIR=~/.ppu-test python -m app.cli status
PPU_STATE_DIR=~/.ppu-test python -m app.cli watch --poll-seconds 60
PPU_STATE_DIR=~/.ppu-test uvicorn app.server:app --port 8000
```

## Pruefung

```sh
python -m pytest tests/ -q          # 51 Tests, ohne Docker, ohne Netz
```

Offizieller Umbrel-Linter (aus dem `umbrel-apps`-Repository, dieses Paket als
Root zeigen lassen):

```sh
node .tools/lint-apps.mjs pixel-photo-uploader --root <pfad-zu>/umbrel
```

Er meldet fuer dieses Paket 0 Fehler. Die Compose-Datei bleibt bewusst ohne
YAML-Anker: der Parser des Linters loest `<<: *anchor` nicht auf, ein geankertes
Compose wuerde bei `image` und `volumes` stillschweigend durchgewinkt.

## Was Windows-only bleibt (bewusst nicht portiert)

- ADB (WLAN und USB), `tools\platform-tools\adb.exe`, `Start-*.cmd`,
  WinForms-GUI, COM `Shell.Application`, `System.Drawing`.
- `tasks.json`-Prozessverfolgung und FileSystemWatcher mit 64-KiB-Puffer:
  im Container durch Polling ersetzt.
- `ReserveGiB` (Freiraum-Puffer vor dem Batch) bleibt ADB-only; die
  Uebergabe per App kennt keinen vollen Telefonspeicher, weil die
  Rueckbelege erst nach der Google-Fotos-Freigabe abarbeiten.
