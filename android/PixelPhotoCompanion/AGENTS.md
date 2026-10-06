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
