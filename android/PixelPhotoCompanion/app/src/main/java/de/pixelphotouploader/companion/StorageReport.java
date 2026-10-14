package de.pixelphotouploader.companion;

import android.content.Context;

import org.json.JSONObject;

import java.io.File;
import java.io.FileWriter;

/**
 * Speicherbericht des Pixels fuer den Server.
 *
 * Bis hierher war der freie Telefonspeicher nur auf dem Geraet selbst sichtbar, und
 * der Uploader konnte seine Staging-Kappe nur ueber {@code BatchGiB} raten. Der
 * Bericht geht wie der Rueckbeleg durch den Resilio-Kontrollordner: dieselbe
 * Freigabe, dieselbe Atomaritaet, keine neue Berechtigung und kein zweiter Port.
 *
 * Es ist bewusst kein Rueckbeleg ({@code receipt-*.json}) und auch kein Protokoll:
 * eigener Name, eigenes Format. Der Server liest ihn rein lesend und leitet daraus
 * nur die Kapazitaet ab.
 */
final class StorageReport {
    static final String FILE_NAME = "pixel-storage.json";

    private StorageReport() {}

    static File write(Context context, DeviceStorage.Usage usage,
                      StorageResidue.Inventory inventory, StorageResidue.Reclaimed reclaimed)
            throws Exception {
        String configured = AppState.prefs(context).getString("controlFolder",
                AppState.DEFAULT_CONTROL_FOLDER);
        File folder = new File(configured);
        if (!folder.exists() && !folder.mkdirs()) {
            throw new IllegalStateException("Kontrollordner konnte nicht erstellt werden: " + folder);
        }
        if (!folder.isDirectory() || !folder.canWrite()) {
            throw new IllegalStateException("Kontrollordner ist nicht beschreibbar: " + folder);
        }

        JSONObject report = new JSONObject();
        report.put("version", 1);
        report.put("observedAtEpochMs", System.currentTimeMillis());
        report.put("freeBytes", usage.freeBytes);
        report.put("totalBytes", usage.totalBytes);
        report.put("usedPercent", Math.round(usage.usedPercent() * 10.0) / 10.0);
        report.put("warnLevel", DeviceStorage.warnLevel(usage.freeBytes));
        if (inventory != null) {
            report.put("partialCount", inventory.partials.size());
            report.put("partialBytes", inventory.partialBytes);
            report.put("tempCount", inventory.temps.size());
            report.put("tempBytes", inventory.tempBytes);
        }
        if (reclaimed != null) {
            report.put("reclaimedCount", reclaimed.count());
            report.put("reclaimedBytes", reclaimed.bytes);
        }

        File temp = new File(folder, "." + FILE_NAME + ".tmp");
        File target = new File(folder, FILE_NAME);
        try (FileWriter writer = new FileWriter(temp, false)) {
            writer.write(report.toString(2));
            writer.write("\n");
            writer.flush();
        }
        if (!temp.renameTo(target)) {
            // Wie beim Rueckbeleg: blockiert Resilio die .tmp, direkt schreiben.
            try (FileWriter direct = new FileWriter(target, false)) {
                direct.write(report.toString(2));
                direct.write("\n");
                direct.flush();
            } catch (Exception error) {
                temp.delete();
                throw new IllegalStateException(
                        "Speicherbericht konnte weder atomar noch direkt geschrieben werden: "
                                + error.getMessage());
            }
            temp.delete();
        }
        return target;
    }
}
