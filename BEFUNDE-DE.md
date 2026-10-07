# Sync-Verhalten — Befunde, Regeln, offene Punkte

Stand: 2026-10-07, 16:20 UTC. Server `pixel-photo-uploader:3.3.17` auf beiden
Containern der ZimaOS (`192.168.178.162`), Companion **1.2.4** (versionCode 9) auf dem
Upload-Pixel `FA69M0305152`. Die Zähler in §2, §6 und §8 sind an diesem Stand
gemessen; die Monate-Aussage in §8 ist eine Hochrechnung **an der dort gemessenen**
Upload-Rate und als solche gekennzeichnet — sie ist seit der 15-Minuten-Stichprobe von
17:56–18:11 CEST **keine** belastbare Zahl mehr, siehe §9 Punkt 7. Neu seit der Fassung
von 15:42 UTC: der „backup paused"-Stopp ist **wiederholt** aufgetreten und die Deutung
in §7 ist korrigiert; mein zweiter Fehl-Tap auf den Einwilligungs-Haken (18:13:26) steht
in §6, die Regel dazu in §7.

## 1. Ein Durchlauf, und zwar in dieser Reihenfolge

Der Watcher startet alle 60 s eine Pass (`sync_once()`, `app/sync.py:74`). Zwei Pässe
gleichzeitig gehen nicht: `acquire()` hält eine Sperre, der zweite wirft
`BlockingIOError`. Die Reihenfolge innerhalb des Passes ist der ganze Trick:

| Schritt | Was er tut | Warum an dieser Stelle |
|---|---|---|
| `preflight` | Schreibprobe in die Übergabe, Batches und Belege zählen | nach dem ersten Pass ohne Schreibprobe — eine Probe pro Minute hält Resilio unnötig busy |
| `run_import` | Dropbox/OneDrive/Eingang sortieren, Duplikate per SHA-256 | Cloud-Eingänge werden beim Import **geleert** (bewusst, so entschieden am 2026-10-05) |
| `reconcile` | Archiv-Katalog abgleichen | Grundabgleich alle `RescanMinutes` (360), Vollabgleich alle `DeepRescanDays` (30); dazwischen nur gemeldete Pfade |
| `migrate_refusal_blocks` | alte 3.3.15-Absagen aus `blocked.csv` um buchen | Aufräumen, kein Regelbetrieb |
| `confirm_staged` | Erfolgsbelege abrechnen | **vor** der Nachlage |
| `settle_refused` | Absagebelege als „bereits gesichert" buchen | **vor** der Nachlage |
| `expire_staged` | Handreichungen ohne Beleg nach 72 h freigeben | **vor** der Nachlage |
| `repair_batches` | fehlende Handreichungskopien aus dem Archiv ersetzen | zuletzt, und mit Schonfrist |
| `select_and_stage_batch` | neue Dateien einreihen | braucht die freie Restkapazität aus den drei Schritten davor |

**Der Merksatz:** abgerechnet wird, bevor aufgefüllt wird. Alles, was gerade erst
abgerechnet ist, braucht keine Kopie zurück.

## 2. Die vier Register und ihre aktuelle Belegung

| Register | Inhalt | Gerade |
|---|---|---|
| `catalog.csv` | jede Datei im Archiv (inkl. Altbestand) | 178.099 |
| `staged.json` | offene Handreichungen aufs Telefon | 609 Dateien in **zwei** Batches: `20261007-150538` (12 / 0,25 GiB) und `20261007-151943` (597 / 4,75 GiB) |
| `completed.csv` | gesicherte Fingerabdrücke mit Grund | 434 = **299 Absagen** + 134 echte Freigaben + 1 Duplikat-Buchung |
| `blocked.csv` | dauerhaft aus der Queue | 290 — **ausnahmslos 0-Byte-Dateien** |

`open_stable` 177.371 Dateien / 1.539,7 GiB. Log: `PixelPhotoUploader.log` im
State-Ordner, Zeitstempel **UTC**; das Telefon schreibt sein Protokoll nach
`control/companion-log.txt` in **CEST** (zwei Stunden Differenz, kein toter Watcher).

**Korrektur zu einer Aussage von mir:** die 290 Blockierten sind *nicht* „backup
paused"-Fälle. `blocked.csv` nach Reason gelesen: 290 ×
„Empty file - nothing for Google Photos to back up", alle mit Größe 0 (253 davon
`2010 Brasilien/Iguacu`, 30 `Location/Karlsruhe`). Die laufen nie wieder ein und
blockieren nichts — Task 6 (transiente Zustände neu einordnen) hat aktuell **keine**
Ledger-Opfer, aber seit 17:29:22 einen **wiederholten** Betriebsfall: derselbe Stopp
um 17:51:44 erneut, 98 s nach dem Zurücksetzen. Siehe §6, §7 und §9 Punkt 5.

