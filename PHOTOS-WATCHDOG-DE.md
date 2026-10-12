# Google-Fotos-Aussetzer: Mac-Wächter

Der Nutzer hat den Mac als Ausführungsort gewählt. Der Wächter läuft als
Benutzer-Hintergrunddienst, solange dieser Mac läuft. ADB muss mit dem Pixel 1
verbunden und autorisiert sein. Offline wird gemeldet, niemals durch Eingriffe behoben.

## Die drei Regeln

1. Alle 60 Sekunden misst der Wächter die WLAN-Sendebytes **der Google-Fotos-UID**.
   Resilio-Verkehr, Scan-Text und CPU-Auslastung zählen nicht. Companion 1.2.8 ergänzt
   den erkannten Restzähler (Deutsch/Englisch, maximal 120 Sekunden alt). Fortschritt:
   mindestens 8 MiB kumulierter Google-Fotos-Sendeverkehr oder ein sinkender Restzähler.
   Kleine Kontrollanfragen allein verhindern keinen Wiederanlauf. Sendebytes zeigen
   Aktivität, sind aber kein Beleg für erfolgreich gesicherte Dateien.
2. Nach 30 Minuten ohne solchen Fortschritt beendet der Wächter **nur Google Fotos**
   und öffnet es einmal neu. Das Budget gilt pro Batch und überlebt Prozessneustarts.
   Batchdateien, Rückbelege, MediaStore und Timeout-Beginn bleiben erhalten.
3. Bei weiteren 30 Minuten Stillstand beginnt eine Stunde Wartezeit. Fortschritt hebt
   diese Warnung auf, gibt aber keinen zweiten Neustart desselben Batch frei.
   Bleibt der Fortschritt aus, folgt eine dauerhafte Warnung in Status und Log sowie
   eine lokale Mac-Mitteilung. Companion 1.2.8 zeigt die Warnung außerdem auf dem Pixel.
   Ein neuer Batch erhält ein neues Neustartbudget.

Der Wächter prüft Modell **Pixel** und Seriennummer **FA69M0305152** vor Eingriffen.
Er ignoriert pausierte Überwachung, ausstehende Belege, Freigabedialoge und das
72-Stunden-Limit. Bei Messfehlern, ADB-Unterbrechungen, Host-Schlaf oder Uhrsprüngen
beginnt eine neue Beobachtungsfrist; Offline-Zeit ist kein belegter Stillstand.
Ein inzwischen gewechselter Batch wird vor einem Neustart nochmals abgeglichen.

**Geräteneustarts sind ausgeschlossen.** Kein Cache-/Datenlöschen, kein Root,
keine Änderung am Batch-Baum. Auf diesem Pixel funktionieren ADB und Stromversorgung
nur mit der passenden Kabelkombination; niemals ohne ausdrückliche Freigabe rebooten.

## Mac-Dienst einrichten

```bash
.venv/bin/python scripts/install-photos-watchdog-macos.py --device 192.168.178.53:5555
```

Der Benutzer-LaunchAgent `de.pixelphotouploader.photos-watchdog` startet bei Anmeldung
und nach einem Prozessabbruch erneut. Er arbeitet ohne sudo und ohne neue Android-
Berechtigungen. Der persistente Zustand verhindert zusätzliche Neustarts desselben Batch.
Die zuletzt bekannte DHCP-Adresse `192.168.178.53` ist keine feste Zusicherung.
Bei IP-Wechsel den Installer erneut mit der aktuellen Adresse ausführen.

Status und Log:

```bash
cat ~/.pixel-photo-uploader/photos-watchdog/photos-watchdog-status.json
 tail -n 10 ~/.pixel-photo-uploader/photos-watchdog/watchdog.log
launchctl print gui/$(id -u)/de.pixelphotouploader.photos-watchdog
```

Dienst stoppen:

```bash
launchctl bootout gui/$(id -u)/de.pixelphotouploader.photos-watchdog
```

Der Agent bleibt für die nächste Anmeldung gespeichert. Für dauerhaftes Abschalten
zusätzlich `~/Library/LaunchAgents/de.pixelphotouploader.photos-watchdog.plist` entfernen.
Das Neustartbudget nicht löschen, um denselben Batch nicht wiederholt neu zu starten.

Ein einmaliger lesender Check ohne Prozess-Neustartfreigabe:

```bash
.venv/bin/python -m app.photos_watchdog --adb /Users/family/.local/bin/adb --device 192.168.178.53:5555 --once
```

Nicht gleichzeitig mit einem laufenden Hintergrunddienst gegen denselben Zustandsordner
starten. Eine Dateisperre verhindert konkurrierende Instanzen.

## Companion 1.2.8

```bash
cd android/PixelPhotoCompanion
./gradlew testDebugUnitTest assembleDebug lintDebug
adb -s <Pixel-1-Transport> install -r app/build/outputs/apk/debug/app-debug.apk
adb -s <Pixel-1-Transport> shell am start -n de.pixelphotouploader.companion/.MainActivity
```

1.2.8 ist gebaut und getestet, aber noch nicht auf dem derzeit unerreichbaren Pixel
installiert. Mit 1.2.7 funktioniert die UID-Sendeverkehrsmessung bereits; Restzähler
und Warnungsanzeige auf dem Pixel erfordern 1.2.8. Die Mac-Warnung funktioniert unabhängig.

Android 10 braucht nach einem Geräteneustart eventuell erneut USB und `adb tcpip 5555`.
Der Wächter kann das nicht ohne vorhandene Verbindung reparieren. Die richtige
Kabel-/Stromversorgung verwenden; den laufenden Upload dafür nicht unterbrechen.

## Prüfung

```bash
.venv/bin/python -m pytest
cd android/PixelPhotoCompanion
./gradlew testDebugUnitTest assembleDebug lintDebug
```

Tests simulieren Fortschritt, Stillstand, einen Neustart, eine Stunde Wartezeit,
Prozessabsturz, Offline-Zeit, falsche Zielgeräte, Pausen und Freigabephasen. Kein Netzwerk.
Ein echter Wiederanlauftest auf dem Pixel steht bis zur erneuten ADB-Verbindung aus.

Die getrennten Abfragen `dumpsys netstats --poll` und `dumpsys netstats --full --uid`
entsprechen dem [Android-10-Quelltext](https://github.com/aosp-mirror/platform_frameworks_base/blob/android10-release/services/core/java/com/android/server/net/NetworkStatsService.java):
`--poll` aktualisiert die Messung, gibt aber noch keine UID-Historie aus.
