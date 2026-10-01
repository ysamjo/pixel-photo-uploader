package de.pixelphotouploader.companion;

import android.content.Context;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.File;
import java.io.FileWriter;
import java.util.List;
import java.util.UUID;

final class ReceiptWriter {
    private ReceiptWriter() {}

    static File write(Context context, List<String> removedPaths, int remainingCount) throws Exception {
        String configured = AppState.prefs(context).getString("controlFolder",
                AppState.DEFAULT_CONTROL_FOLDER);
        File folder = new File(configured);
        if (!folder.exists() && !folder.mkdirs()) {
            throw new IllegalStateException("Kontrollordner konnte nicht erstellt werden: " + folder);
        }
        if (!folder.isDirectory() || !folder.canWrite()) {
            throw new IllegalStateException("Kontrollordner ist nicht beschreibbar: " + folder);
        }

        long now = System.currentTimeMillis();
        String id = now + "-" + UUID.randomUUID().toString().substring(0, 8);
        JSONObject receipt = new JSONObject();
        receipt.put("version", 1);
        receipt.put("receiptId", id);
        receipt.put("createdAtEpochMs", now);
        receipt.put("remainingCount", remainingCount);
        JSONArray removed = new JSONArray();
        for (String path : removedPaths) removed.put(path);
        receipt.put("removedPaths", removed);

        File temp = new File(folder, ".receipt-" + id + ".tmp");
        File target = new File(folder, "receipt-" + id + ".json");
        try (FileWriter writer = new FileWriter(temp, false)) {
            writer.write(receipt.toString(2));
            writer.write("\n");
            writer.flush();
        }
        if (!temp.renameTo(target)) {
            // Fallback: Wenn Inotify / Resilio Sync die .tmp-Datei blockiert,
            // versuchen wir direkt in die Zieldatei zu schreiben.
            try (FileWriter directWriter = new FileWriter(target, false)) {
                directWriter.write(receipt.toString(2));
                directWriter.write("\n");
                directWriter.flush();
            } catch (Exception ex) {
                temp.delete();
                throw new IllegalStateException("Rückbeleg konnte weder atomar noch direkt geschrieben werden: " + ex.getMessage());
            }
            temp.delete();
        }
        return target;
    }
}
