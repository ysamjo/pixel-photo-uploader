package de.pixelphotouploader.companion;

import android.Manifest;
import android.app.ActivityManager;
import android.app.KeyguardManager;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.os.Build;
import android.os.Handler;
import android.os.HandlerThread;
import android.os.IBinder;
import android.os.PowerManager;
import android.provider.Settings;

import java.io.File;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Locale;
import java.util.Set;

public class BackupMonitorService extends Service {
    static final String ACTION_STOP = "de.pixelphotouploader.companion.STOP";
    private static final int NOTIFICATION_ID = 1401;
    private static final String CHANNEL_ID = "backup_monitor";
    private static final long POLL_MILLIS = 30_000L;
    private static final long STABLE_MILLIS = 120_000L;
    // Der Speicherbericht geht durch dieselbe Resilio-Freigabe wie die Rueckbelege; im
    // 30-s-Takt waere das unnoetiger Sync-Verkehr. Fuenf Minuten sind fuer eine
    // Kapazitaetskante frisch genug.
    private static final long STORAGE_REPORT_MILLIS = 5 * 60_000L;

    private HandlerThread workerThread;
    private Handler worker;
    private MediaFolderScanner scanner;
    private PowerManager.WakeLock wakeLock;
    private DeviceStorage.Usage lastUsage;

