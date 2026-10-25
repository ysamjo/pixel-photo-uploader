package de.pixelphotouploader.companion;

import org.junit.Test;
import java.util.Arrays;
import java.util.Collections;
import static org.junit.Assert.*;

public class ReleaseEvidenceTest {
    @Test public void missingFilesWithoutConfirmedClickNeverProduceSuccess() {
        assertTrue(ReleaseEvidence.removed(Arrays.asList("a", "b"), Collections.emptyList(),
                Collections.emptyList(), false).isEmpty());
    }
    @Test public void partialFreeUpOnlyConfirmsSnapshotFilesThatActuallyDisappeared() {
        assertEquals(Arrays.asList("a"), ReleaseEvidence.removed(Arrays.asList("a", "b"),
                Arrays.asList("b", "new-file"), Collections.emptyList(), true));
    }
    @Test public void refusedFilesAreExcludedEvenWithConfirmedClick() {
        assertEquals(Arrays.asList("a"), ReleaseEvidence.removed(Arrays.asList("a", "b"),
                Collections.emptyList(), Arrays.asList("b"), true));
    }
    @Test public void upgradeWithoutSnapshotCannotReinterpretExistingMissingFiles() {
        assertTrue(ReleaseEvidence.removed(Collections.emptyList(), Arrays.asList("b"),
                Collections.emptyList(), true).isEmpty());
    }
    @Test public void pendingReceiptNeedsPersistentClickAndMatchingSnapshot() {
        assertFalse(ReleaseEvidence.authorizes(Collections.emptyList(), Arrays.asList("a"), true));
        assertFalse(ReleaseEvidence.authorizes(Arrays.asList("a"), Arrays.asList("a"), false));
        assertFalse(ReleaseEvidence.authorizes(Arrays.asList("a"), Arrays.asList("b"), true));
        assertTrue(ReleaseEvidence.authorizes(Arrays.asList("a", "b"), Arrays.asList("a"), true));
    }
}
