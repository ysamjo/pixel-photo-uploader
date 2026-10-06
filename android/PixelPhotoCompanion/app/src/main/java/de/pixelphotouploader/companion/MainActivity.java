package de.pixelphotouploader.companion;

import android.Manifest;
import android.app.Activity;
import android.content.ComponentName;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.graphics.Typeface;
import android.os.Bundle;
import android.os.Handler;
import android.provider.Settings;
import android.text.InputType;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.CheckBox;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

import java.text.DateFormat;
import java.util.Date;
import java.util.Locale;

public class MainActivity extends Activity {
    private static final int STORAGE_REQUEST = 41;
    private final Handler refreshHandler = new Handler();
    private TextView mainStatus;
    private TextView detail;
    private TextView permissionStatus;
    private TextView counters;
    private TextView log;
    private EditText folders;
    private EditText controlFolder;
    private CheckBox safety;
    private Button start;
    private Button pause;

    @Override protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        buildUi();
    }

    private void buildUi() {
        SharedPreferences prefs = AppState.prefs(this);
        ScrollView scroll = new ScrollView(this);
        scroll.setFillViewport(true);
        LinearLayout root = column();
        root.setPadding(dp(20), dp(18), dp(20), dp(28));
        root.setBackgroundColor(Color.rgb(244, 247, 251));
        scroll.addView(root);

        TextView title = text("Pixel Photo Companion", 25, true);
        title.setTextColor(Color.rgb(30, 64, 175));
        root.addView(title);
        TextView intro = text("Automatische Google-Fotos-Sicherung auf deinem Pixel 1", 15, false);
        intro.setTextColor(Color.DKGRAY);
        intro.setPadding(0, dp(2), 0, dp(18));
        root.addView(intro);

        LinearLayout statusCard = card();
        mainStatus = text("Wird geladen …", 20, true);
        detail = text("", 14, false);
        detail.setPadding(0, dp(7), 0, 0);
        statusCard.addView(mainStatus);
        statusCard.addView(detail);
        root.addView(statusCard);

        root.addView(section("Voraussetzungen"));
        permissionStatus = text("", 14, false);
        root.addView(permissionStatus);
        LinearLayout permissionButtons = row();
        Button filesButton = button("Dateizugriff erlauben", Color.rgb(71,85,105));
        Button accessibilityButton = button("Bedienungshilfe öffnen", Color.rgb(37,99,235));
        permissionButtons.addView(filesButton, weighted());
        permissionButtons.addView(accessibilityButton, weighted());
        root.addView(permissionButtons);

        root.addView(section("Überwachte Ordner"));
        TextView hint = text("Ein Ordner pro Zeile. Resilio-Teilübertragungen (*.!sync) werden ignoriert.", 13, false);
        hint.setTextColor(Color.DKGRAY);
        root.addView(hint);
        folders = new EditText(this);
        folders.setText(prefs.getString("folders", AppState.DEFAULT_FOLDERS));
        folders.setTextSize(13);
        folders.setMinLines(3);
        folders.setGravity(Gravity.TOP | Gravity.START);
        folders.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_FLAG_MULTI_LINE | InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS);
        folders.setBackgroundColor(Color.WHITE);
        folders.setPadding(dp(12), dp(10), dp(12), dp(10));
        LinearLayout.LayoutParams folderParams = matchWrap();
        folderParams.topMargin = dp(8);
        root.addView(folders, folderParams);

        TextView controlHint = text("Kontrollordner für Rückmeldungen (z. B. DCIM/PixelSync/control)", 13, false);
        controlHint.setTextColor(Color.DKGRAY);
        controlHint.setPadding(0, dp(12), 0, dp(5));
        root.addView(controlHint);
        controlFolder = new EditText(this);
        controlFolder.setSingleLine(true);
        controlFolder.setText(prefs.getString("controlFolder", AppState.DEFAULT_CONTROL_FOLDER));
        controlFolder.setTextSize(13);
        controlFolder.setBackgroundColor(Color.WHITE);
        controlFolder.setPadding(dp(12), dp(10), dp(12), dp(10));
        root.addView(controlFolder, matchWrap());

        safety = new CheckBox(this);
        safety.setText("Dieses Pixel dient als Upload-Gerät. Google Fotos darf alle bereits gesicherten lokalen Medien über „Speicherplatz freigeben“ entfernen.");
        safety.setTextSize(14);
        safety.setChecked(prefs.getBoolean("safetyAccepted", false));
        safety.setPadding(0, dp(14), 0, dp(6));
        root.addView(safety);
        safety.setOnCheckedChangeListener((buttonView, checked) -> {
            prefs.edit().putBoolean("safetyAccepted", checked).apply();
            if (!checked && prefs.getBoolean("enabled", false)) pauseMonitoring();
        });

        LinearLayout controlButtons = row();
        start = button("Überwachung starten", Color.rgb(22,163,74));
        pause = button("Pausieren", Color.rgb(220,38,38));
        controlButtons.addView(start, weighted());
        controlButtons.addView(pause, weighted());
        root.addView(controlButtons);

        LinearLayout helperButtons = row();
        Button photos = button("Google Fotos öffnen", Color.rgb(71,85,105));
        Button reset = button("Fehler zurücksetzen", Color.rgb(71,85,105));
        helperButtons.addView(photos, weighted());
        helperButtons.addView(reset, weighted());
        root.addView(helperButtons);

        root.addView(section("Aktueller Bestand"));
        counters = text("", 15, false);
        LinearLayout counterCard = card();
        counterCard.addView(counters);
        root.addView(counterCard);

        root.addView(section("Protokoll"));
        log = text("", 12, false);
        log.setTypeface(Typeface.MONOSPACE);
        log.setTextColor(Color.rgb(226,232,240));
        log.setBackgroundColor(Color.rgb(15,23,42));
        log.setPadding(dp(12),dp(12),dp(12),dp(12));
        log.setTextIsSelectable(true);
        root.addView(log, matchWrap());

        TextView note = text("Die App klickt ausschließlich eindeutig erkannte Bedienelemente in Google Fotos. Bei unbekannter Oberfläche, Fehlerstatus oder gesperrtem Pixel wird nichts freigegeben.", 12, false);
        note.setTextColor(Color.DKGRAY);
        note.setPadding(0, dp(16), 0, 0);
        root.addView(note);
        setContentView(scroll);

        filesButton.setOnClickListener(v -> requestPermissions(new String[]{Manifest.permission.READ_EXTERNAL_STORAGE, Manifest.permission.WRITE_EXTERNAL_STORAGE}, STORAGE_REQUEST));
        accessibilityButton.setOnClickListener(v -> startActivity(new Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS)));
        start.setOnClickListener(v -> startMonitoring());
        pause.setOnClickListener(v -> pauseMonitoring());
        photos.setOnClickListener(v -> openPhotos());
        reset.setOnClickListener(v -> {
            // Beide Versuchs-Zähler mit löschen: sonst meldet die Automatik nach dem Zurücksetzen
            // sofort wieder Fehler, weil die alten Versuche noch in den Prefs stehen.
            prefs.edit().putString("phase", AppState.PHASE_MONITORING).putString("detail", "Fehler zurückgesetzt.")
                    .putInt("completeStreak", 0).putInt("freeUpRound", 0)
                    .putInt("nothingToFreeRounds", 0).putLong("nextAttemptAt", 0L).apply();
            AppState.log(this, "Fehlerzustand manuell zurückgesetzt.");
            refresh();
        });
    }

    private void startMonitoring() {
        if (checkSelfPermission(Manifest.permission.READ_EXTERNAL_STORAGE) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{Manifest.permission.READ_EXTERNAL_STORAGE, Manifest.permission.WRITE_EXTERNAL_STORAGE}, STORAGE_REQUEST);
            return;
        }
        if (!safety.isChecked()) {
            detail.setText("Bitte zuerst die Sicherheitsbestätigung aktivieren.");
            detail.setTextColor(Color.rgb(185,28,28));
            return;
        }
        String folderText = folders.getText().toString().trim();
        if (folderText.isEmpty()) {
            detail.setText("Mindestens ein überwachter Ordner ist erforderlich.");
            detail.setTextColor(Color.rgb(185,28,28));
            return;
        }
        String controlText = controlFolder.getText().toString().trim();
        if (controlText.isEmpty()) {
            detail.setText("Der Resilio-Kontrollordner ist erforderlich.");
            detail.setTextColor(Color.rgb(185,28,28));
            return;
        }
        AppState.prefs(this).edit()
                .putString("folders", folderText)
                .putString("controlFolder", controlText)
                .putBoolean("safetyAccepted", true)
                .putBoolean("enabled", true)
                .putLong("nextAttemptAt", 0L)
                .apply();
        if (AppState.PHASE_ERROR.equals(AppState.phase(this))) AppState.phase(this, AppState.PHASE_MONITORING, "Überwachung gestartet.");
        else AppState.log(this, "Überwachung gestartet.");
        BackupMonitorService.start(this);
        refresh();
    }

    private void pauseMonitoring() {
        AppState.prefs(this).edit().putBoolean("enabled", false).apply();
        Intent stop = new Intent(this, BackupMonitorService.class).setAction(BackupMonitorService.ACTION_STOP);
        startService(stop);
        refresh();
    }

    private void openPhotos() {
        Intent launch = getPackageManager().getLaunchIntentForPackage("com.google.android.apps.photos");
        if (launch != null) startActivity(launch);
        else detail.setText("Google Fotos ist nicht installiert.");
    }

    private void refresh() {
        SharedPreferences prefs = AppState.prefs(this);
        boolean enabled = prefs.getBoolean("enabled", false);
        boolean running = BackupMonitorService.isRunning(this);
        String phase = AppState.phase(this);
        String service = prefs.getString("serviceStatus", "Noch nicht gestartet");
        String phaseText = humanPhase(phase);
        mainStatus.setText(enabled && running ? "● Aktiv: " + phaseText : "■ Pausiert");
        mainStatus.setTextColor(enabled && running ? Color.rgb(21,128,61) : Color.rgb(71,85,105));
        detail.setText(prefs.getString("detail", service) + "\n" + service);
        detail.setTextColor(AppState.PHASE_ERROR.equals(phase) ? Color.rgb(185,28,28) : Color.DKGRAY);

        boolean fileAccess = checkSelfPermission(Manifest.permission.READ_EXTERNAL_STORAGE) == PackageManager.PERMISSION_GRANTED;
        boolean accessibility = accessibilityEnabled();
        permissionStatus.setText((fileAccess ? "✓" : "✗") + " Dateizugriff    " +
                (accessibility ? "✓" : "✗") + " Bedienungshilfe    " +
                (safety.isChecked() ? "✓" : "✗") + " Sicherheitsbestätigung");
        permissionStatus.setTextColor(fileAccess && accessibility && safety.isChecked() ? Color.rgb(21,128,61) : Color.rgb(180,83,9));

        int visible = prefs.getInt("visibleFiles", 0);
        long bytes = prefs.getLong("visibleBytes", 0L);
        int completed = prefs.getInt("completedTotal", 0);
        long updated = prefs.getLong("updatedAt", 0L);
        String updatedText = updated == 0 ? "noch nie" : DateFormat.getDateTimeInstance(DateFormat.SHORT, DateFormat.MEDIUM).format(new Date(updated));
        counters.setText(String.format(Locale.GERMANY,
                "Stabile Dateien in überwachten Ordnern: %,d\nGröße: %.2f GiB\nSeit Installation lokal freigegeben: %,d\nLetzte Aktualisierung: %s",
                visible, bytes / 1073741824.0, completed, updatedText));
        log.setText(AppState.readLogTail(this, 80));
        start.setEnabled(!enabled || !running);
        pause.setEnabled(enabled || running);
        folders.setEnabled(!enabled && !running);
        controlFolder.setEnabled(!enabled && !running);
    }

    private boolean accessibilityEnabled() {
        String enabled = Settings.Secure.getString(getContentResolver(), Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES);
        if (enabled == null) return false;
        String component = new ComponentName(this, PhotosAccessibilityService.class).flattenToString();
        return enabled.toLowerCase(Locale.ROOT).contains(component.toLowerCase(Locale.ROOT));
    }

    private String humanPhase(String phase) {
        if (AppState.PHASE_MONITORING.equals(phase)) return "Ordnerüberwachung";
        if (AppState.PHASE_WAIT_BACKUP.equals(phase)) return "warte auf Google-Fotos-Sicherung";
        if (AppState.PHASE_OPEN_FREE_UP.equals(phase)) return "öffnet Speicherplatz freigeben";
        if (AppState.PHASE_CONFIRM_FREE_UP.equals(phase)) return "prüft Freigabebestätigung";
        if (AppState.PHASE_VERIFY.equals(phase)) return "prüft entfernte Dateien";
        if (AppState.PHASE_ERROR.equals(phase)) return "wegen Fehler angehalten";
        return phase;
    }

    @Override protected void onResume() {
        super.onResume();
        refreshHandler.post(refreshLoop);
    }

    @Override protected void onPause() {
        refreshHandler.removeCallbacks(refreshLoop);
        super.onPause();
    }

    private final Runnable refreshLoop = new Runnable() {
        @Override public void run() { refresh(); refreshHandler.postDelayed(this, 2_000L); }
    };

    @Override public void onRequestPermissionsResult(int requestCode, String[] permissions, int[] grantResults) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        refresh();
    }

    private LinearLayout column() { LinearLayout l = new LinearLayout(this); l.setOrientation(LinearLayout.VERTICAL); return l; }
    private LinearLayout row() { LinearLayout l = new LinearLayout(this); l.setOrientation(LinearLayout.HORIZONTAL); l.setPadding(0,dp(8),0,0); return l; }
    private LinearLayout card() { LinearLayout l=column(); l.setPadding(dp(14),dp(14),dp(14),dp(14)); l.setBackgroundColor(Color.WHITE); LinearLayout.LayoutParams p=matchWrap(); p.bottomMargin=dp(8); l.setLayoutParams(p); return l; }
    private TextView section(String value) { TextView v=text(value,17,true); v.setPadding(0,dp(18),0,dp(7)); return v; }
    private TextView text(String value, float size, boolean bold) { TextView v=new TextView(this); v.setText(value); v.setTextSize(size); v.setTextColor(Color.rgb(35,42,52)); if(bold)v.setTypeface(Typeface.DEFAULT,Typeface.BOLD); return v; }
    private Button button(String value, int color) { Button b=new Button(this); b.setText(value); b.setTextColor(Color.WHITE); b.setTextSize(13); b.setAllCaps(false); b.setBackgroundColor(color); return b; }
    private LinearLayout.LayoutParams weighted() { LinearLayout.LayoutParams p=new LinearLayout.LayoutParams(0,dp(48),1f); p.setMargins(dp(3),0,dp(3),0); return p; }
    private LinearLayout.LayoutParams matchWrap() { return new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT); }
    private int dp(int value) { return Math.round(value * getResources().getDisplayMetrics().density); }
}