    @Override public void onCreate() {
        super.onCreate();
        scanner = new MediaFolderScanner(this);
        createChannel();
        workerThread = new HandlerThread("PixelPhotoMonitor");
        workerThread.start();
        worker = new Handler(workerThread.getLooper());
        PowerManager pm = (PowerManager) getSystemService(POWER_SERVICE);
        wakeLock = pm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "PixelPhotoCompanion:monitor");
        wakeLock.acquire();
    }

    @Override public int onStartCommand(Intent intent, int flags, int startId) {
        if (intent != null && ACTION_STOP.equals(intent.getAction())) {
            AppState.prefs(this).edit().putBoolean("enabled", false).apply();
            AppState.phase(this, AppState.PHASE_MONITORING, "Überwachung pausiert.");
            stopSelf();
            return START_NOT_STICKY;
        }
        startForeground(NOTIFICATION_ID, notification("Überwachung wird gestartet …"));
        worker.removeCallbacks(loop);
        worker.post(loop);
        return START_STICKY;
    }

    private final Runnable loop = new Runnable() {
        @Override public void run() {
            try { tick(); }
            catch (Throwable error) {
                AppState.phase(BackupMonitorService.this, AppState.PHASE_ERROR,
                        "Überwachungsfehler: " + error.getMessage());
            }
            if (AppState.prefs(BackupMonitorService.this).getBoolean("enabled", false)) {
                worker.postDelayed(this, POLL_MILLIS);
            } else stopSelf();
        }
    };

    private void tick() {
        SharedPreferences prefs = AppState.prefs(this);
        if (!prefs.getBoolean("enabled", false)) { stopSelf(); return; }
        if (checkSelfPermission(Manifest.permission.READ_EXTERNAL_STORAGE) != PackageManager.PERMISSION_GRANTED) {
            update("Dateizugriff fehlt – App öffnen");
            return;
        }
        if (!prefs.getBoolean("safetyAccepted", false)) {
            update("Sicherheitsbestätigung fehlt");
            return;
        }

        // Speicherstand zuerst und phasenunabhaengig: er ist auch waehrend einer laufenden
        // Handreichung wichtig und speist Warnung sowie die Kapazitaetskante des Servers.
        long now = System.currentTimeMillis();
        lastUsage = DeviceStorage.probe(DeviceStorage.measurementPath(this));
        if (lastUsage != null && lastUsage.measurable()) {
            prefs.edit()
                    .putLong("deviceFreeBytes", lastUsage.freeBytes)
                    .putLong("deviceTotalBytes", lastUsage.totalBytes)
                    .putLong("deviceStorageAt", now)
                    .apply();
            if (now - prefs.getLong("storageReportAt", 0L) >= STORAGE_REPORT_MILLIS) {
                prefs.edit().putLong("storageReportAt", now).apply();
                reportStorage(prefs, lastUsage, now);
            }
        }

        String phase = AppState.phase(this);
        MediaFolderScanner.Snapshot stable = scanner.scanStable(STABLE_MILLIS);
        // Eine abgelehnte Datei, die nicht mehr liegt, ist vom Server abgerechnet: ihre Marke
        // wird fallengelassen, sobald sie vom Gerät verschwunden ist. Der laufende Batch zählt
        // mit — ein nur halb synchronisierter Batch-Ordner erscheint im Bestand noch nicht.
        List<String> stillPresent = new ArrayList<>(stable.seen);
        stillPresent.addAll(split(prefs.getString("batchPaths", "")));
        AppState.forgetRefusedGone(this, stillPresent);
        prefs.edit().putInt("visibleFiles", stable.paths.size()).putLong("visibleBytes", stable.bytes).apply();

        if (AppState.PHASE_ERROR.equals(phase)) {
            if (!RecoveryPolicy.retryable(prefs.getString("detail", ""))
                    && healReceiptFromDisk(prefs, phase)) return;
            if (!recoverError(prefs)) return;
            phase = AppState.phase(this);
        }

        if (!prefs.getString("pendingReceiptPaths", "").trim().isEmpty()) {
            flushPendingReceipt();
            return;
        }
        if (healReceiptFromDisk(prefs, phase)) return;
        if (!prefs.getString("pendingReceiptRefused", "").trim().isEmpty()) {
            flushRefusalReceipt();
            return;
        }

        if (AppState.PHASE_VERIFY.equals(phase)) {
            long verifyAfter = prefs.getLong("verifyAfter", Long.MAX_VALUE);
            if (System.currentTimeMillis() >= verifyAfter) verifyCleanup();
            else update("Google Fotos gibt lokalen Speicher frei …");
            return;
        }
        if (!AppState.PHASE_MONITORING.equals(phase)) {
            update(statusForPhase(phase));
            return;
        }
        long nextAttempt = prefs.getLong("nextAttemptAt", 0L);
        if (System.currentTimeMillis() < nextAttempt) {
            update("Warte vor dem nächsten Versuch");
            return;
        }
        if (stable.paths.isEmpty()) {
            update("Bereit – warte auf neue Fotos");
            return;
        }
        if (!accessibilityEnabled()) {
            update("Bedienungshilfe fehlt – App öffnen");
            return;
        }
        KeyguardManager km = (KeyguardManager) getSystemService(KEYGUARD_SERVICE);
        if (km != null && km.isKeyguardLocked()) {
            update("Pixel gesperrt – bitte einmal entsperren");
            return;
        }

        if (lastUsage != null && DeviceStorage.below(lastUsage.freeBytes, DeviceStorage.FLOOR_GIB)) {
            // Kein neuer Batch auf ein volles Telefon: Resilio kann ihn nicht mehr ganz
            // anlegen, und ein halber Batch ist fuer Google Fotos wertlos. Der gemeldete
            // Speicherstand bleibt stehen, damit der Server die Ursache sieht. Der
            // Warntext ist hier gleich die ganze Meldung — update() verdoppelt ihn nicht.
            String warning = DeviceStorage.warning(lastUsage);
            update(warning != null ? warning
                    : "Warte auf freien Speicher: " + DeviceStorage.describe(lastUsage));
            return;
        }

        List<String> offerable = AppState.withoutRefused(this, stable.paths);
        if (offerable.isEmpty()) {
            update("Nur abgelehnte Dateien liegen noch – warte auf den Server");
            return;
        }
        long offerBytes = 0;
        for (String path : offerable) offerBytes += new File(path).length();

        scanner.mediaScan(offerable);
        prefs.edit()
                .putString("batchPaths", join(offerable))
                .putLong("batchBytes", offerBytes)
                .putLong("batchStartedAt", System.currentTimeMillis())
                .putBoolean("sawActiveBackup", false)
                .putInt("completeStreak", 0)
                .putLong("lastCompleteAt", 0L)
                .apply();
        AppState.phase(this, AppState.PHASE_WAIT_BACKUP,
                String.format(Locale.GERMANY, "%d stabile Dateien an Google Fotos übergeben.", offerable.size()));
        openGooglePhotos();
        update("Google Fotos sichert den aktuellen Batch");
    }

    private boolean recoverError(SharedPreferences prefs) {
        String detail = prefs.getString("detail", "");
        if (!RecoveryPolicy.retryable(detail)) {
            update("Eingriff nötig: " + detail);
            return false;
        }
        long now = System.currentTimeMillis();
        long retryAt = prefs.getLong("errorRetryAt", 0L);
        if (retryAt == 0L) {
            // Auch Fehler einer alten App-Version werden nach dem Update automatisch aufgenommen.
            retryAt = now + RecoveryPolicy.delayMillis(prefs.getInt("recoveryAttempts", 0));
            prefs.edit().putLong("errorRetryAt", retryAt).apply();
            AppState.log(this, "Vorübergehender Fehler: automatische Wiederholung eingeplant.");
        }
        if (now < retryAt) {
            update("Automatische Wiederholung in " + ((retryAt - now + 59_999L) / 60_000L) + " Minuten");
            return false;
        }
        if (!accessibilityEnabled()) { update("Bedienungshilfe fehlt – App öffnen"); return false; }
        KeyguardManager km = (KeyguardManager) getSystemService(KEYGUARD_SERVICE);
        if (km != null && km.isKeyguardLocked()) { update("Pixel gesperrt – bitte einmal entsperren"); return false; }
        boolean hasBatch = !prefs.getString("batchPaths", "").trim().isEmpty();
        prefs.edit().putInt("recoveryAttempts", Math.min(2, prefs.getInt("recoveryAttempts", 0) + 1))
                .putInt("completeStreak", 0).putLong("lastCompleteAt", 0L)
                .putInt("freeUpRound", 0).putLong("nextAttemptAt", 0L).apply();
        // Batch, Absage-Marken und 72-h-Beginn bleiben erhalten; kein erneuter MediaScan.
        AppState.phase(this, RecoveryPolicy.resumePhase(hasBatch),
                "Vorübergehenden Fehler automatisch zurückgesetzt; Sicherung wird erneut geprüft.");
        if (hasBatch) openGooglePhotos();
        return !AppState.PHASE_ERROR.equals(AppState.phase(this));
    }

    /**
     * Aufraeumen und Bericht in einem Zug.
     *
     * Geloescht wird nur unter Druck: die Freigabe gehoert Resilio, solange genug Platz
     * ist, hat die App dort nichts zu suchen. Alte Teilkopien ({@code .!sync}) und
     * haengengebliebene eigene Temp-Reste sind der einzige Speicher, den die App
     * ueberhaupt verantwortet.
     */
    private void reportStorage(SharedPreferences prefs, DeviceStorage.Usage usage, long now) {
        StorageResidue.Reclaimed reclaimed = null;
        if (DeviceStorage.below(usage.freeBytes, DeviceStorage.WARN_GIB)) {
            reclaimed = StorageResidue.reclaim(AppState.folderPaths(this), now);
            if (reclaimed.bytes > 0) {
                AppState.log(this, reclaimed.count() + " abgebrochene Reste freigegeben ("
                        + DeviceStorage.gib(reclaimed.bytes) + ").");
                usage = DeviceStorage.probe(DeviceStorage.measurementPath(this));
                lastUsage = usage;
                if (usage != null && usage.measurable()) {
                    prefs.edit().putLong("deviceFreeBytes", usage.freeBytes)
                            .putLong("deviceTotalBytes", usage.totalBytes).apply();
                }
            }
        }
        if (usage == null || !usage.measurable()) return;
        try {
            File written = StorageReport.write(this, usage,
                    StorageResidue.scan(AppState.folderPaths(this)), reclaimed);
            prefs.edit().putString("lastStorageReport", written.getAbsolutePath()).apply();
        } catch (Exception error) {
            AppState.log(this, "Speicherbericht konnte nicht geschrieben werden: " + error.getMessage());
        }
    }

    private void verifyCleanup() {
        SharedPreferences prefs = AppState.prefs(this);
        List<String> before = split(prefs.getString("batchPaths", ""));
        int removed = 0;
        int remaining = 0;
        List<String> removedPaths = new ArrayList<>();
        for (String path : before) {
            // Eine abgelehnte Datei, die jetzt fehlt, hat der Server freigegeben — nicht
            // Google Fotos. Sie wäre ein Doppelbeleg auf ein bereits gefälltes Urteil.
            if (AppState.isRefused(this, path)) continue;
            if (new File(path).exists()) remaining++;
            else { removed++; removedPaths.add(path); }
        }
        if (removed > 0) {
            prefs.edit()
                    .putString("pendingReceiptPaths", join(removedPaths))
                    .putInt("pendingReceiptRemaining", remaining)
                    .putInt("pendingReceiptCount", removed)
                    .apply();
            flushPendingReceipt();
        } else {
            prefs.edit().putLong("nextAttemptAt", System.currentTimeMillis() + 15 * 60_000L).apply();
            AppState.phase(this, AppState.PHASE_MONITORING,
                    "Google Fotos hat keine überwachte Datei entfernt. Nächste Prüfung in 15 Minuten.");
        }
    }

    private boolean healReceiptFromDisk(SharedPreferences prefs, String phase) {
        String previousError = prefs.getString("detail", "");
        // Nach einer Freigabe entscheidet allein der Dateibestand: fehlt die Datei, war sie
        // weg — auch wenn die App den Knopf nicht selbst gedrückt hat oder vorher in einem
        // Fehlerzustand hängen geblieben ist. VERIFY rechnet selbst ab, bleibt also außen vor.
        if (AppState.PHASE_VERIFY.equals(phase)) return false;
        // Nur für einen Batch, dessen Sicherung beobachtet wurde oder der bereits in der Freigabephase
        // oder im Fehlerzustand war, gilt das Verschwinden der Datei als Beleg der Freigabe.
        boolean wasInFreeUpOrError = AppState.PHASE_OPEN_FREE_UP.equals(phase)
                || AppState.PHASE_CONFIRM_FREE_UP.equals(phase)
                || AppState.PHASE_ERROR.equals(phase);
        boolean confirmedBackup = prefs.getInt("completeStreak", 0) >= 1 || prefs.getBoolean("sawActiveBackup", false);
        if (!wasInFreeUpOrError && !confirmedBackup) return false;
        List<String> paths = split(prefs.getString("batchPaths", ""));
        if (paths.isEmpty()) return false;
        List<String> gone = new ArrayList<>();
        int remaining = 0;
        for (String path : paths) {
            // Verschwindet eine abgelehnte Datei, war das die eigene Handreichungsfreigabe des
            // Servers über Resilio — keine Google-Freigabe. Sie darf nie als Erfolg verbucht
            // werden; das Urteil darüber ist schon als Absage übergeben.
            if (AppState.isRefused(this, path)) continue;
            if (new File(path).exists()) remaining++;
            else gone.add(path);
        }
        if (gone.isEmpty()) return false;
        prefs.edit()
                .putString("pendingReceiptPaths", join(gone))
                .putInt("pendingReceiptRemaining", remaining)
                .putInt("pendingReceiptCount", gone.size())
                .apply();
        AppState.log(this, gone.size() + " freigegebene Dateien aus dem Dateibestand nachgebucht.");
        flushPendingReceipt();
        if (AppState.PHASE_ERROR.equals(phase) && !RecoveryPolicy.retryable(previousError)
                && AppState.PHASE_MONITORING.equals(AppState.phase(this))) {
            // Ein erfolgreicher Beleg repariert keinen fehlenden Account oder vollen Kontospeicher.
            AppState.phase(this, AppState.PHASE_ERROR, previousError);
        }
        return true;
    }

    private void flushRefusalReceipt() {
        SharedPreferences prefs = AppState.prefs(this);
        List<String> refused = new ArrayList<>();
        for (String path : split(prefs.getString("pendingReceiptRefused", ""))) {
            // Nur was noch liegt, ist eine echte Absage. Was fehlt, ist freigeben worden und
            // wird über einen normalen Rückbeleg abgerechnet.
            if (new File(path).exists()) refused.add(path);
        }
        prefs.edit().putString("pendingReceiptRefused", "").apply();
        if (refused.isEmpty()) return;
        try {
            File receipt = ReceiptWriter.write(this, new ArrayList<String>(), refused,
                    refused.size());
            // Die Marke entsteht hier: Von jetzt an bietet die Automatik keine dieser Dateien
            // noch einmal an und verbucht ihre Löschung nicht als Google-Freigabe — die
            // Handreichung gibt nämlich der Server selbst frei, und Resilio löscht sie vom
            // Gerät, ohne dass Google Fotos je etwas damit getan hätte.
            AppState.rememberRefused(this, refused);
            prefs.edit()
                    .putString("lastReceipt", receipt.getAbsolutePath())
                    .putString("batchPaths", "")
                    // Das Urteil ist übergeben; die Zählung beginnt mit dem nächsten Batch von vorn.
                    .putInt("nothingToFreeRounds", 0)
                    .putLong("nextAttemptAt", System.currentTimeMillis() + 60_000L)
                    .apply();
            AppState.phase(this, AppState.PHASE_MONITORING,
                    refused.size() + " Dateien gibt Google Fotos nicht frei; Urteil als Rückbeleg "
                            + "an den Server übergeben. Die Archiv-Kopien bleiben erhalten.");
        } catch (Exception error) {
            prefs.edit().putString("pendingReceiptRefused", join(refused)).apply();
            AppState.phase(this, AppState.PHASE_ERROR,
                    "Das Absage-Urteil konnte nicht als Rückbeleg übergeben werden: "
                            + error.getMessage());
        }
    }

    private void flushPendingReceipt() {
        SharedPreferences prefs = AppState.prefs(this);
        List<String> removedPaths = split(prefs.getString("pendingReceiptPaths", ""));
        if (removedPaths.isEmpty()) return;
        int remaining = prefs.getInt("pendingReceiptRemaining", 0);
        try {
            File receipt = ReceiptWriter.write(this, removedPaths, new ArrayList<String>(), remaining);
            int total = prefs.getInt("completedTotal", 0) + removedPaths.size();
            prefs.edit()
                    .putInt("completedTotal", total)
                    .putInt("lastRemoved", removedPaths.size())
                    .putString("lastReceipt", receipt.getAbsolutePath())
                    .putString("pendingReceiptPaths", "")
                    .putString("batchPaths", "")
                    // Echter Fortschritt: Dateien sind weg. Die Absage-Zählung der Bedienungshilfe
                    // beginnt damit von vorn — sonst zählten sich alte Absagen gegen die neuen
                    // Dateien an.
                    .putInt("nothingToFreeRounds", 0)
                    .putLong("nextAttemptAt", System.currentTimeMillis() + 60_000L)
                    .apply();
            AppState.phase(this, AppState.PHASE_MONITORING,
                    removedPaths.size() + " Dateien lokal freigegeben; Rückbeleg für den Server geschrieben. " +
                            remaining + " Dateien blieben erhalten.");
        } catch (Exception error) {
            AppState.phase(this, AppState.PHASE_ERROR,
                    "Dateien wurden lokal freigegeben, aber der Server-Rückbeleg konnte nicht geschrieben werden: " +
                            error.getMessage());
        }
    }

    private void openGooglePhotos() {
        Intent launch = getPackageManager().getLaunchIntentForPackage("com.google.android.apps.photos");
        if (launch == null) {
            AppState.phase(this, AppState.PHASE_ERROR, "Google Fotos ist nicht installiert.");
            return;
        }
        launch.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TOP);
        startActivity(launch);
    }

    private boolean accessibilityEnabled() {
        String enabled = Settings.Secure.getString(getContentResolver(), Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES);
        if (enabled == null) return false;
        ComponentName component = new ComponentName(this, PhotosAccessibilityService.class);
        return enabled.toLowerCase(Locale.ROOT).contains(component.flattenToString().toLowerCase(Locale.ROOT));
    }

    private String statusForPhase(String phase) {
        if (AppState.PHASE_WAIT_BACKUP.equals(phase)) return "Google Fotos: Sicherung wird geprüft";
        if (AppState.PHASE_OPEN_FREE_UP.equals(phase)) return "Öffne „Speicherplatz freigeben“";
        if (AppState.PHASE_CONFIRM_FREE_UP.equals(phase)) return "Bestätige lokale Freigabe";
        return phase;
    }

    private void update(String text) {
        String storageWarning = DeviceStorage.warning(lastUsage);
        if (storageWarning != null && !text.startsWith("Telefonspeicher")) {
            text = storageWarning + " " + text;
        }
        // Der ADB-Waechter besitzt das Prozess-Neustartrecht; die App zeigt seine Warnung.
        File watchdog = new File(getFilesDir(), "photos-watchdog-status.json");
        if (watchdog.isFile()) {
            try {
                String raw = new String(java.nio.file.Files.readAllBytes(watchdog.toPath()),
                        java.nio.charset.StandardCharsets.UTF_8);
                org.json.JSONObject status = new org.json.JSONObject(raw);
                double age = System.currentTimeMillis() / 1000.0 - status.optDouble("observedAt", 0);
                String state = status.optString("state");
                if (age >= 0 && age <= 150 && ("alert".equals(state) || "cooldown".equals(state))) {
                    text = status.optString("message", text);
                }
            } catch (Exception ignored) { }
        }
        AppState.prefs(this).edit().putString("serviceStatus", text).putLong("updatedAt", System.currentTimeMillis()).apply();
        NotificationManager manager = (NotificationManager) getSystemService(NOTIFICATION_SERVICE);
        if (manager != null) manager.notify(NOTIFICATION_ID, notification(text));
    }

    private Notification notification(String text) {
        Intent open = new Intent(this, MainActivity.class);
        PendingIntent pending = PendingIntent.getActivity(this, 1, open,
                Build.VERSION.SDK_INT >= 23 ? PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE : PendingIntent.FLAG_UPDATE_CURRENT);
        Intent stop = new Intent(this, BackupMonitorService.class).setAction(ACTION_STOP);
        PendingIntent stopPending = PendingIntent.getService(this, 2, stop,
                Build.VERSION.SDK_INT >= 23 ? PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE : PendingIntent.FLAG_UPDATE_CURRENT);
        return new Notification.Builder(this, CHANNEL_ID)
                .setSmallIcon(android.R.drawable.stat_sys_upload)
                .setContentTitle("Pixel Photo Companion")
                .setContentText(text)
                .setContentIntent(pending)
                .setOngoing(true)
                .addAction(new Notification.Action.Builder(null, "Pausieren", stopPending).build())
                .build();
    }

    private void createChannel() {
        if (Build.VERSION.SDK_INT >= 26) {
            NotificationChannel channel = new NotificationChannel(CHANNEL_ID, "Foto-Sicherungsüberwachung", NotificationManager.IMPORTANCE_LOW);
            channel.setDescription("Zeigt den aktuellen Zustand der Pixel-Fotoautomatisierung.");
            NotificationManager manager = (NotificationManager) getSystemService(NOTIFICATION_SERVICE);
            if (manager != null) manager.createNotificationChannel(channel);
        }
    }

    static boolean isRunning(Context context) {
        ActivityManager manager = (ActivityManager) context.getSystemService(ACTIVITY_SERVICE);
        if (manager == null) return false;
        for (ActivityManager.RunningServiceInfo info : manager.getRunningServices(Integer.MAX_VALUE)) {
            if (BackupMonitorService.class.getName().equals(info.service.getClassName())) return true;
        }
        return false;
    }

    static void start(Context context) {
        Intent intent = new Intent(context, BackupMonitorService.class);
        if (Build.VERSION.SDK_INT >= 26) context.startForegroundService(intent); else context.startService(intent);
    }

    private static String join(List<String> values) {
        StringBuilder out = new StringBuilder();
        for (String value : values) { if (out.length() > 0) out.append('\n'); out.append(value); }
        return out.toString();
    }

    private static List<String> split(String raw) {
        List<String> out = new ArrayList<>();
        for (String line : raw.split("\\n")) if (!line.trim().isEmpty()) out.add(line.trim());
        return out;
    }

    @Override public void onDestroy() {
        if (worker != null) worker.removeCallbacksAndMessages(null);
        if (workerThread != null) workerThread.quitSafely();
        if (wakeLock != null && wakeLock.isHeld()) wakeLock.release();
        super.onDestroy();
    }

    @Override public IBinder onBind(Intent intent) { return null; }
}
