package de.pixelphotouploader.companion;

import android.accessibilityservice.AccessibilityService;
import android.content.Intent;
import android.content.SharedPreferences;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;
import android.view.accessibility.AccessibilityEvent;
import android.view.accessibility.AccessibilityNodeInfo;

import java.io.File;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Locale;

public class PhotosAccessibilityService extends AccessibilityService {
    private static final String PHOTOS_PACKAGE = "com.google.android.apps.photos";
    private static final long COMPLETE_INTERVAL = 45_000L;
    private static final long GRACE_MILLIS = 5 * 60_000L;
    private static final long PHOTOS_LAUNCH_SPACING = 45_000L;
    // Zeigt Google Fotos 30 Minuten lang weder Aktivität noch Abschluss (oder fehlt der
    // Menüpunkt genauso lange), hält die Automatik laut an statt still zu stehen: vorher
    // klickte sie bis zum 72-Stunden-Limit nur das Profil an/aus, ohne je Bildschirmtexte
    // zu melden — ein umbenannter Google-Fotos-Wortlaut war damit unsichtbar.
    private static final long STUCK_MILLIS = 30 * 60_000L;
    // So oft darf der Freigabebildschirm ohne Dialog beobachtet werden, bevor ein Mensch
    // gebraucht wird. Gezählt wird hier, nicht die Wanduhr: über Nacht schläft das Fenster,
    // und neun Stunden Schlaf sind kein Grund für einen Fehlerzustand.
    private static final int FREE_UP_ROUNDS = 6;
    private static final long FREE_UP_ROUND_SPACING = 5 * 60_000L;
    // So oft darf Google Fotos „Nichts freizugeben“ melden, bevor wir die Datei als
    // unbestätigt melden und den Server die Handreichung nach seinem Timeout freigeben lassen.
    private static final int NOTHING_TO_FREE_ROUNDS = 2;
    // Wörter, die eine laufende Sicherung beweisen. Sie heavier als die Fehlerwörter unten:
    // Promo- und Onboarding-Karten von Google Fotos enthalten Sätze wie „Backup is off“,
    // während die Sicherung in Wahrheit durchläuft.
    private static final String[] BACKUP_ACTIVE_NEEDLES = {
            "sicherung läuft", "wird gesichert", "werden gesichert", "wird hochgeladen",
            "hochladen läuft", "fotos werden gesichert", "videos werden gesichert",
            "sicherung wird vorbereitet", "synchronis",
            "backing up", "preparing backup", "getting ready to back up", "uploading",
            "items left", "item left", "elemente verbleibend", "element verbleibend", "elemente",
            "checking time remaining", "remaining time", "keep the app open", "keep app open"
    };
    private final Handler handler = new Handler(Looper.getMainLooper());
    private long lastActionAt = 0L;
    private long lastInspectAt = 0L;
    private long lastKeepAliveAt = 0L;

    private final Runnable poll = new Runnable() {
        @Override public void run() {
            keepMonitorAlive();
            inspect();
            handler.postDelayed(this, 5_000L);
        }
    };

    // Ein APK-Update beendet die App per Force-Stop, und der START_STICKY-Neustart der
    // Überwachung überlebt das nicht: der Service-Record bleibt ohne Prozess hängen, der
    // 30-Sekunden-Tick läuft nie wieder an. Die App meldet dann „Pausiert“ und auf der NAS
    // fällt keine Fehlerzeile auf — die Queue steht still. Die Bedienungshilfe dagegen ist
    // an das System gebunden und lebt, solange sie eingeschaltet ist; sie weckt die
    // Überwachung wieder. Wer sie selbst pausiert hat (enabled=false), wird nicht geweckt.
    private void keepMonitorAlive() {
        long now = System.currentTimeMillis();
        if (now - lastKeepAliveAt < 60_000L) return;
        lastKeepAliveAt = now;
        if (!AppState.prefs(this).getBoolean("enabled", false)) return;
        if (BackupMonitorService.isRunning(this)) return;
        AppState.log(this, "Überwachung lief nicht – wird neu gestartet.");
        BackupMonitorService.start(this);
    }

    @Override protected void onServiceConnected() {
        super.onServiceConnected();
        AppState.log(this, "Bedienungshilfe verbunden.");
        handler.removeCallbacks(poll);
        handler.post(poll);
    }

