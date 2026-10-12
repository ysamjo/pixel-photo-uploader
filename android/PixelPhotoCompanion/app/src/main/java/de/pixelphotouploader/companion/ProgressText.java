package de.pixelphotouploader.companion;

import java.util.regex.Matcher;
import java.util.regex.Pattern;

final class ProgressText {
    private static final Pattern REMAINING = Pattern.compile(
            "([0-9]+)\\s+(?:items? left|(?:elemente?|dateien|fotos|videos)\\s+(?:verbleibend|übrig))",
            Pattern.CASE_INSENSITIVE);

    static int remaining(String text) {
        Matcher match = REMAINING.matcher(text);
        if (!match.find()) return -1;
        try { return Integer.parseInt(match.group(1)); }
        catch (NumberFormatException ignored) { return -1; }
    }
}
