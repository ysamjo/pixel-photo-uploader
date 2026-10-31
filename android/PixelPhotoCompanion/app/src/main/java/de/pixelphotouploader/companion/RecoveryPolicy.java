package de.pixelphotouploader.companion;

import java.util.Locale;

/** Wiederholungen reparieren Bedienung und Wartezustaende, keine fehlenden Voraussetzungen. */
final class RecoveryPolicy {
    private RecoveryPolicy() {}

    static long delayMillis(int attempts) {
        if (attempts <= 0) return 5 * 60_000L;
        if (attempts == 1) return 15 * 60_000L;
        return 30 * 60_000L;
    }

    static boolean retryable(String detail) {
        String text = detail.toLowerCase(Locale.ROOT);
        if (text.contains("nicht installiert") || text.contains("72 stunden")
                || text.contains("kontospeicher voll") || text.contains("account storage")
                || text.contains("sicherung deaktiviert") || text.contains("sicherung ist deaktiviert")
                || text.contains("sicherung aus") || text.contains("backup is off")
                || text.contains("backup off") || text.contains("backup turned off")) return false;
        return text.startsWith("überwachungsfehler:")
                || text.startsWith("google fotos meldet einen sicherungsfehler")
                || text.startsWith("google fotos zeigt seit 30 minuten")
                || text.contains("stagniert")
                || text.contains("ohne eindeutig erkennbaren, klickbaren freigabe-knopf")
                || text.contains("rückbeleg konnte nicht geschrieben")
                || text.contains("nicht als rückbeleg übergeben")
                || (text.contains("automatik bleibt angehalten") && text.contains("fehler zurücksetzen"));
    }

    static String resumePhase(boolean hasBatch) {
        // Ein Freigabedialog muss nach einem Fehler erneut durch die Sicherungspruefung.
        return hasBatch ? "WAIT_BACKUP" : "MONITORING";
    }
}
