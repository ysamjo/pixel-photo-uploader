# Pixel Photo Companion 1.2.4

Android-Begleit-App für ein Google Pixel der ersten Generation, das als dediziertes Uploadgerät für Google Fotos verwendet wird. Die App benötigt kein Root.

## Was die App macht

- überwacht standardmäßig `DCIM/PixelSync`: Batch-Ordner unter `staging/`
  (nur vollständig — `_batch-manifest.json` + `_batch-ready.txt` mit passender
  Datei- und Bytezahl), `control/` und Resilio-Reste (`.sync`, `.!sync`) werden
  ignoriert;
- akzeptiert Medien erst, wenn Größe und Änderungszeit zwei Minuten stabil sind;
- meldet fertige Dateien beim Android-Medienscanner an;
- öffnet Google Fotos und liest den sichtbaren Sicherungsstatus über einen Bedienungshilfedienst;
- verlangt zweimal „Sicherung abgeschlossen“ mit mindestens 45 Sekunden Abstand;
- stoppt bei Sicherungsfehlern, gesperrtem Pixel oder unbekannter Google-Fotos-Oberfläche;
- öffnet Google Fotos selbst, wenn ein Schritt die Oberfläche braucht (der Bildschirm muss dabei an und entsperrt sein);
- öffnet ausschließlich ein eindeutig erkanntes „Speicherplatz freigeben” und dessen Bestätigungsdialog;
- akzeptiert im Bestätigungsdialog nur eine kurze Knopfbeschriftung mit Mengen- oder Zahlenangabe, die nicht „Abbrechen“ oder „Später“ heißt, kein Fragezeichen enthält und deren Element tatsächlich klickbar ist; die Knöpfe der installierten Google-Fotos-Fassung heißen „Vom Gerät löschen“ (auch mit Zähler), zusätzlich werden „… freigeben“, „… entfernen“ und die englischen Texte erkannt;
- bleibt auf einem Bildschirm ohne Bestätigungsdialog nicht stehen: sie geht zurück, sucht den Menüpunkt neu (sechs Versuche im Fünf-Minuten-Abstand) und meldet erst danach den Fehlerzustand mit den gelesenen Bildschirmtexten (vollständig im Protokoll);
- vergleicht den realen Dateibestand und zählt nur tatsächlich entfernte Dateien als abgeschlossen — maßgeblich ist der Bestand, nicht wer den Knopf gedrückt hat;
- hält eine Absage auseinander: meldet Google Fotos zweimal „Nichts freizugeben“, übergibt die Liste als Absage-Rückbeleg, bietet dieselben Inhalte nicht erneut an und verbucht ihre spätere Löschung nicht als Google-Freigabe — die gibt nämlich der Server selbst über Resilio frei;
- schreibt einen atomaren JSON-Rückbeleg in den Resilio-Kontrollordner, auch nach einer Teilfreigabe und auch dann, wenn die App vorher in einem Fehlerzustand stehen geblieben ist;
- spiegelt ihr Protokoll zusätzlich nach `<Kontrollordner>/companion-log.txt`, damit der Server im Web-UI unter „Pixel meldet" zeigt, worauf die Automatik wartet — ohne Kabel;
- läuft als sichtbarer Vordergrunddienst und startet nach einem Pixel-Neustart wieder, wenn er vorher aktiv war; auch nach einem App-Update weckt die Bedienungshilfe die Überwachung selbst.

## Wichtige Sicherheitsgrenze

Google Fotos stellt keine offizielle Schnittstelle für den Uploadstatus oder „Speicherplatz freigeben“ bereit. Die App liest deshalb die sichtbare Google-Fotos-Oberfläche. Nach einem größeren Google-Fotos-Update kann eine Anpassung nötig sein.

„Speicherplatz freigeben“ kann **alle bereits gesicherten lokalen Medien auf dem Pixel** entfernen, nicht nur Medien in den überwachten Ordnern. Verwende die Automatik daher nur auf dem dedizierten Upload-Pixel. Die Originale auf dem Server und dem Haupthandy werden von dieser App nie verändert.

## Installation aus Android Studio

1. Aktuelles Android Studio auf dem Rechner installieren.
2. Diesen Ordner über **Open** als Projekt öffnen.
3. Falls angeboten, Android SDK Platform 35 installieren lassen.
4. Pixel per USB verbinden und USB-Debugging zulassen.
5. In Android Studio **Run** wählen oder über **Build → Build APK(s)** eine APK erzeugen.
6. Die App auf dem Pixel öffnen.

Das Projekt verwendet ausschließlich Android-System-APIs und keine externen App-Bibliotheken.

Ohne Android Studio genügt `./gradlew assembleDebug` im Projektordner; die APK liegt danach unter
`app/build/outputs/apk/debug/app-debug.apk` und kann wie jeder andere Ordnerinhalt über Resilio auf das Pixel.

