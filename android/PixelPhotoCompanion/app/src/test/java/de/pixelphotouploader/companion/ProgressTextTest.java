package de.pixelphotouploader.companion;

import org.junit.Test;
import static org.junit.Assert.*;

public class ProgressTextTest {
    @Test public void readsActualRemainingCounterInBothLanguages() {
        assertEquals(13, ProgressText.remaining("Backing up · 13 items left"));
        assertEquals(1, ProgressText.remaining("1 item left"));
        assertEquals(21, ProgressText.remaining("21 Elemente verbleibend"));
        assertEquals(0, ProgressText.remaining("0 Dateien übrig"));
    }
    @Test public void scanAndCpuActivityAreNotProgress() {
        assertEquals(-1, ProgressText.remaining("Preparing backup · Scanning your photo library"));
        assertEquals(-1, ProgressText.remaining("Backup complete"));
        assertEquals(-1, ProgressText.remaining("99999999999999999999 items left"));
    }
}
