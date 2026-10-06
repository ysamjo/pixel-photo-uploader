# Pixel Photo Uploader — ZimaOS-Paket (3.3.13)

Gleiche Logik wie der Umbrel-Port (`../umbrel/pixel-photo-uploader`, App + Resilio,
kein ADB, kein USB-Kabel), verpackt für ZimaOS: `docker-compose.yml` mit
`x-casaos`-Block, stabile `/DATA`-Pfade und ein Import, der Cloud-Mounts auf
fremden Dateisystemen übersteht. (Die alte Windows-Variante ist eingefroren
unter `../Archiv/Windows-PS1-eingefroren-3.3.12/`.) Das Docker-Image ist dasselbe
(`ghcr.io/ysamjo/pixel-photo-uploader:3.3.13`, amd64 + arm64); nur die
Verpackung und die Standardpfade unterscheiden sich.

## Was wo läuft — der beste Workflow

```
 OneDrive „Eigene Aufnahmen" ──┐
                                ├─> [_eingang-inbox] ──> sortieren ──> [Archiv YYYY.MM]
 Dropbox „Camera Uploads" ──────┘         │                                  │
                                          │ Duplikate (SHA-256)              │ nur KOPIEREN
                                          v                                  v
                                   Screenshots/Memes               [PixelSync/staging/Batches/<id>]
                                   bleiben im Eingang                        │ Resilio Sync
                                                                             v
                                                        Pixel + „Pixel Photo Companion"
                                                        meldet, wartet „Sicherung
                                                        abgeschlossen", gibt Speicher frei
                                                                             │ receipt-*.json
                                                                             v
                                                        [PixelSync/control] ──> Uploader löscht
                                                        bestätigte Batches, Google Fotos
                                                        ist das Langzeit-Ziel
```

Regeln, kurz:

1. **Clouds sind nur Eingänge.** Dropbox `Camera Uploads` und OneDrive
   `Eigene Aufnahmen` werden per **Verschieben** geleert — bewusst, damit die
   Handy-Upload-Ordner nicht ewig wachsen. Das lokale Archiv wächst, die Clouds
   schrumpfen.
2. **Das Archiv ist die Bibliothek.** Daraus wird für das Pixel ausschließlich
   **kopiert**. Gelöscht werden nur bestätigte Batch-Ordner unter
   `staging/Batches/`.
3. **Duplikate entscheidet SHA-256**, nicht der Dateiname. Gleicher Inhalt wird
   entfernt, gleicher Name mit anderem Inhalt bekommt ` (1)`, ` (2)` …
4. **Screenshots und Memes** bleiben im Eingang (`Screenshots/`, `Memes/`) und
   gehen nie ans Pixel.
5. **Ein Batch, ein Rückbeleg.** Der nächste Batch beginnt erst, wenn das Pixel
   den aktuellen per `receipt-*.json` bestätigt hat.
6. **Nichts wartet endlos.** Bleibt eine Datei länger als `BackupTimeoutHours`
   (Standard 72 h) ohne Rückbeleg, wandert sie nach `state/blocked.csv` und die
   Handreichung wird freigegeben — das Archiv behält seine Kopie. Blockierte
   Fingerabdrücke werden nie wieder vorgemerkt; zum erneuten Versuch die Zeile
   in `blocked.csv` löschen.

## Pfade: Host (ZimaOS) → Container → Zweck

| Host (anpassbar) | Container (fest) | Zweck |
| --- | --- | --- |
| `/DATA/Media/Photos/Archiv` | `/data/archive` | Archiv `JJJJ.MM`, nur Kopierquelle |
| `/DATA/AppData/resilio-sync/data/pixelsync` | `/data/pixelsync` | **einzige** Resilio-Freigabe (bidirektional), liegt in Resilios Sync-Wurzel `/sync` |
| … Unterordner `staging` | `/data/staging` | `Batches/<id>` + `_batch-manifest.json` |
| … Unterordner `control` | `/data/control` | `receipt-*.json` vom Pixel |
| `/DATA/AppData/pixel-photo-uploader/state` | `/data/state` | `config.json`, `catalog.csv`, `blocked.csv`, Log |
| `/DATA/Media/Photos/_eingang-dropbox` | `/data/dropbox` | Spiegel von Dropbox `Camera Uploads` |
| `/DATA/Media/Photos/_eingang-inbox` | `/data/inbox` | Spiegel von OneDrive `Eigene Aufnahmen` |
| *(optional, auskommentiert)* | `/data/archive/Altbestand` | alter Foto-Bestand, **nur lesend** mitlaufend |

### Beide Clouds anbinden (Variante A, empfohlen)

1. In ZimaOS unter **Dateien** OneDrive und Dropbox verknüpfen.
2. Je einen lokalen Spiegel-Ordner anlegen (`_eingang-dropbox`,
   `_eingang-inbox`) und per Kopierauftrag bzw. Sync-Auftrag **Cloud → NAS**
   befüllen lassen. Richtung Einweg/Kopie genügt: Der Import leert den Spiegel,
   die Cloud bleibt Quelle.