## Einrichtung auf dem Pixel

1. **Dateizugriff erlauben** drücken und die Speicherberechtigung bestätigen.
2. **Bedienungshilfe öffnen** drücken und „Pixel Photo Companion“ aktivieren.
3. In Google Fotos Sicherung und **Originalqualität** aktivieren.
4. In Google Fotos die Sicherung für den Ordner `PixelSync` aktivieren (Gerätesicherungsordner).
5. In Resilio **genau einen Ordner** teilen: Pixel `/storage/emulated/0/DCIM/PixelSync`
   ↔ Server-Ordner `pixelsync` (ZimaOS: `/DATA/AppData/resilio-sync/data/pixelsync`,
   weil Resilio nur Ordner seiner Freigabe-Wurzel `sync` teilen kann).
   Bidirektional, mit vollständiger Synchronisierung.
6. In der App die vorbelegten Ordner prüfen: Überwachung auf
   `/storage/emulated/0/DCIM/PixelSync`, Kontrollordner auf
   `/storage/emulated/0/DCIM/PixelSync/control`.
7. Auf dem Pixel **Overwrite any changed files ausschalten**, damit von Google Fotos
   lokal entfernte Dateien nicht erneut geladen werden.
8. Die Sicherheitsbestätigung in der App aktivieren.
9. Zunächst mit 20–50 Testfotos und einem Video testen.
10. **Überwachung starten** drücken.
11. Für den alleinigen Betrieb ohne Eingriff: Entwickleroptionen → **Bildschirm nicht ausschalten** (bleibt an, solange das Gerät am Laden hängt). Ohne das bleibt die Freigabe liegen, weil bei dunklem Bildschirm kein Fenster zu lesen und zu klicken ist.

## Zusammenspiel mit Server und Resilio

Der Server (Windows-Uploader, Umbrel- oder ZimaOS-App — für die Companion-App
ist das derselbe Vertrag) gibt ausschließlich **einen** Resilio-Ordner frei,
niemals die komplette Hauptbibliothek:

- Server: `pixelsync/` mit den Unterordnern `staging/Batches/` (der
  Uploader legt pro Batch genau einen Ordner mit `_batch-manifest.json` und
  `_batch-ready.txt` an) und `control/` (hier landen die `receipt-*.json`).
- Pixel: `/storage/emulated/0/DCIM/PixelSync` als einzige Freigabe empfangen;
  vollständige Synchronisierung verwenden.
- Haupthandy: Kameraordner als weitere Quelle freigeben (optional).
- Auf dem Pixel **Overwrite any changed files ausschalten**, damit von Google Fotos lokal entfernte Dateien nicht erneut geladen werden.

Keinen zweiten Google-Fotos-Automatiklauf (z. B. den ADB-Dauerbetrieb) gleichzeitig laufen lassen. Sonst bedienen zwei Stellen parallel dieselbe Google-Fotos-Oberfläche. Die Companion-App ersetzt die Google-Fotos-Steuerung; Resilio ersetzt dabei den Transport zum Pixel.

Ohne Rückbeleg gibt der Server die Handreichung nach `BackupTimeoutHours` (Standard 72 h) auf. Die App sieht das als lokal entfernte Datei und schreibt einen Rückbeleg darüber; der Server ignoriert ihn, weil der Eintrag dann schon in `blocked.csv` steht und nicht mehr vorgemerkt ist. Der Zähler „abgeschlossen" auf dem Telefon zählt diese Freigaben mit — die Abrechnung auf dem Server stimmt trotzdem.

Nach einem Neustart muss das Pixel einmal manuell entsperrt werden. Die App speichert keine PIN und entsperrt das Gerät nicht selbst.

## Statusphasen

- **Ordnerüberwachung:** Wartet auf stabile Mediendateien.
- **Warte auf Google-Fotos-Sicherung:** Liest Sicherungsstatus und Fehlertexte.
- **Öffnet Speicherplatz freigeben:** Sucht den eindeutigen Menüpunkt.
- **Prüft Freigabebestätigung:** Klickt nur einen eindeutig erkannten lokalen Freigabedialog.
- **Prüft entfernte Dateien:** Vergleicht die vorher gespeicherten Pfade mit dem Bestand danach.
- **Fehler:** Automatik ist angehalten; es wird nichts freigegeben. Nach **Zurücksetzen** in der App läuft sie weiter.

## Änderungen in 1.2.4

