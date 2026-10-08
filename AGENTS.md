# pixel-photo-uploader

## Projekt-Kontext

Automatisiert den Foto-Upload auf Google Fotos über ein älteres Google Pixel (mit
unbegrenztem Original-Qualitäts-Speicherplatz):
- Sortiert Eingangsordner (Dropbox, OneDrive) ins Archiv (`YYYY.MM`).
- Packt Abhol-Batches (standardmäßig 5 GiB) in die Resilio-Sync-Freigabe `staging/Batches/`.
- Die Android Companion-App (`PixelPhotoCompanion`) auf dem Pixel übernimmt den Batch, wartet auf die Bestätigung von Google Fotos ("Sicherung abgeschlossen") und schreibt einen Rückbeleg `receipt-*.json` in den `control/`-Ordner.
- Der Uploader rechnet den Rückbeleg ab, markiert die Dateien in `completed.csv` als gesichert und löscht den Batch auf dem Pixel.
- Sagt Google Fotos zweimal in Folge „Nichts freizugeben", ist das **kein Erfolgsbeleg**: `settle_refused()` führt die Datei als unbestätigt in `blocked.csv` und gibt die Handreichung frei. Die Archiv-Kopie bleibt. `migrate_refusal_blocks()` verschiebt alte, unbelegte Absagen aus `completed.csv` in dieses Register.
- Eine offene Handreichung hält die Queue nicht mehr auf: `select_and_stage_batch()` reiht neue Dateien ein, solange die wartenden nicht mehr als die Batch-Kapazität belegen.
- Bleibt eine Datei ohne Rückbeleg, endet die Handreichung nach `BackupTimeoutHours` (Standard 72 h): Eintrag nach `blocked.csv`, Handreichung freigeben, Archiv-Kopie bleibt. `select_and_stage_batch()` überspricht blockierte Fingerabdrücke, sonst blockiert eine abgelehnte Datei die ganze Queue.
- Läuft eine Handreichungskopie aus dem Batch-Ordner weg, wartet `repair_batches()`
  die `REPAIR_GRACE_SECONDS` (600 s) auf den Rückbeleg, bevor es aus dem Archiv
  nachlegt: Resilio trägt die Freigabe-Löschung des Telefons schneller zurück, als der
  Beleg des Pixels läuft, und ein sofortiges Nachlegen würde eine gelungene
  Speicherfreigabe mit eigenen Händen rückgängig machen. Deshalb rechnet `sync_once()`
  erst ab (`confirm_staged`/`settle_refused`) und füllt danach auf.
- Läuft 24/7 als ZimaOS-Container mit integriertem Web-UI und Hintergrund-Watcher.

## Konventionen

- Python-Quelltext auf Deutsch / Englisch: Docstrings und Kommentare mit ASCII-Umlauten (`ueber`, `fuer`), nutzersichtbare Texte im Web-UI und README mit echten Umlauten.
- Keine Netzwerkzugriffe in Tests.
- Konfiguration und Status liegen immer unter `state_root()` (`PPU_STATE_DIR`, standardmäßig `/data/state`).
- `docker-compose.yml` ist die maßgebliche ZimaOS-App-Definition.
- `docker-compose.local.yml` dient für lokale Entwicklung und Tests.
- **`BEFUNDE-DE.md` ist das Sync-Nachschlagewerk**: Passreihenfolge, Resilio-Latenz
  (gemessen, nicht gefühlt), Register-Belegung, Durchsatz. Vor jeder neuen Aussage
  über Latenz, Blockierte oder Durchsatz dort nachlesen — und die Zahl neu messen,
  wenn sie älter ist als ein Deploy.

## Commands

```bash
.venv/bin/pytest                     # kein Netzwerk nötig
docker build -t pixel-photo-uploader:3.3.18 .
docker compose -f docker-compose.local.yml up -d --build
```

## Fallstricke

- `tests/test_container.py` prüft `docker-compose.yml` gegen die ZimaOS-Regeln.
  Beim Ändern der Datei beachten: kein `build:`, kein `$` in irgendeinem Wert,
  `port_map` als Zeichenkette statt Zahl, `title`/`tagline`/`description` als
  sprachgeschlüsselte Objekte mit `en_US`, Daten unter `/DATA/`.
- Alter Foto-Bestand läuft **nur als Mount unter dem Archiv** mit
  (`…/Pictures:/data/archive/Altbestand:ro`): der Walk ist rekursiv, eine zweite
  Config-Wurzel gibt es nicht. `:ro` ist die Sicherung gegen ein `rm -rf`, das durch
  den Mountpunkt hindurch in den Bestand greift — die App schreibt selbst nie dorthin,
  `move_media_file()` kennt nur `inbox`, `inbox/{Screenshots,Memes}` und
  `Archiv/JJJJ.MM` als Ziel. Nach dem Aktivieren ist **ein Vollabgleich Pflicht** —
  sonst überspringt der Grundabgleich den Ordner wegen zu alter Schreibzeit.
  Niemals `DropboxRoot`/`OneDriveRoot`/`InboxRoot` auf einen Bestand richten: diese
  drei Quellen werden beim Import **geleert**.
- Ein Bestand darf nicht aktiviert werden, während der Pixel offline ist: derselbe
  Durchlauf staged sofort den ersten Batch, und `expire_staged()` setzt nach
  `BackupTimeoutHours` mehrere hundert Bestandsdateien auf `blocked.csv`.
- **Reihenfolge Ledger → Löschung:** `_release_staged()` schreibt das Ledger, *bevor* es die
  Handreichungsdatei unlink't. Sähe Resilio die Löschung zuerst, verbuchte die App das
  Verschwinden über `healReceiptFromDisk()` als von Google Fotos freigegeben und der Server
  bekam einen zweiten, falschen Erfolgsbeleg. Die App ihrerseits merkt sich abgelehnte
  Content-Marken (`AppState.refusedTokens`, Schlüssel ist der Zwölfer-Fingerabdruck aus
  `NNNNNN-<fp12>.ext`) und bietet sie weder erneut an noch bucht ihre Löschung.
