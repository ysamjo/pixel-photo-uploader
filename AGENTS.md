# pixel-photo-uploader

## Projekt-Kontext

Automatisiert den Foto-Upload auf Google Fotos über ein älteres Google Pixel (mit
unbegrenztem Original-Qualitäts-Speicherplatz):
- Sortiert Eingangsordner (Dropbox, OneDrive) ins Archiv (`YYYY.MM`).
- Packt Abhol-Batches (standardmäßig 5 GiB) in die Resilio-Sync-Freigabe `staging/Batches/`.
- Die Android Companion-App (`PixelPhotoCompanion`) auf dem Pixel übernimmt den Batch, wartet auf die Bestätigung von Google Fotos ("Sicherung abgeschlossen") und schreibt einen Rückbeleg `receipt-*.json` in den `control/`-Ordner.
- Der Uploader rechnet den Rückbeleg ab, markiert die Dateien in `completed.csv` als gesichert und löscht den Batch auf dem Pixel.
- Bleibt eine Datei ohne Rückbeleg, endet die Handreichung nach `BackupTimeoutHours` (Standard 72 h): Eintrag nach `blocked.csv`, Handreichung freigeben, Archiv-Kopie bleibt. `select_and_stage_batch()` überspricht blockierte Fingerabdrücke, sonst blockiert eine abgelehnte Datei die ganze Queue.
- Läuft 24/7 als ZimaOS-Container mit integriertem Web-UI und Hintergrund-Watcher.

## Konventionen

- Python-Quelltext auf Deutsch / Englisch: Docstrings und Kommentare mit ASCII-Umlauten (`ueber`, `fuer`), nutzersichtbare Texte im Web-UI und README mit echten Umlauten.
- Keine Netzwerkzugriffe in Tests.
- Konfiguration und Status liegen immer unter `state_root()` (`PPU_STATE_DIR`, standardmäßig `/data/state`).
- `docker-compose.yml` ist die maßgebliche ZimaOS-App-Definition.
- `docker-compose.local.yml` dient für lokale Entwicklung und Tests.

## Commands

```bash
.venv/bin/pytest                     # 72 Tests, kein Netzwerk nötig
docker build -t pixel-photo-uploader:3.3.14 .
docker compose -f docker-compose.local.yml up -d --build
```

## Fallstricke

- `tests/test_container.py` prüft `docker-compose.yml` gegen die ZimaOS-Regeln.
  Beim Ändern der Datei beachten: kein `build:`, kein `$` in irgendeinem Wert,
  `port_map` als Zeichenkette statt Zahl, `title`/`tagline`/`description` als
  sprachgeschlüsselte Objekte mit `en_US`, Daten unter `/DATA/`.
