package de.pixelphotouploader.companion;

import android.content.Context;
import android.os.Environment;
import android.os.StatFs;

import java.io.File;
import java.util.List;
import java.util.Locale;

/**
 * Freier und belegter Geraetespeicher des Pixels.
 *
 * Die App kannte bisher nur die Medien-Bytes in den ueberwachten Ordnern; wie voll
 * das Telefon wirklich war, stand nirgends. Der Server rechnet seine Staging-Kappe
 * seit dieser Messung auf den echten Platzrueckstand des Telefons zurueck — ohne
 * diese Zahl kann er nur ueber die Batchgroesse raten.
 *
 * Rechnung, Schwellen und Texte sind bewusst frei von Android-Aufrufen: nur
 * {@link #probe(File)} liest den Datentraeger, alles andere ist pruefbar.
 */
final class DeviceStorage {
    static final long GIB = 1024L * 1024L * 1024L;

    /** Unter dieser Schwelle warnt die App sichtbar in Status und Benachrichtigung. */
    static final long WARN_GIB = 3L;
    /** Unter dieser Schwelle wird kein neuer Batch mehr an Google Fotos uebergeben. */
    static final long FLOOR_GIB = 1L;

    static final class Usage {
        final long freeBytes;
        final long totalBytes;

        Usage(long freeBytes, long totalBytes) {
            this.freeBytes = Math.max(0L, freeBytes);
            this.totalBytes = Math.max(0L, totalBytes);
        }

        long usedBytes() { return Math.max(0L, totalBytes - freeBytes); }

        double usedPercent() {
            return totalBytes <= 0L ? 0.0 : 100.0 * usedBytes() / totalBytes;
        }

        boolean measurable() { return totalBytes > 0L; }
    }

    private DeviceStorage() {}

    /** Der ueberwachte Ordner liegt im selben /data-Volume wie die Resilio-Freigabe. */
    static File measurementPath(Context context) {
        List<String> folders = AppState.folderPaths(context);
        if (!folders.isEmpty()) return new File(folders.get(0));
        return Environment.getExternalStorageDirectory();
    }

    /** Liest den Datentraeger; null, wenn der Pfad nicht messbar ist. */
    static Usage probe(File path) {
        try {
            StatFs stat = new StatFs(path.getAbsolutePath());
            // getAvailableBytes statt getFreeBytes: der Wurzel-Vorbehalt ist fuer Apps
            // nicht nutzbar und wuerde den freien Platz schoenrechnen.
            return new Usage(stat.getAvailableBytes(), stat.getTotalBytes());
        } catch (Exception error) {
            return null;
        }
    }

    static boolean below(long freeBytes, long thresholdGib) {
        return freeBytes < thresholdGib * GIB;
    }

    /** Warnstufe fuer Meldung und Speicherbericht. */
    static String warnLevel(long freeBytes) {
        if (below(freeBytes, FLOOR_GIB)) return "floor";
        if (below(freeBytes, WARN_GIB)) return "warn";
        return "ok";
    }

    static String describe(Usage usage) {
        if (usage == null || !usage.measurable()) return "Telefonspeicher nicht messbar";
        return describe(usage.freeBytes, usage.totalBytes);
    }

    static String describe(long freeBytes, long totalBytes) {
        if (totalBytes <= 0L) return "Telefonspeicher nicht messbar";
        Usage usage = new Usage(freeBytes, totalBytes);
        return String.format(Locale.GERMANY, "%.2f GiB frei von %.2f GiB (%.0f %% belegt)",
                usage.freeBytes / (double) GIB, usage.totalBytes / (double) GIB, usage.usedPercent());
    }

    /** Nutzersichtbarer Warntext oder null, solange genug Platz ist. */
    static String warning(Usage usage) {
        if (usage == null || !usage.measurable()) return null;
        String level = warnLevel(usage.freeBytes);
        if ("floor".equals(level)) {
            return "Telefonspeicher fast voll (" + describe(usage)
                    + "). Kein neuer Batch, bis Platz frei ist.";
        }
        if ("warn".equals(level)) {
            return "Telefonspeicher wird knapp: " + gib(usage.freeBytes) + " frei.";
        }
        return null;
    }

    static String gib(long bytes) {
        return String.format(Locale.GERMANY, "%.2f GiB", bytes / (double) GIB);
    }
}
