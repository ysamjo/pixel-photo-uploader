package de.pixelphotouploader.companion;

import org.junit.Test;
import static org.junit.Assert.*;

public class BackupProgressTest {
    @Test public void repeatedCounterReachesStallDespiteFrequentPolling() {
        long progress = 1000L;
        for (long now = 6000L; now <= 21 * 60_000L; now += 5000L) {
            progress = BackupProgress.observedAt(52, 52, progress, now);
        }
        assertEquals(1000L, progress);
        assertTrue(BackupProgress.stalled(progress, 0L, 21 * 60_000L, 20 * 60_000L));
    }
    @Test public void decreasingCounterDelaysStallAndRisingCounterDoesNot() {
        long progress = BackupProgress.observedAt(52, 51, 1000L, 600_000L);
        assertEquals(600_000L, progress);
        progress = BackupProgress.observedAt(51, 55, progress, 700_000L);
        assertEquals(600_000L, progress);
        assertFalse(BackupProgress.stalled(progress, 0L, 800_000L, 300_000L));
        assertTrue(BackupProgress.stalled(progress, 0L, 900_000L, 300_000L));
    }
    @Test public void freeUpProbeHasSeparateCooldownWithoutFakingProgress() {
        assertFalse(BackupProgress.stalled(1000L, 1_200_000L, 1_300_000L, 300_000L));
        assertTrue(BackupProgress.stalled(1000L, 1_200_000L, 1_500_000L, 300_000L));
    }
}