    @Override public void onAccessibilityEvent(AccessibilityEvent event) {
        if (event == null || event.getPackageName() == null) return;
        if (!PHOTOS_PACKAGE.contentEquals(event.getPackageName())) return;
        // Während der Sicherung feuert Fotos Ereignis-Bursts (Fortschritt); der 5-s-Poll
        // reicht dort völlig (Streak braucht 45 s Abstand). Jeder Event-Scan kostet einen
        // kompletten Baumdurchlauf. Dialogphasen bleiben ereignisgetrieben (Timing zählt).
        if (AppState.PHASE_WAIT_BACKUP.equals(AppState.phase(this))
                && System.currentTimeMillis() - lastInspectAt < 10_000L) return;
        inspect();
    }

    private void inspect() {
        SharedPreferences prefs = AppState.prefs(this);
        if (!prefs.getBoolean("enabled", false)) return;
        lastInspectAt = System.currentTimeMillis();
        String phase = AppState.phase(this);
        if (AppState.PHASE_MONITORING.equals(phase) || AppState.PHASE_VERIFY.equals(phase) || AppState.PHASE_ERROR.equals(phase)) return;
        long batchStarted = prefs.getLong("batchStartedAt", System.currentTimeMillis());
        if (System.currentTimeMillis() - batchStarted > 72L * 60L * 60L * 1000L) {
            AppState.phase(this, AppState.PHASE_ERROR,
                    "Google Fotos wurde innerhalb von 72 Stunden nicht fertig. Es wurde nichts freigegeben.");
            return;
        }

        // Versuche mit Abstand: sonst feuert die Automatik in jeder Runde auf denselben
        // Bildschirm, wenn Google Fotos gerade nicht geantwortet hat.
        if (System.currentTimeMillis() < prefs.getLong("nextAttemptAt", 0L)) return;

        AccessibilityNodeInfo root = getRootInActiveWindow();
        if (root == null || (!photosVisible(root) && !systemDialog(root))) {
            // Nur bei leerem oder fremdem Fenster wird Google Fotos vorgeholt. Systemdialoge
            // (Berechtigung, „Zulassen“) liegen über dem Fotos-Fenster und enthalten Klickbares —
            // sie werden gelesen statt übergangen.
            bringPhotosForward(prefs);
            return;
        }

        List<NodeText> nodes = new ArrayList<>();
        collect(root, nodes);
        String all = allText(nodes);

        String errorHit = firstMatch(all,
                "sicherung ist deaktiviert", "sicherung deaktiviert", "sicherung aus", "sicherung ausgeschaltet",
                "sicherungsfehler", "sicherung fehlgeschlagen",
                "fehler bei der sicherung", "nicht gesichert", "keine sicherung", "fehlgeschlagen",
                "backup is off", "backup off", "backup turned off",
                "backup error", "backup failed", "not backed up", "no backup",
                "kontospeicher voll", "account storage full", "account storage is full",
                "konnte nicht gesichert", "couldn't back up", "could not back up");
        if (errorHit != null && !containsAny(all, BACKUP_ACTIVE_NEEDLES)) {
            // Der gefundene Wortlaut steht in der Meldung: ohne ihn war ein Fehlalarm von
            // einem echten Sicherungsstopp auf dem Gerät nicht zu unterscheiden.
            AppState.phase(this, AppState.PHASE_ERROR,
                    "Google Fotos meldet einen Sicherungsfehler („" + errorHit
                            + "“). Es wurde nichts freigegeben.");
            return;
        }

        if (AppState.PHASE_WAIT_BACKUP.equals(phase)) inspectBackup(nodes, all, prefs);
        else if (AppState.PHASE_OPEN_FREE_UP.equals(phase)) openFreeUp(nodes, prefs);
        else if (AppState.PHASE_CONFIRM_FREE_UP.equals(phase)) confirmFreeUp(nodes, all, prefs);
    }

    private static boolean photosVisible(AccessibilityNodeInfo root) {
        return root != null && PHOTOS_PACKAGE.contentEquals(root.getPackageName());
    }

    private static boolean systemDialog(AccessibilityNodeInfo root) {
        if (root == null || root.getPackageName() == null) return false;
        String pkg = root.getPackageName().toString();
        return "android".equals(pkg) || "com.android.systemui".equals(pkg)
                || "com.android.packageinstaller".equals(pkg)
                || "com.google.android.packageinstaller".equals(pkg)
                || "com.android.permissioncontroller".equals(pkg);
    }

