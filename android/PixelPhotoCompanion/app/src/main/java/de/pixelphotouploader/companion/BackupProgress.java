package de.pixelphotouploader.companion;

/** Nur ein sinkender Restzaehler ist messbarer Fortschritt, kein wiederholter Status. */
final class BackupProgress {
    private BackupProgress() {}

    static long observedAt(int previous, int remaining, long lastProgressAt, long now) {
        return remaining >= 0 && remaining < previous ? now : lastProgressAt;
    }

    static boolean stalled(long lastProgressAt, long lastProbeAt, long now, long limit) {
        return now - Math.max(lastProgressAt, lastProbeAt) >= limit;
    }
}
