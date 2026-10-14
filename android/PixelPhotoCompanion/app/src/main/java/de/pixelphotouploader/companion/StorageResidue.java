package de.pixelphotouploader.companion;

import java.io.File;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Comparator;
import java.util.List;

/**
 * Reste in der Resilio-Freigabe, die niemand mehr anfasst.
 *
 * Zwei Sorten belegen still Platz und sind fuer die Medienpruefung unsichtbar:
 *
 * - Resilio-Teilkopien ({@code name.jpg.!sync}): bricht eine Uebertragung ab, laesst
 *   Resilio die halb geschriebene Datei liegen. Der Scanner ueberspringt sie bewusst,
 *   geloescht hat sie bisher niemand — nach einem abgebrochenen 5-GiB-Batch sind das
 *   mehrere GiB.
 * - eigene Atomar-Schreibdateien ({@code .receipt-*.tmp}): bleibt {@link ReceiptWriter}
 *   vor dem Umbenennen stehen, liegt der Rest im Kontrollordner.
 *
 * Geloescht wird nur, was eine Stunde nicht angefasst wurde. Eine <em>laufende</em>
 * Uebertragung schreibt staendig und ist damit nie betroffen; eine abgebrochene wird
 * genau dann frei, wenn sie wirklich liegt. Die Resilio-Metadaten ({@code .sync})
 * bleiben unberuehrt.
 */
final class StorageResidue {
    /** Resilio-Teilkopien; der Punkt davor ueberspringt der Mediascanner. */
    static final String PARTIAL_SUFFIX = ".!sync";
    /** Eigene Atomar-Schreibdateien aus {@link ReceiptWriter}. */
    static final String TEMP_PREFIX = ".receipt-";
    static final String TEMP_SUFFIX = ".tmp";
    /** So lange muss ein Rest unberuehrt liegen, bevor er als abgebrochen gilt. */
    static final long STALE_MILLIS = 60 * 60_000L;

    static final class Inventory {
        final List<File> partials = new ArrayList<>();
        final List<File> temps = new ArrayList<>();
        long partialBytes;
        long tempBytes;

        long bytes() { return partialBytes + tempBytes; }
        int count() { return partials.size() + temps.size(); }
        boolean empty() { return count() == 0; }
    }

    static final class Reclaimed {
        int partials;
        int temps;
        long bytes;

        int count() { return partials + temps; }
    }

    private StorageResidue() {}

    static Inventory scan(List<String> folders) {
        Inventory inventory = new Inventory();
        for (String folder : folders) collect(new File(folder), inventory);
        return inventory;
    }

    /** Nur die Kandidaten, die lange genug unberuehrt liegen. */
    static List<File> stale(Inventory inventory, long now) {
        List<File> out = new ArrayList<>();
        for (File file : inventory.partials) if (isStale(file, now)) out.add(file);
        for (File file : inventory.temps) if (isStale(file, now)) out.add(file);
        return out;
    }

    static boolean isStale(File file, long now) {
        long modified = file.lastModified();
        // lastModified() == 0 heisst unbekannt, nicht alt: im Zweifel liegen lassen.
        return modified > 0L && now - modified >= STALE_MILLIS;
    }

    /** Loescht ausschliesslich alte Resilio-Teilkopien und alte eigene Temp-Reste. */
    static Reclaimed reclaim(List<String> folders, long now) {
        Inventory inventory = scan(folders);
        Reclaimed result = new Reclaimed();
        for (File file : inventory.partials) {
            if (!isStale(file, now)) continue;
            long size = file.length();
            if (file.delete()) { result.partials++; result.bytes += size; }
        }
        for (File file : inventory.temps) {
            if (!isStale(file, now)) continue;
            long size = file.length();
            if (file.delete()) { result.temps++; result.bytes += size; }
        }
        return result;
    }

    private static void collect(File file, Inventory inventory) {
        if (file == null || !file.exists()) return;
        String name = file.getName();
        if (file.isDirectory()) {
            // Resilio-Metadaten: klein, aber tabu. Nicht hineinsehen und nicht loeschen.
            if (".sync".equalsIgnoreCase(name)) return;
            File[] children = file.listFiles();
            if (children == null) return;
            List<File> sorted = new ArrayList<>();
            Collections.addAll(sorted, children);
            Collections.sort(sorted, Comparator.comparing(File::getName));
            for (File child : sorted) collect(child, inventory);
            return;
        }
        if (name.endsWith(PARTIAL_SUFFIX) && name.length() > PARTIAL_SUFFIX.length()) {
            inventory.partials.add(file);
            inventory.partialBytes += file.length();
            return;
        }
        if (name.startsWith(TEMP_PREFIX) && name.endsWith(TEMP_SUFFIX)
                && name.length() > TEMP_PREFIX.length() + TEMP_SUFFIX.length()) {
            inventory.temps.add(file);
            inventory.tempBytes += file.length();
        }
    }
}
