package de.pixelphotouploader.companion;

import org.junit.Test;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;

public class DeviceStorageTest {
    private static final long GIB = DeviceStorage.GIB;

    @Test public void warnstufeTrenntHinweisVonDerHartenKante() {
        // Ueber der Warnschwelle ist alles ruhig.
        assertEquals("ok", DeviceStorage.warnLevel(9L * GIB));
        assertNull(DeviceStorage.warning(new DeviceStorage.Usage(9L * GIB, 24L * GIB)));
        // Zwischen harter Kante und Warnschwelle wird gewarnt, aber weitergearbeitet.
        assertEquals("warn", DeviceStorage.warnLevel(2L * GIB));
        assertTrue(DeviceStorage.warning(new DeviceStorage.Usage(2L * GIB, 24L * GIB))
                .startsWith("Telefonspeicher wird knapp"));
        // Unter der harten Kante wird kein neuer Batch mehr uebergeben.
        assertEquals("floor", DeviceStorage.warnLevel(512L * 1024L * 1024L));
        assertTrue(DeviceStorage.warning(new DeviceStorage.Usage(512L * 1024L * 1024L, 24L * GIB))
                .contains("Kein neuer Batch"));
        assertTrue(DeviceStorage.below(512L * 1024L * 1024L, DeviceStorage.FLOOR_GIB));
        assertTrue(DeviceStorage.below(2L * GIB, DeviceStorage.WARN_GIB));
        assertFalse(DeviceStorage.below(4L * GIB, DeviceStorage.WARN_GIB));
    }

    @Test public void beschreibungNenntFreieUndBelegteBytesDeutsch() {
        assertEquals("8,20 GiB frei von 24,00 GiB (66 % belegt)",
                DeviceStorage.describe(8_804_682_956L, 24L * GIB));
        assertEquals("0,50 GiB", DeviceStorage.gib(512L * 1024L * 1024L));
    }

    @Test public void nichtMessbarerDatentraegerWarntNichtUndRundetNicht() {
        DeviceStorage.Usage usage = new DeviceStorage.Usage(-5L, 0L);
        assertFalse(usage.measurable());
        assertEquals(0L, usage.usedBytes());
        assertEquals(0.0, usage.usedPercent(), 0.0001);
        assertNull(DeviceStorage.warning(null));
        assertNull(DeviceStorage.warning(usage));
        assertEquals("Telefonspeicher nicht messbar", DeviceStorage.describe(usage));
        assertEquals("Telefonspeicher nicht messbar", DeviceStorage.describe(0L, 0L));
    }
}
