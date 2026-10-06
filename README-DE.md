# Pixel Photo Uploader — ZimaOS & Container (App + Resilio)

Automatisiert den Foto-Upload auf Google Fotos über ein altes Google Pixel mit
unbegrenztem Speicherplatz: Sortiert Aufnahmen aus Cloud-Eingängen (Dropbox /
OneDrive) ins lokale Archiv (nach `YYYY.MM`), packt Abhol-Batches in eine
Resilio-Sync-Freigabe für das Pixel und rechnet die Rückbelege der Android
Companion-App ab, sobald Google Fotos die Sicherung bestätigt hat.

Kein ADB, kein USB-Kabel nötig — läuft 24/7 als Container auf ZimaOS.

## Was wo läuft

```
 OneDrive / Dropbox ──> [_eingang] ──> sortieren ──> [Archiv YYYY.MM]
                                                            │ nur KOPIEREN
                                                            v
                                            [PixelSync/staging/Batches/<id>]
                                                            │ Resilio Sync
                                                            v
                                            Pixel + „Pixel Photo Companion"
                                            wartet „Sicherung abgeschlossen"
                                                            │ receipt-*.json
                                                            v
                                            [PixelSync/control] ──> Uploader löscht
                                            bestätigte Batches vom Pixel
```

1. **Clouds sind nur Eingänge:** Werden per Verschieben geleert, damit Speicher nicht voll läuft.
2. **Das Archiv ist die Bibliothek:** Daraus wird ausschließlich kopiert.
3. **Duplikate entscheidet SHA-256:** Nicht der Dateiname.
4. **Screenshots & Memes:** Bleiben im Eingang und gehen nie ans Pixel.
5. **Ein Batch, ein Rückbeleg:** Der nächste Batch startet erst, wenn das Pixel den aktuellen bestätigt hat.
6. **Keine Datei wartet ewig:** Was nach `BackupTimeoutHours` (Standard 72 h) keinen Rückbeleg hat, wandert in `blocked.csv` und gibt den Batch-Ordner frei. Das Archiv behält seine Kopie, nur die Handreichung aufs Pixel endet; blockierte Fingerabdrücke laufen nie wieder ein.

## Paketinhalt

```
docker-compose.yml         ZimaOS-App-Definition (für "Custom Install")
docker-compose.local.yml   Lokale Entwicklung & Tests (Mac / Linux / Windows)
Dockerfile                 python:3.12-slim, unprivilegierter Nutzer
app/                       Python-Kern
  config.py                Konfiguration, Wurzel- und Schachtelprüfung
  fingerprints.py          Zeitstempel + SHA-256 Fingerabdruck
  store.py                 catalog / completed / staged / blocked / lastscan
  pipeline.py              Import -> Archiv/YYYY.MM
  batches.py               Übergabe in Batches/ + Rückbelege
  sync.py                  Sync-Durchlauf & Zähler
  runner.py                Job-Sperre & Sync-Anforderung
  watch.py                 Hintergrund-Watcher (Polling)
  server.py                Web-UI (Status, Setup, Manuelle Aktionen)
  cli.py                   Kommandozeile (setup, sync, status, watch)
android/                   Android Companion-App (PixelPhotoCompanion)
  app/build/outputs/apk/   Fertige app-debug.apk für das Pixel
data/                      Ordnerstruktur für Bind-Mounts
tests/                     71 Tests (pytest, kein Netzwerk nötig)
```

## Installation auf ZimaOS

### 1. Image auf ZimaOS bereitstellen

Entweder direkt auf dem ZimaOS-NAS bauen:
```bash
cd /DATA/AppData/pixel-photo-uploader
docker build -t pixel-photo-uploader:3.3.15 .
```

Oder vom Entwicklungsrechner übertragen:
```bash
# Auf dem Mac/PC:
docker save pixel-photo-uploader:3.3.15 | gzip > pixel-photo-uploader-3.3.15.tar.gz
scp pixel-photo-uploader-3.3.15.tar.gz user@<ZIMAOS-IP>:/DATA/AppData/pixel-photo-uploader/

# Auf ZimaOS via SSH:
docker load < /DATA/AppData/pixel-photo-uploader/pixel-photo-uploader-3.3.15.tar.gz
```

### 2. Im ZimaOS App-Manager installieren

1. In ZimaOS auf **App Store** -> **Install a customized app** klicken.
2. Den Inhalt der [docker-compose.yml](file:///Users/family/Developer/pixel-photo-uploader-docker/docker-compose.yml) einfügen.
3. Die Hostpfade bei Bedarf anpassen (Standard: `/DATA/Media/Photos/Archiv`, `/DATA/AppData/pixel-photo-uploader/...`).
4. Installieren & starten.

### 3. Resilio Sync einrichten

In Resilio Sync genau **einen** Ordner teilen:
- **Server-Pfad:** `/DATA/AppData/resilio-sync/data/pixelsync` (Resilio kann nur
  Ordner unterhalb seiner Freigabe-Wurzel `/sync` teilen)
- **Pixel-Pfad:** `/storage/emulated/0/DCIM/PixelSync`

### 4. Pixel Companion App installieren

Die fertige APK liegt unter:
[`android/PixelPhotoCompanion/app/build/outputs/apk/debug/app-debug.apk`](file:///Users/family/Developer/pixel-photo-uploader-docker/android/PixelPhotoCompanion/app/build/outputs/apk/debug/app-debug.apk)

Auf dem Pixel installieren, Berechtigungen für Speicher und Barrierefreiheit (für Google Fotos Status-Erkennung) erteilen.

## Lokale Entwicklung & Tests (Mac / PC)

Mit lokalem Docker:
```bash
docker compose -f docker-compose.local.yml up -d --build
```
Danach ist das Web-UI unter `http://localhost:8000` erreichbar.

Ohne Docker:
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
pytest
```

Alle 71 Tests laufen ohne Docker und ohne Netzwerkzugriffe.
