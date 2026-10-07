package de.pixelphotouploader.companion;

import android.content.Context;
import android.content.SharedPreferences;

import java.io.BufferedReader;
import java.io.File;
import java.io.FileReader;
import java.io.FileWriter;
import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Date;
import java.util.HashSet;
import java.util.List;
import java.util.Locale;
import java.util.Set;

final class AppState {
    static final String PREFS = "pixel_photo_companion";
    static final String PHASE_MONITORING = "MONITORING";
    static final String PHASE_WAIT_BACKUP = "WAIT_BACKUP";
    static final String PHASE_OPEN_FREE_UP = "OPEN_FREE_UP";
    static final String PHASE_CONFIRM_FREE_UP = "CONFIRM_FREE_UP";
    static final String PHASE_VERIFY = "VERIFY";
    static final String PHASE_ERROR = "ERROR";

    static final String DEFAULT_FOLDERS =
            "/storage/emulated/0/DCIM/PixelSync";

    static final String DEFAULT_CONTROL_FOLDER =
            "/storage/emulated/0/DCIM/PixelSync/control";

    private AppState() {}

    static SharedPreferences prefs(Context context) {
        return context.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
    }

    static String phase(Context context) {
        return prefs(context).getString("phase", PHASE_MONITORING);
    }

    static void phase(Context context, String phase, String detail) {
        prefs(context).edit()
                .putString("phase", phase)
                .putString("detail", detail)
                .putLong("updatedAt", System.currentTimeMillis())
                .remove("stuckSince")
                .apply();
        log(context, detail);
    }

    // Absage-Marken: Sagt Google Fotos „Nichts freizugeben“, darf die Automatik dieselben
    // Dateien weder noch einmal anbieseln noch ihre spätere Löschung als Google-Freigabe
    // verbuchen — nach dem Urteil gibt der Server die Handreichung selbst frei, und Resilio
    // löscht die Kopie vom Gerät, ohne dass Google Fotos etwas damit getan hätte.
    // Gemerkt wird der Zwölfer-Fingerabdruck aus dem Handreichungsnamen
    // (000042-1a2b3c4d5e6f.jpg): der bleibt über jedes Neueinreihen gleich, laufende
    // Nummer und Batch-Ordner wechseln dabei.
    private static final String REFUSED_TOKENS = "refusedTokens";

    static String contentToken(String path) {
        String name = new File(path).getName().toLowerCase(Locale.ROOT);
        if (name.length() >= 19 && name.charAt(6) == '-') {
            boolean numbered = true;
            for (int i = 0; i < 6; i++) if (!Character.isDigit(name.charAt(i))) numbered = false;
            boolean fingerprinted = true;
            for (int i = 7; i < 19; i++) if (Character.digit(name.charAt(i), 16) < 0) fingerprinted = false;
            if (numbered && fingerprinted) return name.substring(7, 19);
        }
        // ADB-Übergabe und Fremdnamen haben kein Muster; ihr Dateiname ist das beste Merkmal.
        return name;
    }

    static Set<String> refusedTokens(Context context) {
        Set<String> out = new HashSet<>();
        for (String line : prefs(context).getString(REFUSED_TOKENS, "").split("\\n")) {
            String value = line.trim();
            if (!value.isEmpty()) out.add(value);
        }
        return out;
    }

    static boolean isRefused(Context context, String path) {
        return refusedTokens(context).contains(contentToken(path));
    }

    static void rememberRefused(Context context, List<String> paths) {
        Set<String> tokens = refusedTokens(context);
        for (String path : paths) tokens.add(contentToken(path));
        prefs(context).edit().putString(REFUSED_TOKENS, join(new ArrayList<>(tokens))).apply();
    }

    static List<String> withoutRefused(Context context, List<String> paths) {
        Set<String> refused = refusedTokens(context);
        List<String> out = new ArrayList<>();
        for (String path : paths) if (!refused.contains(contentToken(path))) out.add(path);
        return out;
    }

