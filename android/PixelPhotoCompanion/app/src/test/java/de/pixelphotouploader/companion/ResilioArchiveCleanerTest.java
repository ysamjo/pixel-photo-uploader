package de.pixelphotouploader.companion;

import org.junit.Rule;
import org.junit.Test;
import org.junit.rules.TemporaryFolder;

import java.io.File;
import java.io.IOException;

import static org.junit.Assert.*;

public class ResilioArchiveCleanerTest {
    @Rule
    public TemporaryFolder temp = new TemporaryFolder();

    @Test
    public void nullOrNonDirectoryReturnsZero() throws IOException {
        assertEquals(0, ResilioArchiveCleaner.purge(null));
        File nonExistent = new File(temp.getRoot(), "does_not_exist");
        assertEquals(0, ResilioArchiveCleaner.purge(nonExistent));

        File file = temp.newFile("plain_file.txt");
        assertEquals(0, ResilioArchiveCleaner.purge(file));
    }

    @Test
    public void purgesNestedFilesAndDirectoriesLeavingArchiveRootIntact() throws IOException {
        File archiveDir = temp.newFolder(".sync", "Archive");
        File staging = new File(archiveDir, "staging");
        File batches = new File(staging, "Batches");
        File batch1 = new File(batches, "20261013-003806");
        assertTrue(batch1.mkdirs());

        File f1 = new File(batch1, "000001-abc.jpg");
        File f2 = new File(batch1, "000002-def.jpg");
        assertTrue(f1.createNewFile());
        assertTrue(f2.createNewFile());

        File batch2 = new File(batches, "20261014-051601");
        assertTrue(batch2.mkdirs());
        File f3 = new File(batch2, "000003-ghi.jpg");
        assertTrue(f3.createNewFile());

        // 3 files + 4 directories (batch1, batch2, batches, staging) = 7 deleted items
        int deleted = ResilioArchiveCleaner.purge(archiveDir);
        assertEquals(7, deleted);

        // archiveDir still exists and is completely empty
        assertTrue(archiveDir.exists());
        assertTrue(archiveDir.isDirectory());
        File[] remaining = archiveDir.listFiles();
        assertNotNull(remaining);
        assertEquals(0, remaining.length);
    }
}
