package de.pixelphotouploader.companion;

import org.junit.Test;

import java.util.Arrays;
import java.util.List;
import java.util.Locale;

import static org.junit.Assert.*;

public class StallDetectionTest {

    private static final String[] FAILED_ITEMS_NEEDLES = {
            "can't be backed up", "cannot be backed up", "couldn't be backed up", "could not be backed up",
            "können nicht gesichert werden", "kann nicht gesichert werden",
            "nicht gesichert werden", "nicht sicherbar"
    };

    private static final String[] PROFILE_SHEET_NEEDLES = {
            "manage your google account", "google-konto verwalten",
            "unlimited storage", "unbegrenzter speicherplatz",
            "photos settings", "fotos-einstellungen"
    };

    private static String normalize(String text) {
        return text == null ? "" : text.trim().toLowerCase(Locale.GERMANY)
                .replace('\u00a0', ' ')
                .replace('\u2019', '\'')
                .replace('\u2018', '\'')
                .replace('´', '\'')
                .replace('`', '\'');
    }

    private static boolean containsAny(String text, String... needles) {
        String normalized = normalize(text);
        for (String needle : needles) {
            if (normalized.contains(normalize(needle))) return true;
        }
        return false;
    }

    @Test
    public void detectsFailedItemsInGermanAndEnglish() {
        // Test with curly apostrophe U+2019 directly (as rendered by Google Photos)
        assertTrue(containsAny("4 items can\u2019t be backed up", FAILED_ITEMS_NEEDLES));
        assertTrue(containsAny("4 items can’t be backed up", FAILED_ITEMS_NEEDLES));
        assertTrue(containsAny("4 items can't be backed up", FAILED_ITEMS_NEEDLES));
        assertTrue(containsAny("1 Element kann nicht gesichert werden", FAILED_ITEMS_NEEDLES));
        assertTrue(containsAny("2 Elemente können nicht gesichert werden", FAILED_ITEMS_NEEDLES));
        assertFalse(containsAny("Getting ready to back up • 52 items left", FAILED_ITEMS_NEEDLES));
    }

    @Test
    public void detectsProfileSheetOpen() {
        assertTrue(containsAny("signed in as user@example.com | manage your google account | unlimited storage", PROFILE_SHEET_NEEDLES));
        assertTrue(containsAny("angemeldet als user@example.com | google-konto verwalten", PROFILE_SHEET_NEEDLES));
        assertFalse(containsAny("photos | search | library | sharing", PROFILE_SHEET_NEEDLES));
    }

    @Test
    public void stallConditionEvaluatesCorrectly() {
        long start = 1000L;
        long now1 = start + 10 * 60_000L; // 10 min
        long now2 = start + 21 * 60_000L; // 21 min

        long stallLimit = 20 * 60_000L;
        assertFalse((now1 - start) >= stallLimit);
        assertTrue((now2 - start) >= stallLimit);
    }

    @Test
    public void detectsLifetimeSummaryCorrectly() {
        assertTrue(PhotosAccessibilityService.isLifetimeSummary("backup complete • 331,459 photos backed up • dismiss"));
        assertTrue(PhotosAccessibilityService.isLifetimeSummary("331,459 photos backed up"));
        assertTrue(PhotosAccessibilityService.isLifetimeSummary("331.459 Fotos gesichert"));
        assertTrue(PhotosAccessibilityService.isLifetimeSummary("12,345 elemente gesichert"));
        assertTrue(PhotosAccessibilityService.isLifetimeSummary("100000 photos backed up"));

        // Regular batch counts or status strings must NOT be identified as lifetime summaries
        assertFalse(PhotosAccessibilityService.isLifetimeSummary("Backup complete"));
        assertFalse(PhotosAccessibilityService.isLifetimeSummary("Sicherung abgeschlossen"));
        assertFalse(PhotosAccessibilityService.isLifetimeSummary("Backing up 365 photos"));
        assertFalse(PhotosAccessibilityService.isLifetimeSummary("365 items left"));
        assertFalse(PhotosAccessibilityService.isLifetimeSummary("Preparing backup"));
    }

    @Test
    public void distinguishesPreparingFromActiveNeedles() {
        String[] preparingNeedles = {
                "sicherung wird vorbereitet", "sicherung vorbereiten", "wird vorbereitet",
                "sicherung wird gestartet", "synchronis",
                "preparing backup", "getting ready to back up", "checking time remaining",
                "scanning your photo library", "looking for items to back up"
        };
        String[] activeNeedles = {
                "sicherung läuft", "wird gesichert", "werden gesichert", "wird hochgeladen",
                "backing up", "uploading",
                "items left", "item left", "elemente verbleibend", "element verbleibend"
        };

        assertTrue(containsAny("Preparing backup", preparingNeedles));
        assertFalse(containsAny("Preparing backup", activeNeedles));

        assertTrue(containsAny("Scanning your photo library", preparingNeedles));
        assertFalse(containsAny("Scanning your photo library", activeNeedles));

        assertTrue(containsAny("Backing up", activeNeedles));
        assertFalse(containsAny("Backing up", preparingNeedles));

        assertTrue(containsAny("12 items left", activeNeedles));
        assertFalse(containsAny("12 items left", preparingNeedles));
    }
}
