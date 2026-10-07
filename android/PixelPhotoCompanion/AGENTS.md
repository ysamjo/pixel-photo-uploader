# PixelPhotoCompanion

Android-Begleit-App (Android 10 / API 29) für das Google Pixel der 1. Generation als dediziertes Upload-Gerät für Google Fotos mit unbegrenztem Speicher in Originalqualität.

## Zielgerät & ADB-Deployment
- **Zielgerät**: Google Pixel 1 ("sailfish")
  - **Verbindung**: Keine feste IP (dynamisch via DHCP im WLAN oder per USB-Kabel).
  - **Zweck**: Exklusives Upload-Gerät — ausschließlich diese App wird hier installiert.
- **Paketname**: `de.pixelphotouploader.companion`
- **Architektur**:
  - Überwacht `DCIM/PixelSync` (Resilio-Freigabe `staging/Batches/` vom ZimaOS-Host).
  - Meldet Medien beim Android-Medienscanner an und steuert Google Fotos per Bedienungshilfedienst (`AccessibilityService`).
  - Bestätigt Uploads über Rückbeleg `receipt-*.json` in `control/`.

## Commands

```bash
# Debug-APK bauen
./gradlew assembleDebug

# Auf Pixel 1 via ADB installieren
adb install -r app/build/outputs/apk/debug/app-debug.apk

# App starten
adb shell am start -n de.pixelphotouploader.companion/.MainActivity
```

## Fallstricke

- **Ein APK-Update entlässt die Überwachung:** `adb install -r` beendet die App per
  Force-Stop, und der START_STICKY-Neustart von `BackupMonitorService` überlebt das —
  der Service-Record bleibt ohne Prozess hängen (`dumpsys activity services … | grep app=`
  zeigt `app=null`), der 30-Sekunden-Tick läuft nie wieder an. Die App meldet dann nur
  „Pausiert", auf der NAS fällt keine Fehlerzeile auf. Dagegen weckt
  `PhotosAccessibilityService.keepMonitorAlive()` die Überwachung alle 60 s neu, solange
  die Bedienungshilfe eingeschaltet ist und `enabled` nicht selbst pausiert wurde.
- **`updatedAt` ist kein Lebenszeichen:** `AppState.phase()` schreibt bei jedem
  Phasenwechsel auch `updatedAt`. Zwei Stichproben im Abstand von >30 s zusammen mit dem
  `app=`-Feld aus `dumpsys` sind die einzige belastbare Antwort darauf, ob die Schleife lebt.
- **„Free up space" nie von Hand bestätigen:** der Dialog löscht Telefon-Medien. Nur die
  App darf ihn bestätigen, und nur nach ihrer Haken-Abfrage.
- **Kein `uiautomator dump`** auf dem Gerät, Screenshots nur nach `/data/local/tmp` —
  beides schreibt sonst in den MediaStore-Ordner, den die App selbst überwacht.
- **Niemals Dateien im Batch-Baum auf dem Telefon anfassen:** Resilio überträgt jede
  Löschung zurück auf die NAS.
