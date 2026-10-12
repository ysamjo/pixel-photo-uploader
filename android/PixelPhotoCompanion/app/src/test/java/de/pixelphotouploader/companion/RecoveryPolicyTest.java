package de.pixelphotouploader.companion;

import org.junit.Test;
import static org.junit.Assert.*;

public class RecoveryPolicyTest {
    @Test public void transientErrorsIncludingOldPausedErrorAreRetried() {
        assertTrue(RecoveryPolicy.retryable("Google Fotos meldet einen Sicherungsfehler („backup paused“). Es wurde nichts freigegeben."));
        assertTrue(RecoveryPolicy.retryable("Google Fotos zeigt seit 30 Minuten keinen Menüpunkt."));
        assertTrue(RecoveryPolicy.retryable("6 Versuche ohne eindeutig erkennbaren, klickbaren Freigabe-Knopf."));
        assertTrue(RecoveryPolicy.retryable("Überwachungsfehler: Datenträger vorübergehend nicht verfügbar"));
        assertTrue(RecoveryPolicy.retryable("Dateien wurden lokal freigegeben, aber der Server-Rückbeleg konnte nicht geschrieben werden: IO"));
        assertTrue(RecoveryPolicy.retryable("Das Absage-Urteil konnte nicht als Rückbeleg übergeben werden: IO"));
        assertTrue(RecoveryPolicy.retryable("Rückbeleg für 38 freigegebene Dateien geschrieben. Die Automatik bleibt angehalten; erst „Fehler zurücksetzen“ lässt sie weiterlaufen."));
    }

    @Test public void missingPrerequisitesAndTimeoutNeverBecomeAnAutomaticReset() {
        assertFalse(RecoveryPolicy.retryable("Google Fotos ist nicht installiert."));
        assertFalse(RecoveryPolicy.retryable("Google Fotos wurde innerhalb von 72 Stunden nicht fertig."));
        for (String reason : new String[]{"account storage full", "account storage is full", "kontospeicher voll", "backup is off", "backup off", "backup turned off", "sicherung deaktiviert", "sicherung ist deaktiviert", "sicherung ausgeschaltet"}) {
            assertFalse(reason, RecoveryPolicy.retryable("Google Fotos meldet einen Sicherungsfehler („" + reason + "“)."));
        }
        assertFalse(RecoveryPolicy.retryable("Unbekannter Fehler"));
    }

    @Test public void repeatFailuresBackOffButRemainRecoverable() {
        assertEquals(300_000L, RecoveryPolicy.delayMillis(0));
        assertEquals(900_000L, RecoveryPolicy.delayMillis(1));
        assertEquals(1_800_000L, RecoveryPolicy.delayMillis(2));
        assertEquals(1_800_000L, RecoveryPolicy.delayMillis(Integer.MAX_VALUE));
    }

    @Test public void recoveryRequiresFreshBackupConfirmationForExistingBatch() {
        assertEquals("WAIT_BACKUP", RecoveryPolicy.resumePhase(true));
        assertEquals("MONITORING", RecoveryPolicy.resumePhase(false));
    }
}
