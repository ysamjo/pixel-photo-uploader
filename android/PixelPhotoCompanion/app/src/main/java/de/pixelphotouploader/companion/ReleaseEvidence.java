package de.pixelphotouploader.companion;

import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Set;

/** Erfolg nur fuer vor dem bestaetigten Freigabeklick vorhandene Dateien. */
final class ReleaseEvidence {
    private ReleaseEvidence() {}

    static boolean authorizes(List<String> beforeClick, List<String> claimed, boolean confirmed) {
        return confirmed && !claimed.isEmpty() && new HashSet<>(beforeClick).containsAll(claimed);
    }

    static List<String> removed(List<String> beforeClick, List<String> current,
                                List<String> refused, boolean confirmed) {
        List<String> removed = new ArrayList<>();
        if (!confirmed) return removed;
        Set<String> present = new HashSet<>(current);
        Set<String> rejected = new HashSet<>(refused);
        for (String path : beforeClick) {
            if (!present.contains(path) && !rejected.contains(path)) removed.add(path);
        }
        return removed;
    }
}
