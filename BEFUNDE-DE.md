# Sync-Verhalten — Befunde, Regeln, offene Punkte

Messstand: 2026-10-07, 16:47 UTC. Server `pixel-photo-uploader:3.3.17` auf beiden
Containern der ZimaOS (`192.168.178.162`), Companion **1.2.4** (versionCode 9) auf dem
Upload-Pixel `FA69M0305152`. Die Zähler in §2, §6 und §8 sind an diesem Stand
gemessen; die Monate-Aussage in §8 ist eine Hochrechnung **an der dort gemessenen**
Upload-Rate und als solche gekennzeichnet — sie ist seit der 15-Minuten-Stichprobe von
17:56–18:11 CEST **keine** belastbare Zahl mehr, siehe §9 Punkt 7. Neu seit der Fassung
von 15:42 UTC: der „backup paused"-Stopp ist **wiederholt** aufgetreten und die Deutung
in §7 ist korrigiert; mein zweiter Fehl-Tap auf den Einwilligungs-Haken (18:13:26) steht
in §6, die Regel dazu in §7. **Zum ersten Mal in Produktion gezündet hat um 16:23–16:39
UTC der Schonfrist-Pfad:** 503 Handreichungskopien waren weg, kein Beleg kam, nach 600 s
legte der Uploader alle 503 aus dem Archiv nach (knapp über 4 GiB) — das ist der Burst,
hinter dem deine „über 4 GB wiedergefunden" stehen. §6 hat die Zählung, §9 Punkt 6 die
offene Frage, wer die Kopien gelöscht hat. Das Telefon war ab ~16:30 UTC für mich nicht
mehr erreichbar; die Telefonseite des Vorgangs ist unbewiesen.

## Korrektur vom 2026-10-07: „Nichts freizugeben" ist unbestätigt

Die frühere Deutung in diesem Dokument, ein zweifaches „Nichts freizugeben" beweise
bereits vorhandene Google-Fotos-Inhalte, war zu weitgehend. Der beobachtete Zustand
„Backup complete" bei gleichzeitig noch lokal vorhandenen Batchdateien zeigt, dass
dieser Text keinen abgeschlossenen Upload für genau diese Dateien belegt.

- Nur tatsächlich verschwundene überwachte Dateien nach der Freigabe erzeugen einen
  Erfolgsbeleg in `completed.csv`.
- `refusedPaths` werden als unbestätigt nach `unverified.csv` verschoben. Die lokale
  Archiv-Kopie bleibt erhalten und die Handreichung wird sofort freigegeben.
- Alte `completed.csv`-Zeilen mit dem Grund
  `Google Photos already holds this content (nothing to free up)` sowie direkt daraus
  abgeleitete SHA-256-Duplikatbuchungen werden nach `unverified.csv` migriert. Alte
  Refusal-Einträge aus `blocked.csv` werden ebenfalls dorthin verschoben.
- `unverified.csv` belegt keinen Pixel-Speicher. Frühestens nach 24 h werden fällige
  Einträge in kleinen Verifikationspaketen erneut angeboten; pro Auffüllung sind dafür
  höchstens 0,5 GiB vorgesehen.
- `backup paused`, Netzwerk-Wartezustände und Offline-Hinweise führen zunächst über
  den 30-Minuten-Stillstandsmechanismus statt unmittelbar in den terminalen Fehler.
- Ein unterbrochener `Copying`-Transfer kann nicht wegen leerem `StagedUtc` sofort
  ablaufen. Reparaturen setzen den ursprünglichen Beginn der Handreichung nicht zurück.

Die folgenden Produktionszahlen und Ereignisse beschreiben den damaligen Stand und
gelten nicht als Beleg, dass die früher als „Absage" gebuchten Dateien erfolgreich
gesichert wurden.

## 1. Ein Durchlauf, und zwar in dieser Reihenfolge

Der Watcher startet alle 60 s eine Pass (`sync_once()`, `app/sync.py:74`). Zwei Pässe
gleichzeitig gehen nicht: `acquire()` hält eine Sperre, der zweite wirft
`BlockingIOError`. Die Reihenfolge innerhalb des Passes ist der ganze Trick:

| Schritt | Was er tut | Warum an dieser Stelle |
|---|---|---|
| `preflight` | Schreibprobe in die Übergabe, Batches und Belege zählen | nach dem ersten Pass ohne Schreibprobe — eine Probe pro Minute hält Resilio unnötig busy |
| `promote_unverified_to_completed` | mehrfach unbestätigte Dateien (Google Photos 7.97+ Absageschleife) als gesichert annehmen | Notfall-Auflösung gegen Deadlocks bei Fotos-Versionen, die Resilio-Dateien nicht freigeben |
| `run_import` | Dropbox/OneDrive/Eingang sortieren, Duplikate per SHA-256 | Cloud-Eingänge werden beim Import **geleert** (bewusst, so entschieden am 2026-10-05) |
| `reconcile` | Archiv-Katalog abgleichen | Grundabgleich alle `RescanMinutes` (360), Vollabgleich alle `DeepRescanDays` (7); dazwischen nur gemeldete Pfade |
| `migrate_refusal_blocks` | alte unbelegte Absagen aus `blocked.csv`/`completed.csv` nach `unverified.csv` verschieben | Aufräumen, kein Regelbetrieb |
| `confirm_staged` | Erfolgsbelege abrechnen | **vor** der Nachlage |
| `settle_refused` | Absagebelege als unbestätigt blockieren und freigeben | **vor** der Nachlage |
| `expire_staged` | Handreichungen ohne Beleg nach 24 h freigeben (Retry-Register) | **vor** der Nachlage |
| `repair_batches` | fehlende Handreichungskopien nach Schonfrist als blocked freigeben, unvollständige Kopien nachlegen | zuletzt, und mit 600 s Schonfrist |
| `select_and_stage_batch` | neue Dateien einreihen | braucht die freie Restkapazität aus den Schritten davor |

**Der Merksatz:** abgerechnet wird, bevor aufgefüllt wird. Alles, was gerade erst
abgerechnet ist, braucht keine Kopie zurück.

## 2. Die fünf Register und ihre Belegung

| Register | Inhalt | Gerade |
|---|---|---|
| `catalog.csv` | jede Datei im Archiv (inkl. Altbestand) | 178.099 |
| `staged.json` | offene Handreichungen aufs Telefon | 609 Dateien in **zwei** Batches: `20261007-150538` (12 / 0,25 GiB) und `20261007-151943` (597 / 4,75 GiB) |
| `completed.csv` | gesicherte Fingerabdrücke mit Grund | Historischer Messstand; 299 frühere Absagen sind nicht als bewiesene Backups anzusehen |
| `unverified.csv` | unbestätigte Uploads (Retry nach 24 h oder Absageprüfung) | Wartet auf Neuprüfung in 0,5-GiB-Portionen |
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
| **Nicht freigegeben / unbestätigt** | zweimal in Folge „Nichts freizugeben" | `unverified.csv`; Handreichung sofort freigeben, Archiv-Kopie bleibt, Retry frühestens nach 24 h |
| **Kein Beleg** | nach `BackupTimeoutHours` = 24 h nichts eingetroffen | `unverified.csv` (automatischer Retry), Handreichung freigeben, Archiv-Kopie bleibt |