    private void bringPhotosForward(SharedPreferences prefs) {
        if (System.currentTimeMillis() - prefs.getLong("photosLaunchAt", 0L) < PHOTOS_LAUNCH_SPACING) return;
        prefs.edit().putLong("photosLaunchAt", System.currentTimeMillis()).apply();
        Intent launch = getPackageManager().getLaunchIntentForPackage(PHOTOS_PACKAGE);
        if (launch == null) {
            AppState.phase(this, AppState.PHASE_ERROR, "Google Fotos ist nicht installiert.");
            return;
        }
        launch.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        try {
            startActivity(launch);
            AppState.log(this, "Google Fotos vorgeholt, weil die Automatik ein Fenster zum Lesen braucht.");
        } catch (Exception error) {
            // Android untersagt Aktivitäten aus dem Hintergrund, wenn dem Gerät die
            // Entwickleroption „Bildschirm nicht ausschalten“ fehlt. Dann wartet die
            // Automatik weiter, statt in einem Fehlerzustand zu landen.
            prefs.edit().putLong("nextAttemptAt", System.currentTimeMillis() + FREE_UP_ROUND_SPACING).apply();
            AppState.log(this, "Google Fotos ließ sich nicht vorholen: " + error.getMessage());
        }
    }

    private void inspectBackup(List<NodeText> nodes, String all, SharedPreferences prefs) {
        // Abschluss zuerst: Enthält ein Abschlussblatt zufällig ein Aktiv-Wort („Elemente“),
        // würde die umgekehrte Reihenfolge den Abschluss endlos vertagen (sawActive + streak=0).
        if (containsAny(all, "sicherung abgeschlossen", "sicherung vollständig", "alle fotos gesichert",
                "alle elemente gesichert", "alle medien gesichert",
                "auf neuestem stand", "sicherung ist aktuell",
                "synchronisierung abgeschlossen", "synchronisation abgeschlossen",
                "backup complete", "backup is complete", "sync complete", "all photos backed up",
                "all photos & videos backed up", "all photos and videos backed up",
                "everything backed up", "up to date", "backed up", "backup done")) {
            clearStuck(prefs);
            boolean sawActive = prefs.getBoolean("sawActiveBackup", false);
            long started = prefs.getLong("batchStartedAt", System.currentTimeMillis());
            if (!sawActive && System.currentTimeMillis() - started < GRACE_MILLIS) return;
            long last = prefs.getLong("lastCompleteAt", 0L);
            if (System.currentTimeMillis() - last < COMPLETE_INTERVAL) return;
            int streak = prefs.getInt("completeStreak", 0) + 1;
            prefs.edit().putInt("completeStreak", streak).putLong("lastCompleteAt", System.currentTimeMillis()).apply();
            AppState.log(this, "Google Fotos meldet Sicherung abgeschlossen (Prüfung " + streak + "/2)." );
            if (streak >= 2) {
                AppState.phase(this, AppState.PHASE_OPEN_FREE_UP,
                        "Sicherung zweimal bestätigt. Suche „Speicherplatz freigeben“." );
                openFreeUp(nodes, prefs);
            }
            return;
        }

        if (containsAny(all, BACKUP_ACTIVE_NEEDLES)) {
            clearStuck(prefs);
            prefs.edit().putBoolean("sawActiveBackup", true).putInt("completeStreak", 0).apply();
            return;
        }

        // Weder aktiv noch abgeschlossen: früher klickte die Automatik hier bis zum
        // 72-Stunden-Limit nur das Profil an/aus, ohne je Bildschirmtexte zu melden.
        // Nach der Karenz zählt Stillstand als Befund — mit den gelesenen Texten im Fehler.
        long started = prefs.getLong("batchStartedAt", System.currentTimeMillis());
        if (!prefs.getBoolean("sawActiveBackup", false)
                && System.currentTimeMillis() - started >= GRACE_MILLIS) {
            noteStuck(prefs, nodes, "weder Sicherungsaktivität noch Sicherungsabschluss");
        }

        if (System.currentTimeMillis() - lastActionAt > 10_000L) {
            NodeText profile = find(nodes,
                    "google-konto", "google account", "profilbild", "profile picture",
                    "kontoprofilfoto", "account profile", "konto und einstellungen", "account and settings",
                    "signed in as", "angemeldet als", "profile photo");
            if (profile != null && click(profile.node)) {
                lastActionAt = System.currentTimeMillis();
                AppState.log(this, "Google-Fotos-Profilmenü geöffnet.");
            }
        }
    }

