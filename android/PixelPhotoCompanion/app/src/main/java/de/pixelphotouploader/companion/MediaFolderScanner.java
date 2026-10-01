package de.pixelphotouploader.companion;

import android.content.Context;
import android.media.MediaScannerConnection;

import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.File;
import java.io.FileReader;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;

final class MediaFolderScanner {
    private static final Set<String> EXTENSIONS = new HashSet<>(Arrays.asList(
            "jpg","jpeg","jpe","png","gif","webp","bmp","heic","heif","tif","tiff","dng",
            "arw","cr2","cr3","nef","nrw","orf","raf","rw2","pef","srw","3gp","3g2","mp4",
            "m4v","mov","mkv","avi","wmv","mpg","mpeg","mts","m2ts","webm"));

    static final class Snapshot {
        final List<String> paths;
        final long bytes;
        Snapshot(List<String> paths, long bytes) { this.paths = paths; this.bytes = bytes; }
    }

    private final Context context;
    private final Map<String, FileStamp> previous = new HashMap<>();
    private final Map<String, Long> stableSince = new HashMap<>();

    // reconcileNewFiles läuft bei jedem Bedienungshilfen-Durchlauf (5-s-Poll plus
    // Ereignis-Bursts) auf dem Hauptthread: ein voller Baumdurchlauf pro Runde ist
    // Ruckeln + Akku. Daher ein kurzer, ordnergebundener Cache — neue Dateien
    // erscheinen spätestens nach TTL, die Batch-Kette rechnet in Minuten.
    private static final long ALL_TTL_MILLIS = 20_000L;
    private static Snapshot cachedAll = null;
    private static long cachedAllAt = 0L;
    private static String cachedFoldersKey = "";

    MediaFolderScanner(Context context) { this.context = context.getApplicationContext(); }

    Snapshot scanStable(long stableMillis) {
        long now = System.currentTimeMillis();
        Map<String, FileStamp> current = new HashMap<>();
        List<String> all = new ArrayList<>();
        for (String folder : AppState.folderPaths(context)) collect(new File(folder), current, all);

        List<String> stable = new ArrayList<>();
        long bytes = 0;
        for (String path : all) {
            FileStamp stamp = current.get(path);
            FileStamp old = previous.get(path);
            if (old != null && old.size == stamp.size && old.modified == stamp.modified) {
                if (!stableSince.containsKey(path)) stableSince.put(path, now);
                if (now - stableSince.get(path) >= stableMillis) {
                    stable.add(path);
                    bytes += stamp.size;
                }
            } else {
                stableSince.put(path, now);
            }
        }
        stableSince.keySet().retainAll(current.keySet());
        previous.clear();
        previous.putAll(current);
        Collections.sort(stable);
        return new Snapshot(stable, bytes);
    }

    Snapshot scanAll() {
        Map<String, FileStamp> current = new HashMap<>();
        List<String> all = new ArrayList<>();
        for (String folder : AppState.folderPaths(context)) collect(new File(folder), current, all);
        long bytes = 0;
        for (FileStamp stamp : current.values()) bytes += stamp.size;
        Collections.sort(all);
        return new Snapshot(all, bytes);
    }

    static synchronized Snapshot scanAllCached(Context context) {
        StringBuilder key = new StringBuilder();
        for (String folder : AppState.folderPaths(context)) key.append(folder).append('\n');
        long now = System.currentTimeMillis();
        if (cachedAll != null && now - cachedAllAt < ALL_TTL_MILLIS
                && key.toString().equals(cachedFoldersKey)) {
            return cachedAll;
        }
        MediaFolderScanner scanner = new MediaFolderScanner(context);
        cachedAll = scanner.scanAll();
        cachedAllAt = now;
        cachedFoldersKey = key.toString();
        return cachedAll;
    }

    void mediaScan(List<String> paths) {
        if (paths.isEmpty()) return;
        MediaScannerConnection.scanFile(context, paths.toArray(new String[0]), null, null);
    }

    private void collect(File file, Map<String, FileStamp> current, List<String> all) {
        if (!file.exists() || !file.canRead()) return;
        if (file.isDirectory()) {
            if ("control".equalsIgnoreCase(file.getName()) || ".sync".equalsIgnoreCase(file.getName())) return;
            if ("batches".equalsIgnoreCase(file.getName()) || "WindowsBatches".equalsIgnoreCase(file.getName()) || "staging".equalsIgnoreCase(file.getName())) {
                File[] batches = file.listFiles();
                if (batches != null) {
                    for (File batch : batches) if (batch.isDirectory() && completeWindowsBatch(batch)) collectChildren(batch, current, all);
                }
                return;
            }
            File[] children = file.listFiles();
            if (children != null) for (File child : children) collect(child, current, all);
            return;
        }
        String name = file.getName();
        if (name.endsWith(".!sync") || name.startsWith(".sync") || name.startsWith(".")) return;
        int dot = name.lastIndexOf('.');
        if (dot < 0 || !EXTENSIONS.contains(name.substring(dot + 1).toLowerCase(Locale.ROOT))) return;
        String path = file.getAbsolutePath();
        current.put(path, new FileStamp(file.length(), file.lastModified()));
        all.add(path);
    }

    private void collectChildren(File folder, Map<String, FileStamp> current, List<String> all) {
        File[] children = folder.listFiles();
        if (children != null) for (File child : children) collect(child, current, all);
    }

    private boolean completeWindowsBatch(File folder) {
        File manifest = new File(folder, "_batch-manifest.json");
        File ready = new File(folder, "_batch-ready.txt");
        if (!manifest.isFile() || !ready.isFile()) return false;
        try {
            StringBuilder raw = new StringBuilder();
            try (BufferedReader reader = new BufferedReader(new FileReader(manifest))) {
                String line;
                while ((line = reader.readLine()) != null) raw.append(line);
            }
            JSONObject json = new JSONObject(raw.toString());
            int expectedCount = json.getInt("fileCount");
            long expectedBytes = json.getLong("bytes");
            long[] actual = countMedia(folder);
            return actual[0] == expectedCount && actual[1] == expectedBytes;
        } catch (Exception error) {
            return false;
        }
    }

    private long[] countMedia(File file) {
        long count = 0;
        long bytes = 0;
        File[] children = file.listFiles();
        if (children == null) return new long[]{0, 0};
        for (File child : children) {
            if (child.isDirectory()) {
                long[] nested = countMedia(child);
                count += nested[0];
                bytes += nested[1];
            } else {
                String name = child.getName();
                int dot = name.lastIndexOf('.');
                if (!name.endsWith(".!sync") && dot >= 0 && EXTENSIONS.contains(name.substring(dot + 1).toLowerCase(Locale.ROOT))) {
                    count++;
                    bytes += child.length();
                }
            }
        }
        return new long[]{count, bytes};
    }

    private static final class FileStamp {
        final long size;
        final long modified;
        FileStamp(long size, long modified) { this.size = size; this.modified = modified; }
    }
}