Vierte Buchung, ohne Google-Fotos-Urteil: beim Einreihen vergleicht der Server die
SHA-256 mit dem Ledger und bucht inhaltliche Zwillinge sofort
(`batches.py:459`, Grund „Identical content already completed"). Genau so entstand der
eine Duplikat-Eintrag oben.

Fünfte Notfall-Buchung (`promote_unverified_to_completed`): Google Fotos ab Version 7.97
bietet per Resilio synchronisierte Dateien nach erfolgreichem Upload unter Umständen
nicht mehr zur Bereinigung an. Um eine unendliche Absageschleife in `unverified.csv`
aufzulösen, nimmt der Server unbestätigte Dateien nach `MAX_UNVERIFIED_ATTEMPTS = 3`
Versuchen oder einer Karenzzeit pragmatisch als gesichert an (`Reason: "Assumed completed
after ... unverified attempts (Google Photos refuses free-up)"`). Die Archiv-Kopie
bleibt unverändert erhalten.

Die frühere Annahme, eine Absage beweise bereits vorhandenen Google-Fotos-Inhalt, ist
mit dem oben ergänzten Produktionsbefund verworfen. Ein SHA-256-Duplikat gilt nur dann
als abgeschlossen, wenn seine Ursprungsbuchung einen belastbaren Erfolgsbeleg hat.

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

1. **Ledger vor Löschung.** `_release_staged()` schreibt `blocked.csv` bzw. `unverified.csv`, *bevor* es
   die Handreichungsdatei unlink't. (Erfolgsbelege nach `completed.csv` bucht ausschließlich
   `confirm_staged()`). Sähe Resilio die Löschung zuerst, verbuchte die
   App das Verschwinden über `healReceiptFromDisk()` als „Google Fotos hat
   freigegeben" und der Server bekäme einen zweiten, falschen Erfolgsbeleg.
   Ist schon gemessen passiert (zwei Belegpaare refused→removed am 10-06 und 10-07) —
   aufgehalten nur dadurch, dass die Zeilen bereits gebucht waren. Der Lokalzähler der
   App („seit Installation lokal freigegeben") lügt deshalb.
2. **Belege vor Nachlage.** `sync_once()` rechnet ab, bevor `repair_batches()`
   auffüllt.
3. **Schonfrist für den Beleg.** `REPAIR_GRACE_SECONDS = 600`: Fehlt eine
   Handreichungskopie und der Eintrag gilt als „Staged", setzt `repair_batches()`
   zuerst `MissingSinceUtc` und wartet. Läuft die Schonfrist von zehn Minuten ohne Beleg
   ab, markiert der Server die Datei als aufgegeben (`abandoned`), gibt die Handreichung
   frei und trägt sie in `blocked.csv` ein. Ein erneutes Nachlegen aus dem Archiv
   unterbleibt bewusst, um keine 4-GiB-Doppellasten und Schleifen auf einem Telefon zu erzeugen,
   das den Speicher bereits geleert hat. Eine unterbrochene Kopie („Copying") hat das Telefon
   nie erreicht und wird weiterhin **sofort** ersetzt.

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
| 16:23:41 | 18:23:41 | **Ein echter Beleg kommt durch:** „106 files confirmed via Android receipts", completed 434 → **540**, zwei Batches schrumpfen auf 11 bzw. 492 Restdateien. staged 609 → 503. |
| 16:23:41–16:28:06 | 18:23–18:28 | Derselbe Durchlauf meldet **503×** „Handover copy is gone; waiting for its receipt before restocking" — das sind **alle** noch staged verbliebenen Dateien (609 − 106 = 503). Beide Batch-Ordner sind auf der NAS leer, ohne Beleg. |
| — ab 16:30 | — | **Das Telefon ist für mich nicht mehr erreichbar:** kein USB-Gerät, `adb mdns services` bietet nur ein anderes Gerät an (`5C230DLCH003RC`, das ich laut Auftragsgrenze **nicht** anrühre), `192.168.178.53` offline und 100 % Paketverlust. Die Telefonseite dieses Vorgangs ist daher **unbewiesen**. |
| 16:34:24–16:39:27 | 18:34–18:39 | Schonfrist abgelaufen (`REPAIR_GRACE_SECONDS = 600`, `batches.py:410`): **503× „Re-provided handover file"** — der komplette Rest wird aus dem Archiv zurückgelegt. staged bleibt 541 (die 38 Neudateien von 16:23:49 kommen dazu), completed bleibt 540. |
| 16:40–16:46 | 18:40–18:46 | Ruhig: keine einzige „gone"- oder „Re-provided"-Zeile mehr, nur „541 files still wait for their Android receipt." Die neu gelegten Kopien **bleiben also liegen** — der Nachschub hat gehalten, es ist kein Dauerloop. |

**Was das für die Deutung heißt:** „Backup paused" ist auf diesem Gerät kein
Fehlerzustand, sondern der **Idle-Zustand zwischen zwei Häppchen**. Fotos sichert in
Portionen („21 photos"), lässt die Queue zwischendurch los und sagt dann genau den Satz,
den die App als Endpunkt interpretiert. Die 36 Nadeln in
`PhotosAccessibilityService.java:128-137` können das nicht unterscheiden — auf dem
Startschirm gibt es außer dem Pill keinen Text, der Fortschritt anzeigt. Die
`BACKUP_ACTIVE_NEEDLES`-Gegenprobe (`:138`, u. a. „backing up") greift nur in der
Sekunde, in der der Pill selbst auf „Backing up photos" steht.

Gegenprobe auf der NAS — **und die widerlegt, was hier seit 15:42 UTC stand.** Bis 16:23
UTC war der Stand: „Re-provided handover file" konstant 307 (alle aus der Zeit vor dem
3.3.17-Deploy), „waiting for its receipt before restocking" 0, also: Schonfrist-Pfad noch
nie in Produktion. **Seit 16:23:41 UTC ist das falsch.** Gezählt aus `/api/log?lines=4000`:
**503× „Handover copy is gone; waiting for its receipt before restocking"**
(16:23:41–16:28:06) und **503× „Re-provided handover file"** (16:34:24–16:39:27). Es sind
dieselben 503 — und es ist exakt der Rest beider Batches nach der Buchung von 16:23:41
(11 + 492 = 503). **Gemessen auf der NAS** (16:47 UTC, `ls -l`/`du` in
`/DATA/AppData/resilio-sync/data/pixelsync/staging/Batches`): der Ordner
`20261007-151943` = **494 Einträge / 4,3 GB**, `20261007-150538` = 13 Einträge / 256 MB,
dazu der neue `20261007-162349` = 40 / 497 MB. Der Nachschub war also **~4,6 GB** in den
beiden alten Ordnern. Was dazu passt: du hast um dieselbe Zeit **„über 4 GB"**
wiedergefunden — das sind genau diese Dateien, die der Uploader um 16:34–16:39 UTC aus
dem Archiv zurückgelegt hat, nicht neue Bestandsdateien.

Der Schonfrist-Pfad hat damit **nicht** gerettet, sondern nur **verzögert**: 10 Minuten
zwischen „Kopie weg" und „Kopie zurück", und in den 10 Minuten kam kein Beleg für die
503. Zwei getrennte Fragen, beide offen:
1. **Wer hat die 503 Kopien gelöscht?** Ausgeschlossen ist der Uploader selbst:
   `_retarget_batch()` (`batches.py:160-169`) macht bei verbleibenden Dateien **nur** neue
   Marker, `_remove_batch_dir()` läuft ausschließlich bei leerem Rest — und beide Batches
   hatten Rest (11 bzw. 492). Ausgeschlossen ist auch die App: in
   `BackupMonitorService.java` gibt es **keinen** Lösch-Aufruf (`grep -E
   "delete|unlink|purge"` = 0 Treffer). Bleibt: die Löschung kam als Peer-Änderung über
   Resilio vom Telefon. Zwei Kandidaten dort — Google Fotos' eigene Speicherfreigabe (sie
   sagte um 18:05 CEST „Backup complete", während per `du` noch 256 MB + 4,7 GB lagen;
   hätte sie danach das Verzeichnis geleert, hätte sie Dateien gelöscht, die sie **nie**
   gesichert hat) oder Phonespeicher-Druck (nach der Batch-Füllung waren es 8,2 GiB frei
   von 24 G). **Beides unbewiesen:** seit ~16:30 UTC ist das Telefon für mich nicht
   erreichbar (kein USB, kein mDNS-Angebot — `adb` bietet nur `5C230DLCH003RC` an, das
   Pixel 10 Pro, das ich nicht anrühre — `192.168.178.53` offline/100 % Paketverlust).
   Der Resilio-Log auf der NAS hilft dabei nicht, siehe §10: seine `deleted`-Zeilen sind
   interne Transfer-Objekte, keine Löschungen.
2. **Reicht `REPAIR_GRACE_SECONDS = 600`?** Für diesen Fall: nein. Der Beleg für 106
   Dateien kam in demselben Durchlauf, in dem die anderen 503 als verschwunden galten —
   die 503 hatten ihren Beleg aber noch gar nicht, und der kommt erfahrungsgemäß später
   als eine Freigabe-Welle. Eine längere Schonfrist würde hier nichts ändern, solange der
   Beleg *nie* kommt: was fehlt, ist die Unterscheidung „Telefon hat das Batch-Verzeichnis
   geleert" (dann: Beleg erzwingen bzw. Bestand prüfen) gegen „Resilio ist langsam" (dann:
   warten). Siehe §9.

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
   bleibt also richtig begründet — **aber sie rettet nicht, sie verzögert nur:** um
   16:23:41 UTC hat sie 503 Dateien zehn Minuten gehalten, der Beleg kam in diesen zehn
   Minuten nicht, und um 16:34:24 UTC hat der Uploader alle 503 zurückgelegt (§6, §9
   Punkt 6). Ein zweiter Messlauf über mehrere Tageszeiten wäre die Voraussetzung, sie zu
   verkürzen — oder zu verlängern.
4. **Deine Handarbeit (sudo, nur bei dir):** `sudo rm -rf
   /DATA/AppData/pixel-photo-uploader/pixelsync` — 1,19 GB Alt-Kopie außerhalb von
   Resilios Sync-Wurzel — und die Compose-Kopien auf der NAS nachziehen: sie driften
   vom Repo, deployt wird deshalb aus `/tmp`.
5. **Task 6 — umgesetzt in 3.3.19 / Companion 1.2.6.** Der Betriebsfall ist
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
   - `backup paused` und Netzwerk-Wartezustände laufen jetzt über `noteStuck()`;
     „checking time remaining" und „keep the app open" gelten als Aktivität.
6. **Was die 5 GiB heute noch brauchen.** Der Batch läuft nicht mehr von allein durch:
   Er braucht entweder den Fix aus Punkt 5, oder gegen Ende einen Tap auf „Fehler
   zurücksetzen", damit die App den Dateibestand vergleicht und den Beleg schreibt.
   **Das ist um 16:23–16:39 UTC zum ersten Mal teuer geworden:** für 106 Dateien kam der
   Beleg, für die übrigen **503** kam er nie — nach der 600-s-Schonfrist hat der Uploader
   sie alle aus dem Archiv zurückgelegt (~4,6 GB, gemessen; §6). `healReceiptFromDisk()`
   entscheidet zwar über den Bestand und nicht über den Bildschirm, aber heilen kann er
   nur, was er noch auf dem Gerät findet: wenn das Telefon das Batch-Verzeichnis geleert
   hat, bevor die Sicherung durch war, ist der Bestand weg und der Beleg kann ihn nicht
   mehr melden.
   **Neue offene Frage, dein Urteil:** was soll der Uploader mit einer Handreichung, deren
   Kopien am Stück verschwinden und für die nach der Schonfrist kein Beleg da ist? Heute:
   still aus dem Archiv nachlegen (§6, 503×). Alternativen: (a) Schonfrist **rauf** auf
   z. B. 30–60 min, (b) nach der Schonfrist den **Beleg erzwingen** statt nachlegen
   (ein `refusedPaths`-ähnliches Urteil „Verzeichnis vom Telefon geleert, ohne
   Freigabebeleg" → `blocked.csv`, Archiv bleibt, keine Doppel-Last für Fotos), oder
   (c) nachlegen, aber die Datei **einmal** als „zweite Handreichung" zählen, damit der
   dritte Durchlauf nicht nochmal 4 GB nachschiebt. Meine Empfehlung: **(b) plus (c)** —
   Nachlegen ist bei 5-GiB-Batches die teuerste Antwort auf ein Telefon, das schon
   geleert hat, und ohne Zähler läuft die Pipeline in genau dem Loop, der Fotos' Queue
   jedes Mal neu füllt.
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
- **Die Handreichungsordner kann man auf der NAS direkt messen** (SSH mit
  `-i ~/.ssh/id_ed25519_zimaos`): `/DATA/AppData/resilio-sync/data/pixelsync/staging/Batches`
  — `ls -1 | wc -l` und `du -sh` je Ordner. Das ist die einzige Instanz, die zwischen
  „Beleg gebucht" und „Kopie wirklich weg" unterscheiden kann. Zähler-Plauschregel:
  Einträge je Ordner = Dateien + 2 Marker (`_batch-manifest.json`, `_batch-ready.txt`).
- **`docker logs resilio-sync` beweist keine Löschung.** Die Zeilen
  `TF[…][/pfad]: check can delete: fs_refs = 0` und `TF[…][/pfad]: deleted` sind die
  **Wegnahme interner Transfer-Objekte**, kein `unlink` auf der Platte — sie erscheinen
  Minuten, nachdem ein Transfer fertig ist, und zwar für Dateien, die unverändert
  dastehen. Ich hätte darauf fast gebaut: 16:24 „40 deleted" im gerade gelegten Batch
  `20261007-162349`, und derselbe Ordner hat um 16:47 wieder 40 Einträge. `OnNotifyFileDeleted`
  (inotify) taucht im Log **0×** auf — wer löschen will, muss die Ordner selbst zählen.
- `apply_setup()` übernimmt jetzt die gespeicherte Konfiguration als Basis und ändert
  nur die sichtbaren Felder. Versteckte Werte wie `ReserveGiB`, `KeepAwake` und
  `RequireUnlocked` bleiben erhalten.
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

## 11. Docker-Wächter am 2026-10-12

Live geprüft nach Deploy von **3.3.20**, ca. 20:09 CEST: Server, Watcher und der neue
Dienst `photos-watchdog` laufen aus demselben Image, unprivilegiert mit UID/GID 1000.
Der Mac-LaunchAgent, seine lokalen Zustandsdateien und sein Installer wurden entfernt.
Status-API und Web-UI melden den unerreichbaren Pixel korrekt als `offline`. Ein
Prozess-Wiederanlauf auf dem Pixel ist bis zur Wiederherstellung von WLAN-ADB und
Bestätigung des eigenen NAS-Schlüssels nicht live geprüft. Keine Geräte-Neustarts.

Register nach dem Deploy: Katalog 178.104, abgeschlossen 672, staged 277, blocked 831,
unverified 300 (davon 0 retry-bereit). Vorher waren 1.131 blockiert; 300 frühere
Absage-Einträge wurden durch die bereits in 3.3.19 enthaltene Migration nach
`unverified.csv` verschoben. Das ist keine neue Erfolgsbuchung. Archiv-Kopien bleiben.
Der aktive Altbestand-Mount `/media/Data_1/Pictures:/data/archive/Altbestand:ro`
ist erhalten (live `RW=false`). Ledger und vorherige Compose-Datei liegen vor dem
Deploy gesichert unter `/DATA/AppData/pixel-photo-uploader/Archiv/state-vor-3.3.20-*.zip`.

## 12. Resilio-Papierkorb (`.sync/Archive`) und Speichererschöpfung (`ENOSPC`) am 2026-10-14

Messung am 2026-10-14, 16:03 CEST auf dem Upload-Pixel `FA69M0305152`:

- **Befund:** Der interne Speicher (`/data`) war mit 24 GiB zu **100 % voll** (exakt 504 KB frei).
- **Verursacher:** `/storage/emulated/0/DCIM/PixelSync/.sync/Archive` belegte **15,65 GiB**
  mit 22 alten Batches (`20261013-*` bis `20261014-*`).
- **Mechanismus:** Resilio Sync verschiebt serverseitig gelöschte Staging-Dateien standardmäßig
  in seinen internen Papierkorb `.sync/Archive` (Standard-Haltezeit 30 Tage). Da das Archiv
  auf der ZimaOS die eigentliche Sicherung hält und Staging-Dateien nach erfolgreicher
  Abrechnung auf dem Telefon wertlos sind, führte das nach wenigen 5-GiB-Batches zum
  vollständigen Überlauf des 24-GiB-Telefonspeichers.
- **Fehlerkette:**
  1. Batch `20261014-094055` (5,0 GiB / 922 Dateien) brach beim Resilio-Empfang bei Datei 585
     mit `ENOSPC` (No space left on device) ab.
  2. `MediaFolderScanner.completeBatch()` verlangt die exakte Datei- und Bytezahl aus
     `_batch-manifest.json` (922 Dateien, 5.368.707.476 Bytes). Der unvollständige Batch wurde
     daher ignoriert (`visibleFiles = 0`).
  3. Companion meldete dauerhaft: `Bereit – warte auf neue Fotos`.
  4. Server wartete auf den Rückbeleg der 922 Dateien und stellte keine neuen Batches bereit.
  5. Android zeigte System-Warnungen („Storage space running out“) und blockierte den Bildschirm
     mit `DeletionHelperActivity`.
  6. Parallel war ADB über Wi-Fi nach einem Neustart nicht aktiv, wodurch `photos-watchdog`
     auf ZimaOS keine Messung vornehmen konnte (`offline`).
- **Konzept-Integration:**
  1. **Companion 1.2.9:** `BackupMonitorService` leert den Inhalt von `.sync/Archive`
     über `ResilioArchiveCleaner.purge()` in jedem Überwachungsdurchlauf (`tick()`) automatisch.
     Damit sammelt sich kein Papierkorb mehr an, ohne dass manuelle Eingriffe in Resilio Sync nötig sind.
  2. **Speicherfreigabe:** Durch die Bereinigung von `.sync/Archive` wurden 15 GiB sofort frei
     (Speicherbelegung sank von 100 % auf 39 %).
  3. **Wiederanlauf:** Resilio Sync synchronisierte die restlichen Dateien von `20261014-094055`
     vollständig nach (924 Dateien, 5,25 GiB).
  4. **WLAN-ADB:** `adb tcpip 5555` reaktiviert und ZimaOS-Schlüssel dauerhaft auf dem Pixel bestätigt.

## 13. Stagnation durch unvollständigen Upload / nicht sicherbare Elemente („4 items can't be backed up“) und Dialog-Speicherleck am 2026-10-19

Messung am 2026-10-19, 14:30 CEST auf dem Upload-Pixel `FA69M0305152` und ZimaOS (`192.168.178.162`):

- **Symptom:** Statusseite meldet `0,00 GiB in den letzten 24 h`. Batch `20261017-004229` (474 Dateien / 5,0 GiB) blockierte seit 59 Stunden (seit Samstag 17.10. 02:53 CEST).
- **Befund:**
  1. Google Fotos hing bei „Getting ready to back up • 52 items left to back up“ mit dem Hinweis „4 items can’t be backed up“.
  2. Durch das permanent geöffnete Profil-Bottom-Sheet geriet Google Fotos in einen massiven GC-Thrash / Speicherleck: Dalvik-Heap war mit 280 MB von 291 MB am Limit, der Prozess brannte über 5.600 CPU-Minuten mit 150 % CPU-Dauerlast weg.
  3. Der ADB-Watchdog startete Google Fotos um 03:25 CEST einmal neu, ging nach 1 h Cooldown in `alert` und verharrte danach passiv (keine Reboots ohne Freigabe).
  4. Companion interpretierte den Text „Getting ready to back up“ als aktive Sicherung (`BACKUP_ACTIVE_NEEDLES`) und setzte seinen Stillstands-Timer endlos zurück.
  5. Der Server wartete die vollen 72 Stunden `BackupTimeoutHours` ab.
- **Konzeptverbesserung & Lösung:**
  1. **Dialog-Schutz im Companion (1.2.12):** Wenn Google Fotos aktiv sichert (`BACKUP_ACTIVE_NEEDLES`), schließt Companion das Profil-Sheet sofort via `performGlobalAction(GLOBAL_ACTION_BACK)`. Google Fotos verbleibt in der Hauptansicht mit ~2 % CPU und gesundem Heap (~20 MB).
  2. **Fortschritts- und Stillstandserkennung im Companion (1.2.12):**
     - Companion liest die Zahl der verbleibenden Elemente (`remaining`) aus dem Bildschirmtext.
     - Sinkt die Zahl für 20 Minuten (`BACKUP_STALL_MILLIS`) nicht, wird ein Sicherungsstillstand diagnostiziert.
     - Werden nicht sicherbare Elemente gemeldet („4 items can’t be backed up“ / `FAILED_ITEMS_NEEDLES`, inkl. typografischer Apostrophe `\u2019`), verkürzt sich die Stillstands-Schwelle auf 5 Minuten (`FAILED_ITEMS_STALL_MILLIS`).
     - Bei Stillstand erzwingt Companion über `openFreeUp()` die Freigabe: Alle tatsächlich in Google Fotos hochgeladenen Dateien werden vom Gerät gelöscht und als Erfolgsbeleg via `claimFreedFiles()` an den Server gemeldet. Verweigerte Dateien meldet Companion nach der 2. Runde als unbestätigt (`pendingReceiptRefused`).
  3. **Vorzeitiger Watchdog-Timeout auf dem Server (3.3.22):**
     - `photos_watchdog` erfasst `alert_since`.
     - `expire_staged()` prüft den Watchdog-Status: Steht der Watchdog seit >= 3 Stunden auf `alert`, werden Handreichungen nach 3 Stunden vorzeitig freigegeben und wandern zur späteren Prüfung in 0,5-GiB-Portionen nach `unverified.csv` (statt 72 Stunden die Queue zu blockieren).

## 14. Ursache der 0,00 GiB / 24 h und 11.959 fälschlich unbestätigten Dateien am 2026-10-19

Messung am 2026-10-19, 19:30 CEST auf dem Upload-Pixel `FA69M0305152` und ZimaOS (`192.168.178.162`):

- **Symptom:** Statusseite meldete `0,00 GiB in den letzten 24 h`, 11.959 Dateien standen in `unverified.csv` (davon 9.453 retry-fällig). Keine Datei schloss erfolgreich ab.
- **Vollständige Fehlerkette (aufgedeckt & live nachgewiesen):**
  1. **MediaStore-Geisterakkumulation:** Wenn Resilio Sync vom Server freigegebene Batches auf dem Dateisystem löschte, blieben 9.534 verwaiste Zeilen in `content://media/external/images/media` und `video/media` zurück. Google Fotos verharrte 24/7 in „Preparing backup • Scanning your photo library“.
  2. **Fehlalarm durch Google-Fotos-Lebenszeit-Karte:** Auf der Startseite blendete Google Fotos eine ausklappbare Promo-Karte ein: `Backup complete • 331,459 photos backed up • dismiss` (die Gesamtzahl des Cloud-Kontos, nicht des aktuellen Batches!).
  3. **Vorzeitige Überbrückung der Karenzzeit:** Suchbegriffe wie `preparing backup` oder `synchronis` standen in `BACKUP_ACTIVE_NEEDLES`. Dadurch setzte Companion `sawActiveBackup = true`, wodurch die 5-Minuten-Schonfrist `GRACE_MILLIS` sofort umgangen wurde.
  4. **Falsch-Abschluss & 2-Runden-Absagefalle:**
     - Companion las `Backup complete` aus der Lebenszeit-Karte, zählte Streak 2/2 und öffnete nach wenigen Sekunden „Speicherplatz freigeben“.
     - Da der 5-GiB-Batch erst wenige Sekunden auf dem Pixel lag und noch gar nicht hochgeladen war, meldete Google Fotos logischerweise „Nichts freizugeben“ (Nothing to free up).
     - Companion wertete das als Runde 1, wartete 15 Minuten, las erneut die Lebenszeit-Karte, öffnete erneut „Speicherplatz freigeben“ -> Runde 2!
     - Nach nur 2 Runden (30 Minuten statt der für 5 GiB benötigten ~5 Stunden) deklarierte Companion den gesunden Batch als verweigert (`pendingReceiptRefused`)!
     - Server buchte alle ~500 Dateien nach `unverified.csv` mit 24 h Wartezeit und löschte den Batch via Resilio.
     - Resilio hinterließ weitere ~500 MediaStore-Geister. Dieser Zyklus wiederholte sich über Tage, bis 11.959 Dateien in `unverified.csv` strandeten und `completed_bytes_24h` auf 0,00 GiB sank.
- **Konzeptverbesserungen & Lösungen:**
  1. **Automatisierte MediaStore-Bereinigung (`MediaStoreCleaner`):** Companion bereinigt verwaiste Einträge in `Images.Media` und `Video.Media` periodisch (alle 60 s) sowie direkt nach jeder Freigabe (`verifyCleanup()` und `healReceiptFromDisk()`). Google Fotos scannt wieder ohne Verzögerung.
  2. **Filterung von Header-Karten & Lebenszeit-Zählern:**
     - `collect()` markiert Knoten innerhalb von `photos_home_header_expansion_view`.
     - `isLifetimeSummary()` schließt Kontostände mit Tausendertrennern (z. B. `331,459 photos backed up`) aus der Statusprüfung aus.
     - `collapseHeaderCardIfExpanded()` schließt/dismissed die Promo-Karte automatisch.
     - Das mehrdeutige Wort `backed up` wurde aus `BACKUP_COMPLETE_NEEDLES` entfernt.
  3. **Trennung von Vorbereitung und echtem Dateitransfer:**
     - `BACKUP_PREPARING_NEEDLES` (`preparing backup`, `scanning your photo library`, `synchronis`) aktualisieren die Aktivität und verhindern Stillstands-Fehlalarme, setzen aber **nicht** `sawActiveBackup = true`.
     - Nur `BACKUP_ACTIVE_NEEDLES` (`backing up`, `uploading`, `items left`) weisen tatsächlichen Transfer nach.
  4. **Entschärfung von „Nichts freizugeben“ (`confirmFreeUp`):**
     - „Nichts freizugeben“ wird nur dann als Verweigerung gewertet, wenn Companion tatsächlich aus einem zweifach bestätigten Sicherungsabschluss (`completeStreak >= 2`) kam.
     - Kam die Navigation aus der Stillstandserkennung oder vor dem Abschluss, kehrt Companion sofort nach `WAIT_BACKUP` zurück und gibt Google Fotos Zeit für den Upload.
     - Nach jeder Absage-Runde wird `completeStreak` auf 0 zurückgesetzt, sodass vor einem erneuten Versuch ein frischer Abschluss nachgewiesen werden muss.
  5. **Bereinigung der 11.959 Falsch-Unbestätigten auf ZimaOS:**
     - `unverified.csv` wurde auf ZimaOS gesichert (`unverified.csv.bak-20261019`) und geleert.
     - Alle 11.959 Dateien stehen vollständig in `catalog.csv` und werden nun in regulären 5-GiB-Batches ohne 24-h-Drosselung zügig hochgeladen.
- **Messergebnis nach Deploy (Companion 1.2.13, Server 3.3.22):**
  - Unmittelbarer Upload-Wiederanlauf: 218 Dateien (1,63 GiB) in den letzten 24 h erfolgreich gesichert (`completed_bytes_24h = 1.630.881.405`).
  - Google Fotos und Companion arbeiten stabil im Zyklus; nächste 556 Dateien befinden sich im regulären Upload-Prozess.

## 15. Codeprüfung und Korrekturen vom 2026-10-21 (kein Live-Messstand)

Arbeitsstand Server 3.3.23 / Companion 1.2.14, noch kein Deploy-Nachweis:

- Watchdog: Fortschritt beendet `alert` und löscht `alert_since`, ohne einen zweiten Neustart desselben beobachteten Batches zu erlauben. Messlücken unterbrechen den Alarmzeitraum.
- Vorzeitige Freigabe: nur für passende `batchIds`, frisches `observedAt` (maximal 150 Sekunden) und mindestens drei Stunden nachgewiesenen Alarm. Alte Statusdateien können keine neuen Batches vorzeitig freigeben. Der normale Timeout und die Zuordnung von Retry-Dateien zu `unverified.csv` bleiben erhalten.
- Companion: Wiederholte Aktivitäts-/Vorbereitungstexte verschieben `lastProgressAt` nicht mehr. Freigabeprüfungen verwenden eine getrennte Wartefrist.
- Erfolgsbeleg: nur nach einem von der App bestätigten Freigabeklick und nur für zuvor vorhandene, danach fehlende Dateien. Ohne gespeicherte Freigabeliste kein Nachbuchen anhand bloßer Abwesenheit. Der Server akzeptiert weiterhin nur Rückbelege zu noch vorgemerkten Handreichungen.
- Teilfreigaben behalten Restdateien und ursprünglichen Timeout-Beginn; Nachlieferungen setzen diesen Beginn nicht zurück.

Diese Aussagen beschreiben Code und lokale Regressionen, keine neue Messung von Latenz, Registerbelegung oder Durchsatz.

Lokale Prüfung: 136 Python-Tests bestanden. Nach dem Gradle-Lauf im lokalen Terminal sind auch alle 24 Android-JUnit-Tests erfolgreich (0 Fehler), die Debug-APK ist als Companion 1.2.14 / versionCode 19 erzeugt. Lint meldet 0 Fehler und 18 Warnungen. Die erzeugten Testberichte, der Lint-Bericht und die APK-Metadaten wurden geprüft. Deployment und Liveprüfung stehen noch aus.

Deployment-Versuch in dieser Sitzung: SSH zu `192.168.178.162:22` und der lokale ADB-Socket werden mit `Operation not permitted` abgewiesen. Es wurden keine NAS-Dienste oder Pixel-Apps verändert. `scripts/deploy.py` bereitet den Aufruf aus dem lokalen Terminal vor: bestehende Compose-Konfiguration mit allen Mounts erhalten, Remote-Image bauen, gestoppten Serverzustand sichern, APK mit App-Daten installieren und Dienste wieder starten. Drei zusätzliche lokale Tests prüfen die Konfigurationserhaltung und den Umgang mit pausierter Überwachung; Remote-Ausführung steht aus.

Erster Terminal-Aufruf: Die NAS ist per SSH erreichbar, aber `docker compose version` scheitert am fehlenden CLI-Plugin. Der Abbruch lag vor Änderungen an NAS-Diensten und Pixel. Das Deploy-Skript erkennt jetzt alternativ `docker-compose` und prüft vorab, ob `up --pull never` unterstützt wird; Start und Wiederherstellung verwenden dieselben kompatiblen Optionen. Neun lokale Deployment-Tests bestanden. Der nächste Terminal-Aufruf muss die tatsächliche Compose-Variante und das Deployment noch bestätigen.

Zweiter Terminal-Aufruf: Auch `docker-compose` ist nicht im SSH-Pfad verfügbar; erneut Abbruch vor Änderungen an Diensten und Pixel. Das Skript sucht nun zusätzlich in den vier üblichen Docker-Plugin-Verzeichnissen. Falls Compose fehlt, lädt es auf dem Mac eine fixierte Linux-Datei (v2.40.3, x86_64/aarch64), prüft den hinterlegten SHA-256-Hash und überträgt sie nach `/DATA/AppData/pixel-photo-uploader/deploy-tools/`. Vor Ausführung erfolgt eine zweite Hash-Prüfung auf der NAS. Bestehende geprüfte Dateien werden wiederverwendet. 15 lokale Deployment-Tests bestanden, einschließlich defekter Downloads und nicht unterstützter Architekturen; keine Netzwerkzugriffe in den Tests. Aufruf weiterhin auf dem Mac, Remote-Deployment weiterhin unbestätigt.
