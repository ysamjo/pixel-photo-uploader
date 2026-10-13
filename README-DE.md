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
5. **Datei für Datei abgerechnet:** Eine offene Handreichung hält die Queue nicht auf – der nächste Batch läuft mit, das Telefon hält dabei nie mehr als eine Batchgröße.
6. **Keine Datei wartet ewig:** Was nach `BackupTimeoutHours` (Standard 72 h) keinen Rückbeleg hat, wandert in `blocked.csv` und gibt den Batch-Ordner frei. Das Archiv behält seine Kopie, nur die Handreichung aufs Pixel endet; blockierte Fingerabdrücke laufen nie wieder ein.
7. **Eine Absage ist kein Erfolgsbeleg:** Sagt Google Fotos zweimal „Nichts freizugeben", bleibt der Upload unbestätigt. Die Datei kommt nach `unverified.csv`, ihre Handreichung wird sofort vom Pixel entfernt und die Archiv-Kopie bleibt erhalten. Frühestens nach 24 h läuft sie in einem kleinen Verifikations-Retry (max. 0,5 GiB pro Auffüllung) erneut ein.
8. **Erst der Beleg, dann die Nachlage:** Fehlt eine Handreichungskopie im Batch-Ordner, wartet der Server zehn Minuten auf den Rückbeleg, bevor er aus dem Archiv nachlegt. Resilio trägt die Löschung einer gelungenen Speicherfreigabe schneller zurück, als der Beleg des Pixels läuft – ein sofortiges Nachlegen würde die Freigabe des Telefons selbst rückgängig machen.

Ausführlich zu Reihenfolge, Latenz, Zählern und offenen Punkten:
**[BEFUNDE-DE.md](BEFUNDE-DE.md)** — Sync-Verhalten, gemessen am Stand 2026-10-07.

## Was die Statusseite zählt

- **im Katalog** – jede Datei im Archiv, die der Abgleich gesehen hat.
- **offen** – Dateien, die noch auf ihren Upload warten, mit Gesamtgröße.
- **auf dem Pixel** – offene Handreichungen im Batch-Ordner.
- **abgeschlossen / hochgeladen / in den letzten 24 h** – Belege aus `completed.csv`, dazu die Byte-Summen: „hochgeladen" ist alles seit der ersten Buchung, „in den letzten 24 h" das Fenster davor. Grundlage ist `CompletedUtc`; die Fingerabdrücke aus dem Duplikat-Kurzschluss (`Identical content already completed`) sind mitgezählt.
- **unbestätigt** – Google Fotos sagte zweimal „Nichts freizugeben": kein Erfolgsbeleg, Archiv-Kopie bleibt, Retry frühestens nach 24 h.
- **blockiert** – endgültig aus der Queue, aus einem von zwei Gründen: entweder kam nach `BackupTimeoutHours` (Standard 72 h) kein Rückbeleg, oder es ist eine 0-Byte-Datei, die Google Fotos nicht sichern kann. Die Archiv-Kopie bleibt, nur die Handreichung aufs Pixel endet; ein blockierter Fingerabdruck läuft nie wieder ein.

Alle Zahlen stehen in deutscher Schreibweise (Punkt als Tausender-, Komma als Dezimaltrenner).

## Unbeaufsichtigter Betrieb auf dem Pixel

Der optionale [Google-Fotos-Wächter](PHOTOS-WATCHDOG-DE.md) misst echten Sendeverkehr und den Restzähler, startet nach 30 Minuten Stillstand nur Google Fotos einmal pro Batch neu und meldet anhaltende Ausfälle nach einer Stunde Wartezeit. Kein Geräteneustart. Companion 1.2.8 zeigt die Warnungen auf dem Pixel. Der Wächter läuft auf ZimaOS als Docker-Dienst; Liveprüfung und Installation der Companion-Erweiterung benötigen ADB zum Pixel 1.

Companion 1.2.7 erholt sich automatisch von vorübergehenden Fehlern (Wiederholung nach 5/15/30 Minuten), ohne den laufenden Batch neu zu scannen oder dessen 72-Stunden-Frist zu verlängern. Deaktivierte Sicherung, voller Kontospeicher, fehlendes Google Fotos und das 72-Stunden-Limit erfordern einen Eingriff. Das Pixel bleibt entsperrt am Ladegerät; Companion, Google Fotos und Resilio sollten von der Akkuoptimierung ausgenommen sein. Details und Android-Prüfbefehle stehen in [android/PixelPhotoCompanion/README-DE.md](android/PixelPhotoCompanion/README-DE.md).

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
tests/                     pytest-Suite (kein Netzwerk nötig)
```

## Installation auf ZimaOS

### 1. Image auf ZimaOS bereitstellen

Entweder direkt auf dem ZimaOS-NAS bauen:
```bash
cd /DATA/AppData/pixel-photo-uploader
docker build -t pixel-photo-uploader:3.3.21 .
```

Oder vom Entwicklungsrechner übertragen:
```bash
# Auf dem Mac/PC:
docker save pixel-photo-uploader:3.3.21 | gzip > pixel-photo-uploader-3.3.21.tar.gz
scp pixel-photo-uploader-3.3.21.tar.gz user@<ZIMAOS-IP>:/DATA/AppData/pixel-photo-uploader/

# Auf ZimaOS via SSH:
docker load < /DATA/AppData/pixel-photo-uploader/pixel-photo-uploader-3.3.21.tar.gz
```

### 2. Im ZimaOS App-Manager installieren

1. In ZimaOS auf **App Store** -> **Install a customized app** klicken.
2. Den Inhalt der [docker-compose.yml](docker-compose.yml) einfügen.
3. Die Hostpfade bei Bedarf anpassen (Standard: `/DATA/Media/Photos/Archiv`, `/DATA/AppData/pixel-photo-uploader/...`).
4. Installieren & starten.

### 3. Resilio Sync einrichten

In Resilio Sync genau **einen** Ordner teilen:
- **Server-Pfad:** `/DATA/AppData/resilio-sync/data/pixelsync` (Resilio kann nur
  Ordner unterhalb seiner Freigabe-Wurzel `/sync` teilen)
- **Pixel-Pfad:** `/storage/emulated/0/DCIM/PixelSync`

### 4. Pixel Companion App installieren

Die fertige APK liegt unter:
[`android/PixelPhotoCompanion/app/build/outputs/apk/debug/app-debug.apk`](android/PixelPhotoCompanion/app/build/outputs/apk/debug/app-debug.apk)

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

Die pytest-Suite läuft ohne Docker und ohne Netzwerkzugriffe.