    private void openFreeUp(List<NodeText> nodes, SharedPreferences prefs) {
        if (!reconcileNewFiles(false)) return;
        if (!claimFreedFiles()) return;
        NodeText free = findFreeUp(nodes);
        if (free != null && System.currentTimeMillis() - lastActionAt > 2_000L && click(free.node)) {
            lastActionAt = System.currentTimeMillis();
            AppState.phase(this, AppState.PHASE_CONFIRM_FREE_UP,
                    "Menüpunkt „Speicherplatz freigeben“ geöffnet; warte auf eindeutige Bestätigung.");
            return;
        }
        // Kein Menüpunkt auf dem Bildschirm: früher Profil-Toggeln ohne Diagnose bis zum
        // 72-Stunden-Limit. Jetzt zählt auch hier Stillstand als Befund.
        noteStuck(prefs, nodes, "keinen Menüpunkt „Speicherplatz freigeben“");
        if (System.currentTimeMillis() - lastActionAt > 10_000L) {
            NodeText profile = find(nodes,
                    "google-konto", "google account", "profilbild", "profile picture",
                    "kontoprofilfoto", "account profile", "konto und einstellungen", "account and settings",
                    "signed in as", "angemeldet als", "profile photo");
            if (profile != null && click(profile.node)) lastActionAt = System.currentTimeMillis();
        }
    }

    private void noteStuck(SharedPreferences prefs, List<NodeText> nodes, String missing) {
        long now = System.currentTimeMillis();
        long since = prefs.getLong("stuckSince", 0L);
        if (since == 0L) {
            prefs.edit().putLong("stuckSince", now).apply();
            AppState.log(this, "Unbekannter Google-Fotos-Bildschirm (" + missing + "). Bildschirmtexte: "
                    + screenSummary(nodes, 4000, true));
            return;
        }
        if (now - since < STUCK_MILLIS) return;
        AppState.phase(this, AppState.PHASE_ERROR,
                "Google Fotos zeigt seit 30 Minuten " + missing + ". "
                        + "Es wurde nichts freigegeben. Zu melden: " + screenSummary(nodes, 180)
                        + " … (vollständig im Protokoll)");
    }

    private static void clearStuck(SharedPreferences prefs) {
        if (prefs.getLong("stuckSince", 0L) != 0L) prefs.edit().remove("stuckSince").apply();
    }