## 3. Der Rückbeleg hat drei Urteile, nicht zwei

| Urteil | Auslöser auf dem Telefon | Buchung |
|---|---|---|
| **Freigegeben** | Google Fotos entfernt die Datei wirklich, App vergleicht den Dateibestand | `completed.csv`, Grund „Android receipt after confirmed Google Photos free-up" |
| **Abgelehnt** | zweimal in Folge „Nichts freizugeben" (Runden 15 min auseinander) | `completed.csv`, Grund „Google Photos already holds this content (nothing to free up)" — Google hält den Inhalt schon, meist von einem anderen Gerät |
| **Kein Beleg** | nach `BackupTimeoutHours` = 72 h nichts eingetroffen | `blocked.csv`, Handreichung freigeben, Archiv-Kopie bleibt |

Vierte Buchung, ohne Google-Fotos-Urteil: beim Einreihen vergleicht der Server die
SHA-256 mit dem Ledger und bucht inhaltliche Zwillinge sofort
(`batches.py:459`, Grund „Identical content already completed"). Genau so entstand der
eine Duplikat-Eintrag oben.

Das dritte Urteil ist der Grund, dass die Leitung überhaupt läuft: für Inhalte, die
Google Fotos schon besitzt, kann der Erfolgsfall „Datei verschwindet vom Telefon" nie
eintreten. Vor 3.3.16 endeten solche Dateien in `blocked.csv` und hielten die Queue.

## 4. Der Übertragungsweg ist der eigentliche Gegner

Handreichung, Löschung und Beleg laufen durch **einen** Resilio-Ordner
(`pixelsync/` in Resilios Sync-Wurzel). Die Freigabe `Data` ist der ganze
Datenpool mit 195.374 Ordnern; das inotify-Limit ist **inzwischen erhöht** (Host und
Container lesen 524288 / 512, gesetzt beim Boot um ~06:53 UTC aus
`/etc/sysctl.d/90-inotify.conf`).

**Trotzdem gemessen, 15:21 UTC:** eine Datei, auf der NAS in `control/` geschrieben,
war nach **135 s** auf dem Pixel sichtbar. Vor der Erhöhung waren für eine Löschung
~3 Minuten gemessen. Der Weg bleibt also in beide Richtungen minutenlang —
**ein Zustand, den die NAS sieht, kann zwei Minuten alt oder zwei Minuten zu früh
sein.** Die drei Regeln unten sind Antworten darauf, und die Schonfrist in §5 ist
genau für diese Lücke da.

## 5. Die drei Regeln, die daraus folgen

1. **Ledger vor Löschung.** `_release_staged()` schreibt `completed.csv`, *bevor* es
   die Handreichungsdatei unlink't. Sähe Resilio die Löschung zuerst, verbuchte die
   App das Verschwinden über `healReceiptFromDisk()` als „Google Fotos hat
   freigegeben" und der Server bekäme einen zweiten, falschen Erfolgsbeleg.
   Ist schon gemessen passiert (zwei Belegpaare refused→removed am 10-06 und 10-07) —
   aufgehalten nur dadurch, dass die Zeilen bereits gebucht waren. Der Lokalzähler der
   App („seit Installation lokal freigegeben") lügt deshalb.
2. **Belege vor Nachlage.** `sync_once()` rechnet ab, bevor `repair_batches()`
   auffüllt.
3. **Schonfrist für den Beleg.** `REPAIR_GRACE_SECONDS = 600`: fehlt eine
   Handreichungskopie und der Eintrag gilt als „Staged", setzt `repair_batches()`
   zuerst `MissingSinceUtc` und wartet. Erst nach zehn Minuten kommt die Kopie aus dem
   Archiv zurück, und mit ihr fällt das Merkmal wieder weg. Eine unterbrochene Kopie
   („Copying") hat das Telefon nie erreicht und wird weiterhin **sofort** ersetzt.

## 6. Was am 2026-10-07 schief lief — Timeline, gemessen

| UTC | Telefon (CEST) | Befund |
|---|---|---|
| 13:34 | 15:34:13 | `adb install -r` (1.2.3) force-stopt die Companion; der START_STICKY-Neustart hinterließ `ServiceRecord app=null` — der 30-s-Tick lief nie wieder. Sichtbar nur als „Pausiert", **keine Fehlerzeile auf der NAS**. |
| 13:41 | 15:41 | Freigabe von 97 Dateien war **erfolgreich** (logcat: `NoSuchFileException` für alle 97). |
| 13:41–13:42 | | `repair_batches()` sah die via Resilio zurückgetragene Löschung, bevor der Beleg da war, und **kopierte alle 97 aus dem Archiv zurück** — inkl. neuem `StagedUtc`, die 72-h-Uhr wurde damit zurückgesetzt. |
| 13:43 | | Build mit der härteren Kapazitätskante `room = capacity - held_bytes` deployt. |
| 13:52 / 13:55 | 15:52:31 / 15:55:46 | von mir: Fehl-Tap auf den Sicherheits-Haken → „Überwachung pausiert", dann manuell neu gestartet. **Passiert um 18:13:26 ein zweites Mal** — dieselbe Falle, unten in §10 steht jetzt die Regel dazu. |
| 14:33 | 16:33:48 | 8 Dateien: zweimal „Nichts freizugeben" → Absage-Beleg. completed 287 → 392, staged 97 → 41, neuer Batch `20261007-143456` (14:34:56) sofort nachgelegt. |
| 14:36 | 16:36:01 | **1.2.4 installiert** — Protokoll: „Bedienungshilfe verbunden." + „Überwachung lief nicht – wird neu gestartet.", danach normaler 30-s-Takt. |
| 15:05 | 17:05:07 | 41 Dateien: Absage-Beleg → **completed 392 → 433**, staged 41 → 0, Batch-Ordner weg, neuer Batch `20261007-150538` mit 12 Dateien. |
| 15:13 | 17:13:10 | Telefon: „Sicherung abgeschlossen (Prüfung 1/2)" für die neuen 12. |
| 15:18:58 | 17:18:58 | **„Setup saved"** im Log: `BatchGiB` 0,25 → **5,0**. Von dir im Web-UI gesetzt — kein POST von mir (im Protokoll liegt nur der Setup-POST vom 06.10. 10:02 UTC, und der war vor deiner 0,25-Einstellung). |
| 15:19:43 | | `select_and_stage_batch()` füllt die neue Kapazität sofort: **597 Dateien / 4,75 GiB**, Batch `20261007-151943`, um 15:20:34 in der Übergabe fertig. |
| 15:21 | 17:21 | Latenz-Messung über die Erhöhung hinweg: Marker in `control/` geschrieben, nach **135 s** auf dem Pixel sichtbar (Poll alle 5 s, beidseitig wieder gelöscht). |
| ~15:28 | 17:28 | Beide Batches sind auf dem Pixel: `staging/Batches/20261007-150538` 256 MB, `…/20261007-151943` **4,7 GB** (`du`). Freier Phonespeicher damit **8,2 GiB** von 24 G (`df /data`, 66 % voll) — vorher 10,69 GiB. |
| 15:29:16 | 17:29:16 | App übergibt **609 stabile Dateien** auf einmal an Fotos (beide Batches in einem Angebot; die 12 aus der Absage-Runde 1/2 sind dabei). |
| 15:29:22 | 17:29:22 | App liest „backup paused" aus dem Startschirm-Pill und geht in `PHASE_ERROR` — „Es wurde nichts freigegeben". **Korrektur meiner selbst:** das war **kein Fehllesen der App**, der Pill stand wirklich so (§7). |
| 15:32 | 17:32 | Bildschirmkontrolle: Pill jetzt **„Backing up photos"** — der Upload lief wieder. `PHASE_ERROR` ist aber **endgültig** (`BackupMonitorService.java:118` → „Angehalten: App öffnen"; `PhotosAccessibilityService.java:103` steigt in ERROR aus), die Leitung stand also still, während die Bytes weiterliefen. |
| 15:33 | 17:33:52 | Von mir: erster Tap auf „Fehler zurücksetzen" — **daneben** (y=320; die Knopfzeile endet bei y≈305, Mitte liegt bei 243). Der Service lief weiter (`app=ProcessRecord{…}`, `isForeground=true`), die Schleife blieb trotzdem in `PHASE_ERROR` stehen. |
| 15:46 | 17:46 | Bildschirmkontrolle: unverändert „Aktiv: wegen Fehler angehalten", derselbe Detailtext von 17:29:22. Das ist der Beweis gegen meinen eigenen Handgriff — `AppState.phase()` (`AppState.java:43-51`) ruft *jedes* Mal `log()` auf, `log()` (`:133-142`) hängt bedingungslos an, und im gespiegelten Protokoll stand seit 17:29:22 **keine** Zeile. |
| 15:49:48 | 17:49:48 | „Fehler zurücksetzen" **getroffen** (780, 243). Protokollzeile „Fehlerzustand manuell zurückgesetzt.", Kopfzeile wieder „Aktiv: Ordnerüberwachung". |
| 15:50:06 | 17:50:06 | App übergibt erneut **609 stabile Dateien** an Fotos; Fotos zeigt „Backing up photos". Der ganze Batch hing also 20 Minuten nutzlos in der Warteschleife, obwohl die Bytes längst liefen. |
| 15:51:44 | 17:51:44 | **Derselbe Stopp nach 98 s wieder.** Protokoll: „Google Fotos meldet einen Sicherungsfehler („backup paused"). Es wurde nichts freigegeben." Kein Zufall, kein Kippel-vom-Bock: die Automatik steht nach jedem Zurücksetzen wieder exakt in diesen Zustand. |
| 15:53 | 17:53 | Pill **„Backup paused"** (Wolke mit Pause-Zeichen). Aufgeklappt: **„Backing up 21 photos" / „Checking time remaining" / „Keep the app open for faster backup"**. Upload-Rate über je 55 s: 1,32 / 0,00 / 0,11 / 0,84 MiB/min. Genau das macht den Wortlaut unbrauchbar: derselbe Pill steht bei **0 MiB/min** wie bei **18 MiB/min** (§7). |
| 15:56–16:11 | 17:56–18:11 | **Der lange Stich:** 15 Minuten `wlan0 tx` über zwei Punkte = **0,23 MiB/min** (0,203 GiB im Fenster). Zum Vergleich die drei Kurzstiche von 17:34–17:42: 13,3 / 13,4 / 18,6 MiB/min. Die Leitung war in dieser halben Stunde also **praktisch zu**, bei Bildschirm an, ohne Doze (`mWakefulness=Awake`, `deviceidle mState=ACTIVE`), Akku 100 % am Kabel, 44,2 °C. |
| 16:05 | 18:05 | Pill jetzt **„Backup complete"** — während auf dem Telefon unverändert **256 MB + 4,7 GB** Batch liegen (`du`) und der belegte Speicher *steigt* (16.749.012 → 16.755.472 KB in einer Minute, Fotos schreibt Cache). `staged` auf der NAS weiter 609. Genau der Fall §7: der Abschluss-Text beweist nichts. |
| 16:06–16:08 | 18:06–18:08 | Aufgeklapptes Backup-Blatt: **drei Minuten lang nur Spinner**. Fotos prüft seine Bibliotheksschlange, sagt aber „complete". |
| 16:13:26 | 18:13:26 | **Zweiter Fehl-Tap von mir auf denselben Haken** (15:52 war der erste): Swipe + Blind-Tap auf `(780, 243)` — nach dem Swipe liegt dort die Einwilligungsbox, nicht der Knopf. Box leer → Protokoll „Überwachung pausiert". |
| 16:14:30 | 18:14:30 | Box wieder gesetzt, „Überwachung starten" **mit frischem Screenshot vorher** getippt (275, 435). Protokoll: „Überwachung gestartet." |
| 16:16:32 | 18:16:32 | App übergibt zum dritten Mal **609 stabile Dateien**; Service lebend (`app=ProcessRecord{…}`, `isForeground=true`). |

**Was das für die Deutung heißt:** „Backup paused" ist auf diesem Gerät kein
Fehlerzustand, sondern der **Idle-Zustand zwischen zwei Häppchen**. Fotos sichert in
Portionen („21 photos"), lässt die Queue zwischendurch los und sagt dann genau den Satz,
den die App als Endpunkt interpretiert. Die 36 Nadeln in
`PhotosAccessibilityService.java:128-137` können das nicht unterscheiden — auf dem
Startschirm gibt es außer dem Pill keinen Text, der Fortschritt anzeigt. Die
`BACKUP_ACTIVE_NEEDLES`-Gegenprobe (`:138`, u. a. „backing up") greift nur in der
Sekunde, in der der Pill selbst auf „Backing up photos" steht.

Gegenprobe auf der NAS, seit dem 3.3.17-Deploy: „Re-provided handover file"
**konstant 307** (alle aus der Zeit davor), „waiting for its receipt before
restocking" 0. Der Burst ist also nicht weiter aufgetreten; der Schonfrist-Pfad
selbst hat in Produktion noch nie gezündet — er ist durch Tests belegt
(`tests/test_batches.py`, `tests/test_sync.py`) und meldet sich, sobald eine echte
Freigabe dem Beleg zuvorkommt.

Telefonseitig nach dem Recreate lag **ein** Batch-Ordner `20261007-150538` mit 14
Einträgen (12 Dateien + Manifest + Bereitschaftsmarker) — die 0,5-GiB-Doppelfüllung des
ersten 3.3.16-Builds war damit abgebaut. Seit deinem Setup-Speichern um 15:19 UTC sind
es **zwei**: dazu `20261007-151943` mit 599 Einträgen / 4,7 GB.

## 7. Die Telefon-Seite: Takt, Phasen, Lebenszeichen

- `POLL_MILLIS = 30 s`, `STABLE_MILLIS = 120 s` (eine Datei muss zwei Minuten ruhige
  Schreibzeit haben), Absage-Zähler `NOTHING_TO_FREE_ROUNDS = 2`, Retry nach
  `15 * 60_000` ms.
- Phasen: MONITORING → WAIT_BACKUP → OPEN_FREE_UP → CONFIRM_FREE_UP → VERIFY, dazu
  ERROR. „Backup complete" auf dem Startschirm beweist **nichts** über die tatsächliche
  Freigabe — maßgeblich ist nur der Vergleich des Dateibestands vorher/nachher.
- **`updatedAt` ist kein Lebenszeichen.** `AppState.phase()` schreibt es bei jedem
  Phasenwechsel mit. Richtig messen: zwei Stichproben im Abstand > 30 s **und**
  `dumpsys activity services de.pixelphotouploader.companion/.BackupMonitorService |
  grep app=` — `app=null` heißt: Schleife tot, App läuft trotzdem weiter.
- Die Bedienungshilfe ist der Anker: Sie ist an das System gebunden und lebt, solange
  sie eingeschaltet ist. `keepMonitorAlive()` prüft alle 60 s und startet die
  Überwachung neu, wenn `enabled` gesetzt ist und kein Service läuft. Wer selbst
  pausiert hat, wird nicht geweckt.
- **`PHASE_ERROR` ist eine Sackgasse, kein Zustand mit Rückweg.** Nichts startet die
  Schleife daraus wieder — nur „Überwachung starten" oder „Fehler zurücksetzen" in der
  App (`MainActivity.java:159/162`). Das ist teuer, weil die Fehler-Erkennung
  **bildschirmtextbasiert** ist: 36 Nadeln (`PhotosAccessibilityService.java:128-137`)
  entscheiden über Anhalten.
- **„backup paused" ist der Idle-Zustand zwischen zwei Portionen, nicht der
  Fehlerzustand der Sicherung.** Das ist die Korrektur eines Satzes, den ich früher in
  diese Datei geschrieben habe (und der dort in §6 jetzt dabeisteht): Ich hielt den Fund
  um 17:29:22 für einen **Fehlalarm**, weil der Pill zwei Minuten später „Backing up
  photos" zeigte. Nach dem zweiten Stopp um 17:51:44 und dem aufgeklappten Backup-Blatt
  („Backing up 21 photos", „Checking time remaining", „Keep the app open for faster
  backup") ist die Lesart eine andere: die App hat den Text **richtig** gelesen — der
  Pill stand wirklich da. Falsch ist, was sie daraus macht. Beleg dafür, dass es trotzdem
  voranging: zwischen dem Alarm von 17:29:22 und 15:45 UTC habe ich 12,7–18,6 MiB/min
  gemessen, also ~13 Minuten Upload *während* `PHASE_ERROR`. Der Pill ist eine
  Portionsanzeige, keine Leitungsaussage. Ein Zustand, der alle zwei Minuten wiederkommt,
  darf die Automatik nicht anhalten; er darf höchstens die Runde neu zählen.
- **Die Gegenprobe reicht nicht.** `BACKUP_ACTIVE_NEEDLES` (`:44-50`, u. a. „backing up",
  „uploading", „items left") soll einen Alarm unterdrücken, wenn die Sicherung sichtbar
  läuft. Auf dem Startschirm ist der Pill *derselbe* Text, der über Pause und Aktiv
  entscheidet — es gibt dort keinen zweiten Text. Die Nadeln greifen erst im aufgeklappten
  Backup-Blatt. Wer die Automatik über den Pill steuert, braucht einen Zähler statt eines
  Wortlauts: zweimal „paused" in Folge *ohne* dazwischen gesehenes „backing up" ist ein
  Stopp, alles andere ist Warteposition.
- **Der Zähler für genau diesen Fall existiert schon — nur nicht auf dem Fehlerpfad.**
  `noteStuck()` (`PhotosAccessibilityService.java:262-276`) arbeitet mit `stuckSince` und
  lässt **30 Minuten** (`STUCK_MILLIS`, `:27`) vergehen, bevor es `PHASE_ERROR` meldet; der
  Pfad „weder aktiv noch abgeschlossen" ist also bereits transient behandelt. Die 36
  Fehler-Nadeln (`:128-144`) haben denselben Zähler **nicht** — sie gehen beim ersten
  Treffer sofort in Endpunkt. Task 6 ist damit kein neuer Mechanismus, sondern: den
  bestehenden auf den zweiten Pfad legen.
- **Zurücksetzen ist nicht umsonst.** Nach dem Tap von 17:49:48 bietet die App alle 609
  Dateien neu an (`17:50:06`), und das heißt: `scanner.mediaScan()` über 609 Dateien und
  Fotos muss die Bibliotheksschlange neu prüfen („Checking time remaining"). Die Rate fiel
  davon auf **1,32 / 0,00 / 0,11 / 0,84 / 0,69 / 0,68 / 1,91 / 1,16 MiB/min** (acht Stiche
  à 55 s, 17:51–17:58 CEST, Mittel ~0,84) — nach 12,7–18,6 MiB/min vor dem Stopp. Ob das
  der MediaScan allein ist oder Fotos' eigener Tag-Rhythmus, ist hier **nicht** entschieden;
  entschieden ist nur die Reihenfolge: erst der Einbruch, nachdem neu übergeben war.
- **Hinlangen heißt: Tap treffen und Protokoll lesen.** Der Kopfzeilen-Wechsel allein
  ist kein Beleg — `update()` schreibt nur den Text. Ein Handgriff an der App hat erst
  stattgefunden, wenn `companion-log.txt` eine neue Zeile hat (17:33 vs. 17:49:48 oben).
  **Es gibt keine feste Knopfkoordinate.** Die Knopfzeile sitzt direkt unter der
  Einwilligungsbox, und die ganze Seite scrollt: mit Seite oben liegt „Fehler
  zurücksetzen" bei `(780, 243)`, nach einem Swipe hoch auf dieselbe Höhe — und dann
  trifft man den **Haken**, was die Überwachung pausiert. Also: **erst Screenshot, dann
  Tippen, dann Protokollzeile als Beweis.** Zwei von mir selbst gemachte Fälle: 15:52:31
  und 18:13:26.

## 8. Durchsatz: was die 1,6 TB praktisch bedeuten

- Bestand + Archiv: 1.539,7 GiB offen, 177.371 Dateien.
- **Live seit 15:19 UTC: `BatchGiB = 5,0`** (von dir gesetzt). Das sind
  **~308 Batches** für den ganzen Bestand. Zum Vergleich die 0,25 GiB von gestern:
  ~6.160 Batches.
- Der Engpass verschiebt sich damit: Die zwei Absagerunden à 15 Minuten kosten pro
  Batch gleich viel Zeit, verteilen sich aber auf 20× mehr Bytes. Was bleibt, ist die
  reine Sicherungszeit — und die ist **gemessen**: drei Stichproben über den
  `wlan0`-Sendezähler (17:34–17:42 CEST) geben **13,3 / 13,4 / 18,6 MiB/min**, also
  **0,8–1,1 GiB je Stunde**. Ein 5-GiB-Batch braucht damit **~5–6 h** reine Uploadzeit,
  der ganze Bestand **~1.400–1.900 h ≈ zwei bis zweieinhalb Monate** Dauerbetrieb am
  Kabel. Drei Grenzen der Zahl: `wlan0 tx` zählt *allen* Sendeverkehr des Telefons
  (Obergrenze für den Anteil von Fotos), die Absage-Runden sind noch nicht drin, und —
  die Messlatte selbst — **es gibt zwei Regime, nicht eine Rate.** Ein *langer* Stich über
  volle 15 Minuten (17:56–18:11 CEST, zwei Punkte `wlan0 tx`) ergibt **0,23 MiB/min**, das
  sind **0,014 GiB je Stunde** — bei Bildschirm an, ohne Doze, Akku voll am Kabel. Davor
  lagen 12,7–18,6 MiB/min, danach acht Kurzstiche mit Mittel ~0,84. Die 0,8–1,1 GiB/h sind
  also die **Spitzengeschwindigkeit im schnellen Regime**, und die zwei bis zweieinhalb
  Monate gelten **nur dort**; im gemessenen langsamen Regime wären es Jahre. Welche der
  beiden Ursachen das entscheidet, ist offen: Fotos drosselt je Tageszeit, oder jede
  Neu-Übergabe (`mediaScan` über 609 Dateien) wirft die Schlange zurück — beides ist
  beobachtet, keines ist bewiesen. **Bevor die Monatszahl jemandem als Plan verkauft wird,
  gehört ihr ein Durchsatz-Protokoll über einen ganzen Tag.**
- **Zwei Dateien bleiben außerhalb jeder 5-GiB-Kappe** (13,98 GiB ≈ 0,9 % aller Bytes):
  `Altbestand/2018.06 Astrid & Tobias Hochzeit/Freie Trauung/2018-06 Hochzeit Astrid
  und Tobias (11).avi` mit **8,17 GiB** und
  `Altbestand/People/Noah/2018.08 Städtisches Klinikum/C0122.MP4` mit **5,81 GiB**.
  Bei 0,25 GiB waren es noch 450 Dateien / 0,29 TiB (19,5 % der Bytes).
- **Der Phonespeicher ist jetzt die harte Kante:** gemessen 8,2 GiB frei von 24 GiB
  (`df /data`, 66 % belegt), während die 5,00 GiB Handreichung schon liegen
  (17:33 CEST). Vorher: 10,69 GiB frei bei 0,25-GiB-Batches. Ein zweiter 5-GiB-Batch
  passt, bevor der erste abgerechnet ist, **nicht** — die Kapazitätskante
  `room = capacity - held_bytes` verhindert das auch, aber Resilio-Teilkopien zählen
  dort nicht. **Ein Puffer fehlt:** `ReserveGiB` (1,5) steht zwar in der Konfiguration,
  wird aber nirgends gelesen — der Server kennt den freien Phonespeicher nicht und
  kann nur über die Batch-Größe darauf Rücksicht nehmen.
- Die **Log-Flut ist mit der Kappe fast weg**: statt ~30 Überspring-Warnungen je
  Durchlauf (34.682 seit dem Bestand) sind es jetzt genau **2** — die beiden Riesen
  oben. `grep -v "Single file larger"` ist damit nur noch für Alt-Protokolle nötig.
- Die 0-Byte-Dateien (290) sind bereits raus, kosten also keine Runden mehr.

## 9. Offen — und deine Entscheidung

1. **Video-Kappe — die hast du selbst entschieden** (15:18:58 UTC auf 5,0 GiB). Offene
   Reste: die zwei Dateien über 5 GiB (13,98 GiB, §8) brauchen entweder 9 GiB Kappe —
   bei 8,2 GiB freiem Phonespeicher geht das nicht — oder einen getrennten Weg. Die
   Frage, ob Fotos die Bibliotheksschlange bei 5 GiB hält, hat um 18:05 CEST **eine
   vorläufige Antwort**: Pill „Backup complete", während unverändert 4,7 GB auf dem
   Telefon liegen und nichts frei wird (§6).
2. **Log-Flut — erledigt sich fast von selbst.** Bei 5,0 GiB Kappe sind es noch zwei
   Warnungen je Durchlauf (§8). Die gebündelte Meldung („N Dateien übersprungen,
   größte: X") wäre trotzdem die sauberere Lösung, ist aber kein Blocker mehr.
3. **inotify-Limit — ist erledigt.** Host und Container lesen 524288 / 512, Resilio
   läuft seit dem Boot um ~06:53 UTC damit. Die neue Latenzmessung (135 s) zeigt aber:
   der Weg ist dadurch nicht schlagartig schneller geworden. Die 600-s-Schonfrist
   bleibt also richtig begründet; ein zweiter Messlauf über mehrere Tageszeiten wäre
   die Voraussetzung, sie zu verkürzen.
4. **Deine Handarbeit (sudo, nur bei dir):** `sudo rm -rf
   /DATA/AppData/pixel-photo-uploader/pixelsync` — 1,19 GB Alt-Kopie außerhalb von
   Resilios Sync-Wurzel — und die Compose-Kopien auf der NAS nachziehen: sie driften
   vom Repo, deployt wird deshalb aus `/tmp`.
5. **Task 6 — jetzt mit Grund, nicht mehr mit Verdacht.** Der Betriebsfall ist
   wiederholt und gemessen (§6: 17:29:22, dann nach Zurücksetzen 17:51:44 erneut, Rate
   danach 1,32 / 0,00 / 0,11 MiB/min). Die Leitungsfolge: **ohne Fix ist der Betrieb nicht
   mehr unbeaufsichtigt.** Irgendwann steht die Automatik in `PHASE_ERROR`, und nur ein
   Hand-Tap holt sie raus — bei jedem Batch, mehrfach.
   Der Entwurf hat sich durch die Messung verschärft:
   - „backup paused" ist **kein Fehler**, sondern Fotos' Idle zwischen zwei Portionen.
     Er darf die Runde nur zählen, nicht die Leitung anhalten — wie bei „Nichts
     freizugeben" (`NOTHING_TO_FREE_ROUNDS = 2`, Retry nach 15 min).
   - `PHASE_ERROR` bleibt nur für echte Endfälle: Fotos nicht installiert, 72 h ohne
     Beleg, „account storage full".
   - Die Gegenprobe braucht einen **Zähler statt eines Wortlauts** — und den gibt es
     schon: `noteStuck()` (`:262-276`) meldet einen unbekannten Bildschirm erst nach
     `STUCK_MILLIS` = 30 min als Fehler. Auf den Nadel-Pfad (`:128-144`) ist derselbe
     Zähler nie gelegt worden. **Task 6 ist also kein neuer Mechanismus, sondern eine
     Zeile Verschiebung.** Dazu: „checking time remaining" und „keep the app open" in
     `BACKUP_ACTIVE_NEEDLES` (`:44-50`), damit das aufgeklappte Backup-Blatt zählt.
   - Kleiner Eingriff in `PhotosAccessibilityService.inspect()`, braucht ein APK-Update
     und danach den einen Hand-Tap „Überwachung starten". Sag Bescheid, dann baue ich das.
6. **Was die 5 GiB heute noch brauchen.** Der Batch läuft nicht mehr von allein durch:
   Er braucht entweder den Fix aus Punkt 5, oder gegen Ende einen Tap auf „Fehler
   zurücksetzen", damit die App den Dateibestand vergleicht und den Beleg schreibt.
   Der Beleg selbst ist nicht in Gefahr — `healReceiptFromDisk()` entscheidet über den
   Bestand, nicht über den Bildschirm.
7. **Die größte offene Zahl: in welchem Regime läuft die Leitung eigentlich?** Gemessen
   sind 0,8–1,1 GiB/h und 0,014 GiB/h **am selben Nachmittag** (§8). Solange das nicht
   entschieden ist, ist jede Monats-Aussage über die 1,6 TB eine Silbe, kein Plan. Der
   billigste Test, der die beiden Erklärungen trennt: **einmal nicht anfassen** — ein Tag
   lang weder Reset noch `mediaScan` noch Screenshot-Taps, nur `staged`/`completed` und
   `wlan0 tx` über Stunden mitschreiben. Fängt die Rate von allein wieder an, drosselt
   Fotos nach Tageszeit; bleibt sie bei ~0, war es meine Neu-Übergabe. Den Lauf kann ich
   aufsetzen, wenn du willst.

## 10. Messregeln, damit die nächste Sitzung nicht auf falschen Zahlen sitzt

- Zustand zuerst über `GET :8088/api/status` und `GET :8088/api/log?lines=N` — beide
  rein lesend, kein SSH nötig. `POST /api/sync` würde dagegen echt einen Pass anstossen.
- **„Speichern" im Web-UI ist kein Teil-Update:** `apply_setup()` baut die Konfiguration
  aus `DEFAULTS` nach (`setup.py:58`) und überschreibt nur die elf Formularfelder. Alles,
  was nicht im Formular steht (`ReserveGiB`, `BackupPollSeconds`, `ScanGraceMinutes`,
  `RemoteRoot`, `KeepAwake`, `RequireUnlocked`), liegt danach wieder auf dem Default —
  und ein Feld, das im Browser noch offen ist, speichert den **alten** Wert. Nach jedem
  Speichern `/api/status` gegenlesen.
- Log-Zeitstempel: NAS **UTC**, Telefon-Protokoll **CEST**.
- Im Log erst `grep -v "Single file larger than batch capacity"`, dann lesen.
- In den Containern lesen ohne Shell-Chaos:
  `ssh -i ~/.ssh/id_ed25519_zimaos ysamjo@192.168.178.162 'docker exec -i
  io-github-ysamjo-pixel-photo-uploader-server-1 sh -s' < script.sh`
  (Mehrzeiler mit `python -c` statt Heredoc, verschachtelte Quotes brechen sonst).
- `adb devices` zeigt drei Transporte: `FA69M0305152` (USB) und `192.168.178.53:5555`
  (derselbe Pixel, TCP) sind ok; `5C230DLCH003RC` ist das **Pixel 10 Pro** und
  `192.168.178.141:5555` der **Google TV Streamer** — beide nicht anfassen, vor jedem
  Zugriff `getprop ro.product.model` (muss `Pixel` sagen).
- Kein `uiautomator dump`, Screenshots nur nach `/data/local/tmp` — alles andere
  landet im MediaStore und wird von der App als neuer Ordner behandelt.
- Fortschritt am Telefon über `awk '/wlan0/{print $10}' /proc/net/dev` — **Feld 10 ist
  tx**, Feld 9 ist multicast. **Aber: kurz ist wertlos.** Fotos sichert in Portionen, ein
  55-s-Fenster hat 0,00 MiB/min gezeigt, während in den 13 Minuten drumherum 12–18 MiB/min
  liefen. Für eine Rate braucht es ein Fenster von **mindestens 15 Minuten**, oder besser
  den Differenzwert zweier `/api/status`-Stiche (`staged`/`completed`) über eine Stunde.
- Den Startschirm-Pill **nicht** als An/Aus der Leitung lesen: „Backup paused" ist dort
  Portionsanzeige, kein Ausfall (§7). Beweiskräftig sind nur der `wlan0`-Zähler über ein
  langes Fenster und der Dateibestand.
- „Free up space" in Google Fotos **nie von Hand** bestätigen: das löscht
  Telefon-Medien. Dafür ist die App da, und die macht das nur nach ihrer Haken-Abfrage.
- Fingerabdruck-Schlüssel überall: `NNNNNN-<fp12>.ext`, der Zwölfer-Teil ist die
  Inhaltsmarke, die die App sich für Absagen merkt (`AppState.refusedTokens`).