    // Eine Marke ist nur so lange nötig, wie die abgelehnte Datei noch liegt. Ist sie vom
    // Gerät verschwunden, hat der Server ihr Urteil schon abgerechnet — ab hier wäre ein
    // späterer Wiedervorlauf ausgeschlossen, ohne Grund.
    static void forgetRefusedGone(Context context, List<String> presentPaths) {
        Set<String> refused = refusedTokens(context);
        if (refused.isEmpty()) return;
        Set<String> present = new HashSet<>();
        for (String path : presentPaths) present.add(contentToken(path));
        Set<String> kept = new HashSet<>();
        for (String token : refused) if (present.contains(token)) kept.add(token);
        if (kept.size() == refused.size()) return;
        StringBuilder out = new StringBuilder();
        for (String token : kept) { if (out.length() > 0) out.append('\n'); out.append(token); }
        prefs(context).edit().putString(REFUSED_TOKENS, out.toString()).apply();
    }

    private static String join(List<String> values) {
        StringBuilder out = new StringBuilder();
        for (String value : values) { if (out.length() > 0) out.append('\n'); out.append(value); }
        return out.toString();
    }

    static List<String> folderPaths(Context context) {
        String raw = prefs(context).getString("folders", DEFAULT_FOLDERS);
        List<String> result = new ArrayList<>();
        for (String line : raw.split("\\r?\\n")) {
            String value = line.trim();
            if (!value.isEmpty()) result.add(value);
        }
        return result;
    }

    static void log(Context context, String message) {
        File logFile = new File(context.getFilesDir(), "companion.log");
        String time = new SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.GERMANY).format(new Date());
        String line = time + "  " + message.replace('\n', ' ') + "\n";
        try (FileWriter writer = new FileWriter(logFile, true)) {
            writer.write(line);
        } catch (Exception ignored) { }
        if (logFile.length() > 512 * 1024) trimLog(logFile);
        mirrorToShared(context, line);
    }

    // Das interne Protokoll sieht nur das Telefon. Ohne Kabel kommt die Frage
    // "warum hat die Automatik nicht geklickt" sonst nie auf dem Rechner an.
    private static void mirrorToShared(Context context, String line) {
        String configured = prefs(context).getString("controlFolder", DEFAULT_CONTROL_FOLDER);
        File folder = new File(configured);
        if (!folder.isDirectory()) return;
        File shared = new File(folder, "companion-log.txt");
        try (FileWriter writer = new FileWriter(shared, true)) {
            writer.write(line);
        } catch (Exception ignored) {
            return;
        }
        if (shared.length() > 256 * 1024) trimLog(shared);
    }

    private static void trimLog(File logFile) {
        List<String> lines = new ArrayList<>();
        try (BufferedReader reader = new BufferedReader(new FileReader(logFile))) {
            String line;
            while ((line = reader.readLine()) != null) lines.add(line);
            int from = Math.max(0, lines.size() - 1000);
            try (FileWriter writer = new FileWriter(logFile, false)) {
                for (int i = from; i < lines.size(); i++) writer.write(lines.get(i) + "\n");
            }
        } catch (Exception ignored) { }
    }

    static String readLogTail(Context context, int maxLines) {
        File logFile = new File(context.getFilesDir(), "companion.log");
        if (!logFile.exists()) return "Noch keine Aktivität.";
        List<String> lines = new ArrayList<>();
        try (BufferedReader reader = new BufferedReader(new FileReader(logFile))) {
            String line;
            while ((line = reader.readLine()) != null) lines.add(line);
        } catch (Exception e) {
            return "Protokoll konnte nicht gelesen werden: " + e.getMessage();
        }
        StringBuilder out = new StringBuilder();
        int from = Math.max(0, lines.size() - maxLines);
        for (int i = from; i < lines.size(); i++) out.append(lines.get(i)).append('\n');
        return out.toString().trim();
    }
}