    private void confirmFreeUp(List<NodeText> nodes, String all, SharedPreferences prefs) {
        if (!reconcileNewFiles(true)) return;
        if (!claimFreedFiles()) return;
        if (containsAny(all,
                "nichts freizugeben", "nothing to free up", "kein speicherplatz freizugeben",
                "keinen speicherplatz freigeben", "no space to free up", "cannot free up space",
                "can't free up space", "no items to free up")) {
            int refused = prefs.getInt("nothingToFreeRounds", 0) + 1;
            if (refused >= NOTHING_TO_FREE_ROUNDS) {
                List<String> stuck = new ArrayList<>();
                for (String line : prefs.getString("batchPaths", "").split("\\n")) {
                    if (!line.trim().isEmpty()) stuck.add(line.trim());
                }
                // Keine Erfolgsbuchung: „Nichts freizugeben“ beweist nicht, dass Google Fotos
                // die Datei bereits gesichert hat. Der Server gibt sie nach seinem Timeout frei.
                AppState.rememberRefused(this, stuck);
                prefs.edit().putInt("nothingToFreeRounds", refused)
                        .putLong("nextAttemptAt", System.currentTimeMillis() + 30 * 60_000L).apply();
                AppState.phase(this, AppState.PHASE_MONITORING,
                        stuck.size() + " Dateien sind unbestätigt: Google Fotos meldet wiederholt „Nichts freizugeben“. "
                                + "Kein Erfolgsbeleg; der Server gibt die Handreichung nach seinem Timeout frei.");
                return;
            }
            prefs.edit().putLong("nextAttemptAt", System.currentTimeMillis() + 15 * 60_000L)
                    .putInt("freeUpRound", 0).putInt("nothingToFreeRounds", refused).apply();
            AppState.phase(this, AppState.PHASE_MONITORING,
                    "Google Fotos meldet „Nichts freizugeben“ (Nothing to free up). "
                            + "Versuch " + refused + "/" + NOTHING_TO_FREE_ROUNDS + " in 15 Minuten.");
            return;
        }
        // Ebene 1 — Ressourcen-IDs: Auf dem Pixel läuft wahrscheinlich eine ältere Fotos-Fassung,
        // deren Wortlaut niemand mehr kennt; Framework-IDs (android:id/button1 = Positiv-Knopf
        // eines Dialogs) sind dagegen seit API 1 stabil. Gilt nur im verifizierten Freigabe-Dialog:
        // Titelknoten mit Frage + Freigabe-Semantik, dann button1. Alles andere fällt auf
        // Wortlaut zurück — alte Wortlisten bleiben, weil die alte Fassung sie noch zeigt.
        if (findFreeUpDialogTitle(nodes) != null) {
            NodeText positive = findPositiveButton(nodes);
            if (positive != null && System.currentTimeMillis() - lastActionAt >= 2_000L
                    && click(positive.node)) {
                lastActionAt = System.currentTimeMillis();
                prefs.edit().putLong("verifyAfter", System.currentTimeMillis() + 20_000L)
                        .putInt("freeUpRound", 0).apply();
                AppState.phase(this, AppState.PHASE_VERIFY,
                        "Freigabe über Dialog-Knopf bestätigt. Prüfe danach, welche überwachten Dateien Google Fotos wirklich entfernt hat.");
                return;
            }
        }
        NodeText confirm = findConfirm(nodes);
        if (confirm == null) {
            retryFreeUpNavigation(nodes, prefs);
            return;
        }
        if (System.currentTimeMillis() - lastActionAt < 2_000L) return;
        if (click(confirm.node)) {
            lastActionAt = System.currentTimeMillis();
            prefs.edit().putLong("verifyAfter", System.currentTimeMillis() + 20_000L)
                    .putInt("freeUpRound", 0).apply();
            AppState.phase(this, AppState.PHASE_VERIFY,
                    "Freigabe bestätigt. Prüfe danach, welche überwachten Dateien Google Fotos wirklich entfernt hat.");
        }
    }

    private static NodeText findFreeUpDialogTitle(List<NodeText> nodes) {
        // Dialogtitel sind kurz, enden mit Fragezeichen und tragen Freigabe-Semantik —
        // unabhängig davon, ob die Fassung „Vom Gerät löschen?“ oder anders fragt.
        for (NodeText item : nodes) {
            if (item.text == null || item.text.length() > 80 || item.text.indexOf('?') < 0) continue;
            if (containsAny(item.text, "freigeben", "free up")
                    || (containsAny(item.text, "lösch", "entfern", "delete", "remove")
                        && containsAny(item.text, "gerät", "device", "element", "foto", "video",
                            "photo", "item", "media", "speicher", "storage", "space"))) {
                return item;
            }
        }
        return null;
    }

    private static NodeText findPositiveButton(List<NodeText> nodes) {
        for (NodeText item : nodes) {
            if (item.viewId != null
                    && ("android:id/button1".equals(item.viewId) || item.viewId.endsWith("/button1"))) {
                if (clickableNode(item.node) != null) return item;
            }
        }
        return null;
    }

    private static void collect(AccessibilityNodeInfo node, List<NodeText> out) {
        if (node == null) return;
        String text = "";
        if (node.getText() != null) text += node.getText().toString() + " ";
        if (node.getContentDescription() != null) text += node.getContentDescription().toString() + " ";
        if (Build.VERSION.SDK_INT >= 28) {
            // Manche Google-Fotos-Knöpfe tragen ihre Beschriftung nur als Tooltip.
            try {
                CharSequence tip = node.getTooltipText();
                if (tip != null) text += tip.toString();
            } catch (Exception ignored) { }
        }
        String viewId = null;
        try {
            CharSequence rawId = node.getViewIdResourceName();
            if (rawId != null) viewId = rawId.toString();
        } catch (Exception ignored) { }
        text = normalize(text);
        if (!text.isEmpty() || viewId != null) out.add(new NodeText(node, text, viewId));
        for (int i = 0; i < node.getChildCount(); i++) collect(node.getChild(i), out);
    }

