# Google-Fotos-Aussetzer: integrierter Docker-Wächter

Ab Uploader 3.3.20 enthält dasselbe Docker-Image auch ADB und den Google-Fotos-Wächter.
Compose startet ihn als eigenständigen Dienst `photos-watchdog`, damit ADB-Wartezeiten
weder Fotoimport noch Web-UI blockieren. Der Mac-Dienst und sein Installer sind entfernt.

## Die drei Regeln

1. Alle 60 Sekunden misst der Wächter die WLAN-Sendebytes **der Google-Fotos-UID**.
   Resilio-Verkehr, Scan-Text und CPU-Auslastung zählen nicht. Companion 1.2.8 ergänzt
   den erkannten Restzähler (maximal 120 Sekunden alt). Fortschritt: mindestens 8 MiB
   kumulierter Google-Fotos-Sendeverkehr oder ein sinkender Restzähler. Sendebytes zeigen
   Aktivität, sind aber kein Beleg für erfolgreich gesicherte Dateien.
2. Nach 30 Minuten ohne solchen Fortschritt beendet der Wächter **nur Google Fotos**
   und öffnet es einmal neu. Das Budget gilt pro Batch und überlebt Prozessneustarts.
   Batchdateien, Rückbelege, MediaStore und Timeout-Beginn bleiben erhalten.
3. Bei weiteren 30 Minuten Stillstand beginnt eine Stunde Wartezeit. Fortschritt hebt
   die Warnung auf, gibt aber keinen zweiten Neustart desselben Batch frei. Bleibt der
   Fortschritt aus, folgt eine dauerhafte Warnung im Web-UI und Containerstatus.
   Companion 1.2.8 zeigt sie außerdem auf dem Pixel. Ein neuer Batch erhält ein neues Budget.

Geprüft werden Modell **Pixel** und Seriennummer **FA69M0305152**. Pausierte
Überwachung, ausstehende Belege, Freigabedialoge und das 72-Stunden-Limit werden
respektiert. Verbindungsabbrüche, Host-Schlaf und Uhrsprünge gelten nicht als Stillstand.

**Keine Geräteneustarts, kein Cache-/Datenlöschen, kein Root auf dem Pixel.** Dieses
Pixel braucht eine spezielle Kabel-/Stromversorgung; Reboot nur nach ausdrücklicher Freigabe.

## ZimaOS-Einrichtung

```bash
docker build -t pixel-photo-uploader:3.3.20 .
docker compose -f docker-compose.yml up -d
```

Alle Dienste laufen als UID/GID 1000. Der Ordner
`/DATA/AppData/pixel-photo-uploader/watchdog-adb` muss UID 1000 gehören und Modus 700
haben. Er wird nach `/home/ppu/.android` gemountet und hält den eigenen NAS-ADB-Schlüssel.
Der private Mac-Schlüssel wird nicht kopiert. Das Pixel muss diesen NAS-Schlüssel
beim ersten Verbinden ausdrücklich bestätigen. In Compose steht die zuletzt bekannte
DHCP-Adresse `192.168.178.53:5555`; bei IP-Wechsel den Wert aktualisieren.

Android 10 braucht nach einem Geräteneustart eventuell erneut USB und `adb tcpip 5555`.
Ohne ADB-Verbindung kann der Wächter diesen Zustand nicht reparieren. Er meldet dann
„Upload-Pixel nicht messbar“ und greift nicht ein. Der Upload durch Google Fotos kann
unabhängig davon weiterlaufen. Companion 1.2.8 ist für Restzähler und Pixel-Warnung
gebaut, aber noch nicht auf dem derzeit unerreichbaren Pixel installiert; die
Sendeverkehrsmessung und Web-Warnung funktionieren bereits mit 1.2.7.

## Status und Log

Web-UI: Abschnitt „Google-Fotos-Wächter“. API: `GET /api/photos-watchdog`.
Nach 150 Sekunden ohne neue Meldung zeigt die API einen veralteten Zustand an.

```bash
docker compose -f docker-compose.yml logs --tail=10 photos-watchdog
cat /DATA/AppData/pixel-photo-uploader/state/photos-watchdog/photos-watchdog-status.json
```

Der Zustand liegt unter `state_root()/photos-watchdog/`. Das Neustartbudget nicht
löschen, um denselben Batch nicht erneut neu zu starten. ADB lauscht nur innerhalb
des Containers; kein Host-Port, kein privilegierter Container, kein Docker-Socket-Mount.

## Tests

```bash
.venv/bin/python -m pytest
cd android/PixelPhotoCompanion
./gradlew testDebugUnitTest assembleDebug lintDebug
```

Tests simulieren Fortschritt, Stillstand, einen Neustart, eine Stunde Wartezeit,
Prozessabsturz, Offline-Zeit, falsche Zielgeräte, Pausen und Freigabephasen. Kein Netzwerk.
Der Live-Wiederanlauftest benötigt weiterhin eine ADB-Verbindung zum Pixel.
