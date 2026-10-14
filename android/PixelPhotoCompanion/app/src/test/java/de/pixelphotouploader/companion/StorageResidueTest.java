package de.pixelphotouploader.companion;

import org.junit.Rule;
import org.junit.Test;
import org.junit.rules.TemporaryFolder;

import java.io.File;
import java.util.Arrays;
import java.util.Collections;
import java.util.List;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

public class StorageResidueTest {
    @Rule public TemporaryFolder temp = new TemporaryFolder();

    private static final long HOUR = 60 * 60_000L;

    private File write(File file, int bytes, long ageMillis) throws Exception {
        file.getParentFile().mkdirs();
        java.io.FileOutputStream out = new java.io.FileOutputStream(file);
        try {
            out.write(new byte[bytes]);
        } finally {
            out.close();
        }
        assertTrue(file.setLastModified(System.currentTimeMillis() - ageMillis));
        return file;
    }

    @Test public void findetAlteTeilkopienUndEigeneTempResteAberKeineResilioMetadaten() throws Exception {
        File root = temp.newFolder("PixelSync");
        File batch = new File(root, "staging/Batches/b1");
        File partial = write(new File(batch, "000001-1a2b3c4d5e6f.jpg.!sync"), 4096, 3 * HOUR);
        write(new File(batch, "000002-1a2b3c4d5e6f.jpg"), 1024, 3 * HOUR);
        write(new File(batch, "_batch-manifest.json"), 64, 3 * HOUR);
        // Der Punkt davor laesst den Mediascanner sie ueberspringen; die Datei bleibt liegen.
        write(new File(batch, "000003-1a2b3c4d5e6f.jpg.!sync"), 2048, 10_000L);
        // Resilio-Metadaten sind tabu, auch wenn dort etwas wie eine Teilkopie liegt.
        write(new File(root, ".sync/ignored.jpg.!sync"), 9999, 5 * HOUR);
        File tempOld = write(new File(root, "control/.receipt-123-abc.tmp"), 512, 3 * HOUR);
        File tempFresh = write(new File(root, "control/.receipt-456-def.tmp"), 256, 1_000L);

        List<String> folders = Collections.singletonList(root.getAbsolutePath());
        StorageResidue.Inventory inventory = StorageResidue.scan(folders);
        assertEquals(2, inventory.partials.size());
        assertEquals(4096 + 2048, inventory.partialBytes);
        assertEquals(2, inventory.temps.size());
        assertEquals(512 + 256, inventory.tempBytes);

        List<File> stale = StorageResidue.stale(inventory, System.currentTimeMillis());
        assertTrue(stale.contains(partial));
        assertTrue(stale.contains(tempOld));
        assertFalse(stale.contains(tempFresh));

        StorageResidue.Reclaimed reclaimed = StorageResidue.reclaim(folders, System.currentTimeMillis());
        assertEquals(1, reclaimed.partials);
        assertEquals(1, reclaimed.temps);
        assertEquals(4096 + 512, reclaimed.bytes);
        assertFalse(partial.exists());
        assertFalse(tempOld.exists());
    }

    @Test public void laufendeUebertragungUndUnbekannteZeitBleibenLiegen() throws Exception {
        File root = temp.newFolder("PixelSync");
        File running = write(new File(root, "staging/Batches/b2/x.jpg.!sync"), 1024, 30_000L);
        File unknown = write(new File(root, "staging/Batches/b2/y.jpg.!sync"), 1024, HOUR);
        // lastModified() == 0 heisst unbekannt, nicht alt: im Zweifel liegen lassen.
        assertTrue(unknown.setLastModified(0L));

        List<String> folders = Collections.singletonList(root.getAbsolutePath());
        StorageResidue.Inventory inventory = StorageResidue.scan(folders);
        assertEquals(2, inventory.partials.size());
        StorageResidue.Reclaimed reclaimed = StorageResidue.reclaim(folders, System.currentTimeMillis());
        assertEquals(0, reclaimed.count());
        assertEquals(0L, reclaimed.bytes);
        assertTrue(running.exists());
        assertTrue(unknown.exists());
    }

    @Test public void leererUndFehlenderOrdnerSindKeinFehler() {
        StorageResidue.Inventory inventory = StorageResidue.scan(Collections.singletonList(
                new File(temp.getRoot(), "gibt-es-nicht").getAbsolutePath()));
        assertTrue(inventory.empty());
        assertEquals(0L, inventory.bytes());
        assertEquals(0, StorageResidue.reclaim(Arrays.asList("", "/gibt/es/nicht"),
                System.currentTimeMillis()).count());
    }
}