    private static String allText(List<NodeText> nodes) {
        StringBuilder out = new StringBuilder();
        for (NodeText item : nodes) out.append(item.text).append('\n');
        return out.toString();
    }

    private static NodeText find(List<NodeText> nodes, String... needles) {
        for (NodeText item : nodes) {
            for (String needle : needles) if (item.text.contains(normalize(needle))) return item;
        }
        return null;
    }

    private static boolean isFreeUpHint(String text) {
        // „Du kannst keinen Speicherplatz freigeben“ ist ein Hinweis auf der Seite, nicht der
        // Menüpunkt — enthält aber denselben Wortlaut.
        return containsAny(text,
                "keinen speicherplatz", "nichts freizugeben", "kein speicherplatz",
                "cannot free up", "nothing to free", "no space to free up", "nothing to free up", "can't free up");
    }

    private static NodeText findFreeUp(List<NodeText> nodes) {
        // Ebene 1 — Ressourcen-IDs: stabil über Sprachen und die meisten Fassungen.
        // Geändert hat sich am Wortlaut schon oft etwas, an Aktions-IDs selten.
        for (NodeText item : nodes) {
            if (isFreeUpHint(item.text) || clickableNode(item.node) == null) continue;
            if (item.viewId != null) {
                String id = item.viewId.toLowerCase(Locale.ROOT);
                if (id.contains("free_up") || id.contains("freeup")) return item;
            }
        }
        // Der erste Texttreffer durfte bisher zählen — und der war der Hinweis, weil „speicherplatz
        // freigeben“ in beiden steckt. Die App blieb dann auf der Seite stehen und hat den echten
        // Menüpunkt nie erreicht. Jetzt: Hinweis überspringen und nur nehmen, was klickbar ist.
        for (NodeText item : nodes) {
            if (isFreeUpHint(item.text) || clickableNode(item.node) == null) continue;
            if (containsAny(item.text,
                    "speicherplatz auf diesem gerät freigeben", "speicherplatz auf dem gerät freigeben",
                    "gerätespeicherplatz freigeben", "speicherplatz für neue fotos freigeben",
                    "speicherplatz freigeben", "speicher freigeben", "free up space on this device",
                    "free up space on device", "free up device storage", "free up space", "free up")) {
                return item;
            }
        }
        for (NodeText item : nodes) {
            if (isFreeUpHint(item.text) || clickableNode(item.node) == null) continue;
            if (item.text.matches("(?s).*[0-9]+([,.][0-9]+)?\\s*(mb|gb).*freigeben.*")
                    || item.text.matches("(?s).*[0-9]+([,.][0-9]+)?\\s*(mb|gb).*free\\s*up.*")
                    || item.text.matches("(?s).*free\\s*up.*[0-9]+([,.][0-9]+)?\\s*(mb|gb).*")) {
                return item;
            }
        }
        return null;
    }

    private static NodeText findConfirm(List<NodeText> nodes) {
        // Bisher reichte der erste Texttreffer — und der landete fast immer auf einem
        // Beschreibungssatz des Dialogs. Dessen Klick wandert zu einem beliebigen Container,
        // tut nichts, und der Bildschirm stand still. Jetzt: kurze Knopfbeschriftung,
        // kein Abbruch-Text, und nur was wirklich klickbar ist.
        for (NodeText item : nodes) {
            if (isConfirmText(item.text) && clickableNode(item.node) != null) return item;
        }
        return null;
    }

