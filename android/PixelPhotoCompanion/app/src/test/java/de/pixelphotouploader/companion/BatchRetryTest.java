package de.pixelphotouploader.companion;

import org.junit.Test;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashSet;
import java.util.List;

import static org.junit.Assert.*;

public class BatchRetryTest {

    @Test
    public void emptyCurrentListIsDetectedAsNewBatch() {
        List<String> currentList = new ArrayList<>();
        List<String> offerable = Arrays.asList("/path/to/a.jpg", "/path/to/b.jpg");
        boolean isNewBatch = currentList.isEmpty() || !new HashSet<>(currentList).equals(new HashSet<>(offerable));
        assertTrue(isNewBatch);
    }

    @Test
    public void identicalOfferableIsNotNewBatchRegardlessOfOrder() {
        List<String> currentList = Arrays.asList("/path/to/a.jpg", "/path/to/b.jpg", "/path/to/c.jpg");
        List<String> offerable = Arrays.asList("/path/to/c.jpg", "/path/to/a.jpg", "/path/to/b.jpg");
        boolean isNewBatch = currentList.isEmpty() || !new HashSet<>(currentList).equals(new HashSet<>(offerable));
        assertFalse(isNewBatch);
    }

    @Test
    public void modifiedOfferableIsDetectedAsNewBatch() {
        List<String> currentList = Arrays.asList("/path/to/a.jpg", "/path/to/b.jpg");
        List<String> offerable = Arrays.asList("/path/to/a.jpg", "/path/to/b.jpg", "/path/to/c.jpg");
        boolean isNewBatch = currentList.isEmpty() || !new HashSet<>(currentList).equals(new HashSet<>(offerable));
        assertTrue(isNewBatch);
    }
}