- **Die Überwachung steht nach einem App-Update wieder auf.** `adb install -r` beendet
  die App per Force-Stop, und der automatische Neustart des Vordergrunddienstes
  überlebt das nicht: der Dienst bleibt ohne Prozess gemeldet, der 30-Sekunden-Tick
  läuft nie wieder an. Die App zeigte dann nur „Pausiert", auf dem Server fiel nichts
  auf und die Queue stand still. Die Bedienungshilfe ist an das System gebunden und
  lebt, solange sie eingeschaltet ist — sie prüft deshalb alle 60 Sekunden und weckt
  die Überwachung, wenn sie fehlt. Wer die Überwachung selbst pausiert hat, wird nicht
  geweckt. Jeder Weckruf steht als eigene Zeile im Protokoll.

Geprüft auf dem Upload-Pixel `FA69M0305152`: Nach der Installation meldete das
Protokoll „16:36:01 Bedienungshilfe verbunden." und „16:36:01 Überwachung lief nicht –
wird neu gestartet.", `dumpsys` zeigte einen lebenden Prozess, und die
Herzenszeile rückte wieder exakt alle 30 Sekunden weiter.

## Änderungen in 1.2.0

Anpassung an das Ein-Ordner-Prinzip, das Server (Windows, Umbrel, ZimaOS) und
App jetzt gemeinsam sprechen — für die ZimaOS-Paarung ist das die
Installationsgrundlage:

- Standard-Überwachung ist nur noch `/storage/emulated/0/DCIM/PixelSync`
  (vorher zusätzlich die veralteten `ResilioInbox`- und `Camera/PixelUploader`-Pfade).
  Bestehende Installationen behalten ihre gespeicherten Ordner; nur frische
  Installationen starten mit dem einen Ordner.
- Abgleich-Cache: Der volle Baumdurchlauf pro Bedienungshilfen-Runde wird 20 s
  gecacht, Ereignis-Bursts während der Sicherung gedrosselt (5-s-Poll reicht) —
  weniger Ruckeln und Akku auf dem Pixel 1, Dialogphasen bleiben ereignisgetreu.
- Die Einrichtung oben beschreibt wieder genau eine Resilio-Freigabe mit den
  Unterordnern `staging/` und `control/` statt zweier getrennter Freigaben.
- Am Übertragungsvertrag ändert sich nichts: `_batch-manifest.json`
  (`fileCount`, `bytes`) + `_batch-ready.txt`, Rückbelege `receipt-*.json`
  mit `removedPaths`, Protokollspiegel `companion-log.txt`.
- **Google-Fotos-Erkennung gehärtet** (zuletzt wurden Felder nicht gefunden):
  Abschluss wird vor Aktivität geprüft (ein „Elemente“-Wort im Abschlussblatt
  vertagte sonst den Abschluss endlos); Kataloge erweitert um „wird
  hochgeladen“, „werden gesichert“, „Elemente“, „alle Elemente/Medien
  gesichert“, „Sicherung pausiert/aus“, „fehlgeschlagen“, „offline/keine
  Verbindung“ plus englische Gegenstücke, Kurzform „Speicher freigeben“ und
  „Jetzt freigeben/löschen“-Knöpfe; Tooltips werden mitgelesen.
  Systemdialoge („Zulassen“) werden gelesen statt übergangen — vorher war die
  Automatik blind, sobald ein Systemfenster über Fotos lag.
  Stillstand ist jetzt ein Befund: Zeigt Fotos 30 Minuten lang weder Aktivität
  noch Abschluss (oder fehlt der Menüpunkt genauso lange), hält die App mit
  den gelesenen Bildschirmtexten an, statt bis zum 72-Stunden-Limit lautlos
  das Profil an- und auszuklicken.
- **Ressourcen-IDs statt nur Wortlaut:** Jeder Knoten merkt sich seine View-ID;
  der Menüpunkt wird zuerst über ID-Bestandteile (`free_up`/`freeup`) gesucht,
  der Bestätigungsknopf über den Framework-Knopf `android:id/button1` — aber
  nur im verifizierten Freigabe-Dialog (kurzer Titelknoten mit Fragezeichen und
  Freigabe-Semantik, z. B. „Vom Gerät löschen?“ — der exakte Wortlaut ist egal).
  Wortlaut bleibt als Rückfall, weil auf dem Pixel wahrscheinlich eine ältere
  Fotos-Fassung läuft, deren IDs niemand kennt. Das Protokoll schreibt zu jedem
  Bildschirmtext die Kurz-ID (`[#…]`), damit künftige Brüche Pinnen statt Raten sind.

## Wenn Felder nicht gefunden werden

Im App-Protokoll (und in `control/companion-log.txt` auf dem Server) stehen
die Zeilen „Unbekannter Google-Fotos-Bildschirm … Bildschirmtexte: …“ und im
Fehlerfall „Zu melden: …“. Jeder Eintrag trägt seit 1.2.0 seine View-ID
(`[#button1]`, `[#free_up_space_button]` …): Eine ID aus dem Protokoll in die
Suchlisten übernehmen schlägt jeden geratenen Wortlaut. „keine lesbaren Texte“
dagegen heißt: Der Baum ist leer (WebView/Canvas oder gesperrtes Pixel), dann
liegt es nicht am Wortlaut.