    private static boolean isConfirmText(String text) {
        if (text == null || text.length() > 60) return false;
        if (containsAny(text, "abbrechen", "cancel", "später", "later", "not now", "dismiss", "nein", "no")) return false;
        // Fragen sind Überschriften oder Beschreibungssätze, keine Knöpfe. Ein Knoten kann
        // beides in einem Text liefern ("Vom Gerät löschen? Das Element bleibt ..."),
        // deshalb schließt ein Fragezeichen im Text den Kandidaten aus.
        if (text.indexOf('?') >= 0) return false;
        // Getrennte, lesbare Regeln für Größen-, Mengen- und Aktionsangaben.
        boolean groesse = text.matches("(?s).*[0-9]([.,][0-9]+)?\\s*(kb|mb|gb).*");
        boolean anzahl = text.matches("(?s).*[0-9]+\\s*(elemente?|fotos?|videos?|items?).*")
                || text.matches("(?s).*\\([0-9]+\\).*"); // z.B. "Delete (15)" oder "Vom Gerät löschen (15)"
        boolean wirkung = containsAny(text, "freigeben", "free up", "entfernen", "löschen", "remove", "delete");

        if ((groesse || anzahl) && wirkung) return true;

        // Eindeutige Aktionsknöpfe sowohl als Phrasen als auch als Ein-Wort-Buttons
        return containsAny(text,
                "vom gerät entfernen", "vom gerät löschen", "speicherplatz freigeben",
                "jetzt freigeben", "jetzt löschen", "jetzt entfernen",
                "elemente löschen", "elemente entfernen", "fotos löschen", "videos löschen",
                "remove from device", "delete from device", "free up space",
                "delete from this device", "remove from this device",
                "free up now", "delete now", "remove now",
                "delete photos", "delete videos", "delete items", "remove items")
                || text.equals("delete") || text.equals("löschen")
                || text.equals("free up") || text.equals("freigeben")
                || text.equals("allow") || text.equals("zulassen");
    }

    private void retryFreeUpNavigation(List<NodeText> nodes, SharedPreferences prefs) {
        int round = prefs.getInt("freeUpRound", 0) + 1;
        AppState.log(this, "Versuch " + round + "/" + FREE_UP_ROUNDS + " ohne Bestätigungsknopf. Bildschirmtexte: "
                + screenSummary(nodes, 4000, true));
        if (round >= FREE_UP_ROUNDS) {
            // Erst nach mehreren Beobachtungen hält die Automatik an: bis dahin ist ein
            // zugefallener oder unvermuteter Bildschirm kein Grund, jemanden zu holen.
            AppState.phase(this, AppState.PHASE_ERROR,
                    FREE_UP_ROUNDS + " Versuche ohne eindeutig erkennbaren, klickbaren Freigabe-Knopf. "
                            + "Es wurde nichts freigegeben. Zu melden: " + screenSummary(nodes, 180)
                            + " … (vollständig im Protokoll)");
            return;
        }
        // Zurück schließt einen Dialogrest, dann sucht die Automatik den Menüpunkt von vorn.
        performGlobalAction(GLOBAL_ACTION_BACK);
        prefs.edit().putInt("freeUpRound", round)
                .putLong("nextAttemptAt", System.currentTimeMillis() + FREE_UP_ROUND_SPACING).apply();
        AppState.phase(this, AppState.PHASE_OPEN_FREE_UP,
                "Kein Bestätigungsdialog auf dem Bildschirm; „Speicherplatz freigeben“ wird neu gesucht "
                        + "(Versuch " + round + "/" + FREE_UP_ROUNDS + ").");
    }

    private static String screenSummary(List<NodeText> nodes, int maxChars) {
        return screenSummary(nodes, maxChars, false);
    }

    private static String screenSummary(List<NodeText> nodes, int maxChars, boolean withIds) {
        StringBuilder out = new StringBuilder();
        for (NodeText item : nodes) {
            if (out.length() > 0) out.append(" | ");
            out.append(item.text);
            // View-IDs machen künftige Brüche selbstdiagnostizierend: Das Protokoll zeigt,
            // welche IDs die installierte Fotos-Fassung wirklich benutzt — Pinnen statt Raten.
            if (withIds && item.viewId != null) {
                String shortId = item.viewId;
                int slash = shortId.lastIndexOf('/');
                if (slash >= 0) shortId = shortId.substring(slash + 1);
                out.append(" [#").append(shortId).append(']');
            }
            if (out.length() > maxChars) { out.append(" …"); break; }
        }
        return out.length() == 0 ? "keine lesbaren Texte" : out.toString();
    }

    private static boolean containsAny(String text, String... needles) {
        return firstMatch(text, needles) != null;
    }

    /** Der erste Treffer, nicht nur „irgend einer“: die Automatik meldet den Wortlaut. */
    private static String firstMatch(String text, String... needles) {
        for (String needle : needles) if (text.contains(normalize(needle))) return needle;
        return null;
    }

    private static String normalize(String text) {
        return text == null ? "" : text.trim().toLowerCase(Locale.GERMANY).replace('\u00a0', ' ');
    }

