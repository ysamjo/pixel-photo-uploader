package de.pixelphotouploader.companion;

import java.io.File;

/**
 * Resilio Sync verschiebt serverseitig geloeschte Batches standardmaessig in
 * .sync/Archive. Auf einem Telefon mit 24 GiB Nutzerspeicher fuehrt das nach
 * wenigen 5-GiB-Batches zu vollem Geraetespeicher (ENOSPC).
 *
 * Diese Klasse leert den Inhalt von .sync/Archive zuverlaessig, laesst den
 * Ordner selbst aber bestehen.
 */
final class ResilioArchiveCleaner {
    private ResilioArchiveCleaner() {}

    static int purge(File archiveDir) {
        if (archiveDir == null || !archiveDir.isDirectory()) return 0;
        return deleteChildren(archiveDir);
    }

    private static int deleteChildren(File dir) {
        int count = 0;
        File[] files = dir.listFiles();
        if (files == null) return 0;
        for (File file : files) {
            if (file.isDirectory()) {
                count += deleteChildren(file);
            }
            if (file.delete()) {
                count++;
            }
        }
        return count;
    }
}