## Änderungen in 1.1.2

Die Knopferkennung ist jetzt gegen die deutschen Sprachdateien der auf dem Upload-Pixel installierten Google-Fotos-Fassung geprüft, statt gegen vermutete Formulierungen. Drei Unterschiede sind aufgefallen und sind abgedeckt:

- Der Bestätigungsknopf heißt dort **„Vom Gerät löschen"** — auch mit angehängtem Zähler („Vom Gerät löschen (24)"). Die vorherigen Suchwörter kannten nur „entfernen".
- Der Menüpunkt erscheint als **„Gerätespeicherplatz freigeben"** und **„Speicherplatz auf dem Gerät freigeben"**. Das alte Suchwort mit „auf diesem Gerät" konnte daran vorbeilaufen.
- **„Du kannst keinen Speicherplatz freigeben"** ist ein Hinweis und kein Menüpunkt. Der Text enthält aber „Speicherplatz freigeben" und wurde bisher als erster Treffer genommen — die App hat dann ins Leere geklickt und den echten Menüpunkt nie erreicht. Der Hinweis wird jetzt übersprungen, und als Menüpunkt zählt nur noch, was tatsächlich klickbar ist.

Zusätzlich schließt jetzt ein Fragezeichen *irgendwo* im Text einen Knopfkandidaten aus. Die Titelzeile „Vom Gerät löschen?" kann zusammen mit dem Hinweissatz in einem gelesenen Knoten ankommen; „nur wenn der Text mit ? endet" hat dem nicht standgehalten.

Drei weitere Punkte waren für den laufenden Betrieb nötig, weil die Freigabe sonst per Hand erfolgen musste:

- **Google Fotos wird selbst geholt.** Die Automatik hat auf einen Bestätigungsdialog gewartet, den nie jemand geöffnet hatte: Nach einem Neustart oder Zurücksetzen steht das Pixel auf dem Startbildschirm, und ohne Google-Fotos-Fenster ist nichts zu lesen oder zu klicken. Jetzt holt die App Google Fotos selbst nach vorn, spätestens eine Runde vorher.
- **Der Dateibestand entscheidet, nicht der Klick.** Fehlende Batchdateien waren bisher ein Fehler („eine vorgemerkte Datei fehlt bereits"); jetzt sind sie der Beleg für eine gelungene Freigabe. Der Rückbeleg wird aus dem Bestand geschrieben — auch nach einer Teilfreigabe und auch dann, wenn die App vorher in einem Fehlerzustand stehen geblieben ist oder ein Mensch den Knopf gedrückt hat. Ohne diesen Schritt bliebe Windows auf einem Batch sitzen, dessen Dateien längst hochgeladen sind.
- **Ein verlorener Bildschirm ist kein Endzustand.** Statt nach zwei Minuten Wanduhr endgültig zu stoppen, geht die App zurück, sucht den Menüpunkt sechs Mal neu (Fünf-Minuten-Abstand) und meldet den Fehler erst danach. Über Nacht schläft der Bildschirm — das darf die Kette nicht dauerhaft anhalten.

Geprüft auf dem Upload-Pixel `FA69M0305152`: Ein Batch mit 891 Dateien blieb nach einer manuellen Freigabe im Fehlerzustand stehen, ohne je einen Rückbeleg geschrieben zu haben. Nach dem Update meldete die App „589 Dateien lokal freigegeben; Rückbeleg für Windows geschrieben. 302 Dateien blieben erhalten", und im Kontrollordner lag erstmals `receipt-…json` mit 589 Pfaden und `remainingCount: 302`.

## Änderungen in 1.1.1

Der Stillstand auf dem Freigabebildschirm hatte eine Ursache im Textvergleich: die Bestätigungs-Regex war eine Kette mit `|`, `String.matches()` prüft aber den gesamten Text. Dadurch passten alle Zweige hinter dem ersten nur auf exakte Beschriftungen, und der erste Treffer war fast immer ein langer Hinweissatz des Dialogs — ein Klick darauf landet bei einem beliebigen Container und tut nichts. Jetzt zählt nur eine kurze, klickbare Knopfbeschriftung; ohne solche bleibt die App nach zwei Minuten mit den sichtbaren Bildschirmtexten im Fehlerzustand stehen.

## Unterstützte Geräteversion

Minimum ist Android 8.0 (API 26). Das offizielle Android 10 des Pixel 1 wird unterstützt. Die App zielt absichtlich auf die klassische Speicherberechtigung, weil das dedizierte Pixel 1 offiziell nicht über Android 10 hinaus aktualisiert wurde.