    private static AccessibilityNodeInfo clickableNode(AccessibilityNodeInfo node) {
        AccessibilityNodeInfo current = node;
        for (int i = 0; current != null && i < 6; i++) {
            if (current.isClickable()) return current;
            current = current.getParent();
        }
        return null;
    }

    private static boolean click(AccessibilityNodeInfo node) {
        AccessibilityNodeInfo target = clickableNode(node);
        return target != null && target.performAction(AccessibilityNodeInfo.ACTION_CLICK);
    }

    private boolean claimFreedFiles() {
        SharedPreferences prefs = AppState.prefs(this);
        List<String> paths = new ArrayList<>();
        for (String line : prefs.getString("batchPaths", "").split("\\n")) {
            if (!line.trim().isEmpty()) paths.add(line.trim());
        }
        if (paths.isEmpty()) {
            AppState.phase(this, AppState.PHASE_ERROR,
                    "Die vorgemerkte Dateiliste fehlt. Es wurde nichts freigegeben.");
            return false;
        }
        int missing = 0;
        for (String path : paths) if (!new File(path).exists()) missing++;
        if (missing == 0) return true;
        // Fehlende Batchdateien sind der Beleg, dass Google Fotos freigegeben hat — egal, ob
        // die App selbst oder ein Mensch den Knopf gedrückt hat. Der Rückbeleg richtet sich
        // ohnehin nach dem tatsächlichen Bestand, also geht die Buchführung nie verloren.
        prefs.edit().putLong("verifyAfter", System.currentTimeMillis() + 5_000L)
                .putInt("freeUpRound", 0).apply();
        AppState.log(this, missing + " von " + paths.size()
                + " Batchdateien sind vom Pixel verschwunden — Freigabe war erfolgreich.");
        AppState.phase(this, AppState.PHASE_VERIFY,
                missing + " von " + paths.size() + " Batchdateien sind vom Pixel verschwunden. "
                        + "Rückbeleg wird aus dem Dateibestand geschrieben.");
        return false;
    }

    private boolean reconcileNewFiles(boolean closeDialog) {
        SharedPreferences prefs = AppState.prefs(this);
        HashSet<String> known = new HashSet<>();
        for (String line : prefs.getString("batchPaths", "").split("\\n")) {
            if (!line.trim().isEmpty()) known.add(line.trim());
        }
        MediaFolderScanner scanner = new MediaFolderScanner(this);
        MediaFolderScanner.Snapshot current = MediaFolderScanner.scanAllCached(this);
        // Abgelehnte Dateien bleiben auch bei einer Nachlieferung außen vor: sonst legte
        // dieselbe Datei Google Fotos noch einmal vor, während ihr Urteil schon beim Server liegt.
        List<String> added = new ArrayList<>();
        for (String path : AppState.withoutRefused(this, current.paths)) {
            if (!known.contains(path)) added.add(path);
        }
        if (added.isEmpty()) return true;

        known.addAll(added);
        List<String> merged = new ArrayList<>(known);
        java.util.Collections.sort(merged);
        scanner.mediaScan(added);
        prefs.edit()
                .putString("batchPaths", join(merged))
                .putLong("batchStartedAt", System.currentTimeMillis())
                .putBoolean("sawActiveBackup", false)
                .putInt("completeStreak", 0)
                .putLong("lastCompleteAt", 0L)
                .apply();
        if (closeDialog) performGlobalAction(GLOBAL_ACTION_BACK);
        AppState.phase(this, AppState.PHASE_WAIT_BACKUP,
                added.size() + " weitere Dateien sind eingetroffen. Sicherungsprüfung beginnt deshalb erneut.");
        return false;
    }

    private static String join(List<String> values) {
        StringBuilder out = new StringBuilder();
        for (String value : values) { if (out.length() > 0) out.append('\n'); out.append(value); }
        return out.toString();
    }

    @Override public void onInterrupt() {
        AppState.log(this, "Bedienungshilfe wurde unterbrochen.");
    }

    @Override public void onDestroy() {
        handler.removeCallbacksAndMessages(null);
        super.onDestroy();
    }

    private static final class NodeText {
        final AccessibilityNodeInfo node;
        final String text;
        final String viewId;
        NodeText(AccessibilityNodeInfo node, String text, String viewId) {
            this.node = node; this.text = text; this.viewId = viewId;
        }
    }
}