3. Im Web-Setup des Uploaders `/data/dropbox` und `/data/inbox` eintragen
   (stehen schon als Vorschlag drin).

### Variante B: Cloud-Mounts direkt einhängen

Nur wenn `findmnt | grep -iE 'onedrive|dropbox'` auf ZimaOS einen aktiven Mount
zeigt (ein Verzeichnis unter `/media` allein beweist nichts — das kann eine
abgehängte Leiche sein). Dann im Compose die beiden Beispielzeilen unten gegen
die echten Hostpfade tauschen. Bedingungen:

- Schreibrechte: Der Import **verschiebt**, braucht also auch in der Cloud
  Löschrechte. Wer die Cloud nicht verändern will, lässt beide Felder leer und
  nutzt Variante A.
- Stabilität hochsetzen: FUSE-Mounts melden mtime grob; `Stabilität`
  auf **300 s** statt 120 s stellen, sonst wandern halb synchronisierte Dateien
  in Batches.
- Re-Auth im Blick: Verschwindet ein Mount, meldet das Protokoll unerreichbare
  Ordner und der Zyklus wird beim nächsten Lauf nachgeholt — Daten gehen nicht
  verloren, es stapelt sich nur.

### Alter Foto-Bestand: mitlaufen lassen, ohne zu kopieren

Der Walk durch `/data/archive` ist rekursiv. Wer einen vorhandenen Foto-Bestand
mitgeben will, **hängt ihn als Bind-Mount unter das Archiv** — die beiden
auskommentierten Zeilen in `docker-compose.yml` sind genau dafür:

```yaml
- /media/Data_1/Pictures:/data/archive/Altbestand:ro
```

Danach in der Web-UI **einmal „Vollabgleich"** einreihen. Ohne ihn bleibt der
Bestand unsichtbar: der Grundabgleich überspringt Ordner, deren Schreibzeit älter
als der letzte Lauf ist (Puffer 24 h), und ein eingeschworener Bestand ist per
Definition alt.

Vier Regeln, die diese Zeile trägt:

- **`ro` ist die Sicherung, nicht Deko.** Der Mount hängt *im* Archivordner. Ohne
  Read-only würde ein `rm -rf Archiv/Altbestand` durch ihn hindurch den Bestand
  löschen. Die App selbst schreibt dort nie hin — Umzüge landen immer in
  `Archiv/JJJJ.MM`, nie im Bestand.
- **Niemals ein Eingangs-Feld auf den Bestand richten.** `DropboxRoot`,
  `OneDriveRoot` und `InboxRoot` sind Quellen, **aus denen verschoben wird** —
  der Import löscht die Quelldatei nach dem Umzug. Ein Bestand ist keine Quelle.
- **Beide Dienste brauchen denselben Mount**, sonst rechnet der Server Batches ab,
  die der Watcher nie katalogisiert hat.
- **Neue Aufnahmen bleiben vorn.** Die Batch-Auswahl sortiert nach letzter
  Schreibzeit; ein Bestand von 2001–2024 rutscht ans Ende und quetscht sich nie an
  frischen Dateien vorbei.

Was es kostet, ist allein die Menge: bei 5 GiB je Batch sind 1,6 TB rund 330
Durchläufe, und der Pixel muss die meiste Zeit am Strom und im WLAN hängen. Eine
Bestandsdatei wird nie verschoben oder gelöscht — nur gelesen und als Kopie in die
Resilio-Freigabe gelegt.

## Installation auf ZimaOS (Custom Install)

1. Ordner aus Variante A anlegen (Dateien-App), z. B.
   `/DATA/Media/Photos/{Archiv,_eingang-dropbox,_eingang-inbox}`.
2. ZimaOS → Apps → **Custom Install**: Inhalt von
   `Apps/PixelPhotoUploader/docker-compose.yml` einfügen. Hostpfade bei Bedarf
   anpassen (Picker zeigt nur existierende Ordner — erst anlegen, dann wählen).
3. Port bleibt `${WEBUI_PORT:-8000}` — ZimaOS vergibt ihn automatisch.
4. App starten, Web-UI öffnen → **Einrichtung**: Archiv, Übergabe, Rückbelege
   stehen schon; Dropbox/Inbox stehen schon (leer lassen = kein Import).
   Startwerte: Batch **4–5 GiB**, Stabilität **120 s** lokal / **300 s** bei
   Cloud-Mounts, Grundabgleich **360 min**, Vollabgleich **7 Tage**.
5. **Resilio Sync** aus dem ZimaOS-Store installieren und genau **einen**
   Ordner teilen: `/DATA/AppData/resilio-sync/data/pixelsync` (im Container
   `/sync/pixelsync`, also bereits in Resilios Sync-Wurzel)
   ↔ Pixel `/storage/emulated/0/DCIM/PixelSync`.
