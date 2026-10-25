package de.pixelphotouploader.companion;

import android.content.ContentResolver;
import android.content.Context;
import android.database.Cursor;
import android.net.Uri;
import android.provider.MediaStore;

import java.io.File;
import java.util.ArrayList;
import java.util.List;

/**
 * Bereinigt verwaiste MediaStore-Einträge (Ghost-Einträge).
 *
 * Wenn Resilio Sync oder eine Server-Freigabe Dateien auf dem Dateisystem löscht,
 * bleiben die entsprechenden Zeilen in MediaStore.Images.Media und MediaStore.Video.Media
 * erhalten. Google Fotos gerät dadurch in eine permanente 24/7-Schleife
 * ("Preparing backup" -> "Scanning your photo library").
 *
 * Diese Klasse erkennt und löscht MediaStore-Einträge unter den überwachten Ordnern,
 * deren Dateien auf der Festplatte nicht mehr existieren.
 */
final class MediaStoreCleaner {
    private MediaStoreCleaner() {}

    static int purgeGhosts(Context context) {
        int totalDeleted = 0;
        for (String folder : AppState.folderPaths(context)) {
            totalDeleted += purgeGhostsForFolder(context, folder);
        }
        return totalDeleted;
    }

    private static int purgeGhostsForFolder(Context context, String folder) {
        int deleted = 0;
        deleted += purgeUri(context, MediaStore.Images.Media.EXTERNAL_CONTENT_URI, folder);
        deleted += purgeUri(context, MediaStore.Video.Media.EXTERNAL_CONTENT_URI, folder);
        return deleted;
    }

    private static int purgeUri(Context context, Uri contentUri, String folder) {
        ContentResolver resolver = context.getContentResolver();
        String prefix = folder.endsWith("/") ? folder : folder + "/";
        String selection = MediaStore.MediaColumns.DATA + " LIKE ?";
        String[] selectionArgs = new String[]{prefix + "%"};
        String[] projection = new String[]{MediaStore.MediaColumns._ID, MediaStore.MediaColumns.DATA};

        List<Long> ghostIds = new ArrayList<>();
        try (Cursor cursor = resolver.query(contentUri, projection, selection, selectionArgs, null)) {
            if (cursor != null) {
                int idIdx = cursor.getColumnIndexOrThrow(MediaStore.MediaColumns._ID);
                int dataIdx = cursor.getColumnIndexOrThrow(MediaStore.MediaColumns.DATA);
                while (cursor.moveToNext()) {
                    long id = cursor.getLong(idIdx);
                    String path = cursor.getString(dataIdx);
                    if (path != null && !new File(path).exists()) {
                        ghostIds.add(id);
                    }
                }
            }
        } catch (Exception e) {
            AppState.log(context, "Fehler beim Suchen von MediaStore-Geistern: " + e.getMessage());
            return 0;
        }

        if (ghostIds.isEmpty()) return 0;

        int deletedCount = 0;
        int chunkSize = 100;
        for (int i = 0; i < ghostIds.size(); i += chunkSize) {
            int end = Math.min(i + chunkSize, ghostIds.size());
            List<Long> chunk = ghostIds.subList(i, end);
            StringBuilder where = new StringBuilder(MediaStore.MediaColumns._ID + " IN (");
            for (int j = 0; j < chunk.size(); j++) {
                if (j > 0) where.append(',');
                where.append(chunk.get(j));
            }
            where.append(')');
            try {
                deletedCount += resolver.delete(contentUri, where.toString(), null);
            } catch (Exception e) {
                AppState.log(context, "Fehler beim Löschen von MediaStore-Geistern: " + e.getMessage());
            }
        }

        if (deletedCount > 0) {
            AppState.log(context, deletedCount + " verwaiste MediaStore-Einträge bereinigt.");
        }
        return deletedCount;
    }
}