6. Auf dem Pixel die **Pixel Photo Companion**-App (`../Android-App`,
   gleicher Ordner wie bisher): Datei- + Bedienungshilfen-Zugriff erlauben,
   Pfad prüfen, `Start Monitoring`.
7. Google Fotos: richtiges Konto, Sicherung ein, **Originalqualität**, Ordner
   `PixelSync` in den Gerätesicherungsordnern aktiviert.
8. Im Web-UI **Sync jetzt** (erster großer Bestand) bzw. **Vollabgleich jetzt**,
   danach läuft der Watcher von allein (alle 60 s, plus Grundabgleich).

## Begleit-Apps im Überblick

| System | App | Wozu |
| --- | --- | --- |
| ZimaOS | **Pixel Photo Uploader** (dieses Paket) | sortieren, katalogisieren, Batches, Rückbelege |
| ZimaOS | **Resilio Sync** (Store) | transportiert `PixelSync` zwischen NAS und Pixel |
| Pixel | **Pixel Photo Companion 1.2.2** (`../Android-App`) | prüft Google Fotos, gibt Speicher frei, schreibt Rückbelege |
| Cloud | OneDrive- + Dropbox-Verknüpfung (ZimaOS Dateien) | Eingänge `Camera Uploads` / `Eigene Aufnahmen` |

## Was 3.3.13 und 3.3.14 gegenüber 3.3.12 ändern (nur Linux-Container)

- **Import über Dateisystemgrenzen:** `Path.rename` wirft zwischen Cloud-Mount
  und lokalem Archiv `EXDEV`. Der Import kopiert dann mit Größenprüfung und
  löscht erst danach die Quelle (`app/pipeline.py:_relocate`). Auf Umbrel ist
  das unschädlich, auf ZimaOS mit Variante B load-bearing.
- **Sync-Reste bleiben draußen:** `.sync/`, `@eaDir`, `.stfolder`,
  `.dropbox.cache`, `*.tmp`, `*.part`, `*.crdownload`, `*.!sync`,
  `*.sync-conflict-*`, `Thumbs.db`, `.DS_Store` werden im Dropbox-Durchlauf
  und in der Inbox-Sortierung übersprungen (`is_ignorable`, Tests).
- **Lineare Duplikatprüfung (3.3.14):** Ein Größen-Index pro Zielordner und
  Importlauf ersetzt das N-malige Ordner-Listen bei N Dateien (`_DestinationIndex`).
- **Lineare Rückbeleg-Abrechnung (3.3.14):** Ein Suffix-Set ersetzt staged ×
  receipts `endswith`-Vergleiche (`confirm_staged`, per `rfind` semantisch identisch).
- **Checkpoint-Saves (3.3.14):** `staged.json` wird beim Bereitstellen nur noch
  alle 25 Dateien plus am Ende geschrieben statt zweimal pro Datei (ein
  900-Dateien-Batch schrieb ~1.800-mal). Verlorene Schweife werden einfach neu
  vorgemerkt, nie verloren.
- **CLI-Text korrigiert:** Das Setup nennt wieder die eine Resilio-Freigabe
  (`DCIM/PixelSync` mit `staging/` + `control/`) statt zweier veralteter Pfade.
- **Absage-Rückbeleg (3.3.15):** Sagt Google Fotos sechs Mal „Nichts freizugeben"
  zu denselben Dateien, schickt das Pixel einen Rückbeleg mit `refusedPaths` statt
  zu schweigen. Der Uploader legt diese Dateien sofort in `blocked.csv` und gibt
  die Handreichung frei (`release_refused`); vorher hielt ein abgelehnter Rest die
  ganze Queue bis `BackupTimeoutHours` auf. Archiv-Kopien bleiben erhalten.
- Windows-PS1 ist eingefroren bei 3.3.12 (siehe `../Archiv/Windows-PS1-eingefroren-3.3.12/`).

Release-Ablauf: Tag `v3.3.13` pushen → `.github/workflows/publish.yml` baut
`:3.3.13` (amd64+arm64). Danach im Umbrel-`docker-compose.yml` den Digest per
`docker buildx imagetools inspect ghcr.io/ysamjo/pixel-photo-uploader:3.3.13`
neu pinnen (Platzhalter steht in der Datei). ZimaOS braucht keinen Digest.

## Diagnose

- Web-UI → letzte Meldungen; **Sync jetzt** vs. **Vollabgleich jetzt**.
- `findmnt | grep -iE 'onedrive|dropbox'` — kein Treffer = Mount weg, in
  ZimaOS-Dateien neu verknüpfen (Cloud-Daten sind davon unberührt).
- Keine Rückbelege: Resilio beidseitig aktiv? Companion zeigt „Überwachung
  gestartet"? Pixel entsperrt, am Ladegerät, Google-Fotos-Sicherung ohne Fehler?
- `Preflight` per `python -m app.cli preflight` (im Container via Terminal).
