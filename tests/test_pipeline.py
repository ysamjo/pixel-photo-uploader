"""Import/Sortierung: Zeitanteile im Log, damit ein langer Lauf erklärbar bleibt."""
import errno
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app import log_path, pipeline
from app.config import DEFAULTS, save_config_atomic


def _roots(tmp_path, monkeypatch):
    state = tmp_path / "state"
    state.mkdir()
    monkeypatch.setenv("PPU_STATE_DIR", str(state))
    for name in ("dropbox", "inbox", "archive"):
        (tmp_path / name).mkdir()
    cfg = dict(DEFAULTS)
    cfg.update({
        "ImportEnabled": True, "DropboxRoot": str(tmp_path / "dropbox"),
        "InboxRoot": str(tmp_path / "inbox"), "SourceRoot": str(tmp_path / "archive"),
        "StableMinutes": 0,
    })
    save_config_atomic(cfg)
    return cfg


def test_import_log_names_both_stages(tmp_path, monkeypatch):
    cfg = _roots(tmp_path, monkeypatch)
    old = int((datetime.now(timezone.utc) - timedelta(days=1)).timestamp())
    pic = Path(cfg["DropboxRoot"]) / "IMG_20260901_120000.jpg"
    pic.write_bytes(b"z" * 12)
    os.utime(pic, ns=(old * 10**9, old * 10**9))

    result = pipeline.run_import(cfg)
    assert result["moved"] == 2  # Dropbox -> Inbox, then Inbox -> Archive in one cycle
    text = log_path().read_text(encoding="utf-8")
    assert "Dropbox sweep" in text and "sorting" in text


def _old_mtime(path: Path) -> None:
    old = int((datetime.now(timezone.utc) - timedelta(days=1)).timestamp())
    os.utime(path, ns=(old * 10**9, old * 10**9))


def test_move_falls_back_to_copy_across_filesystems(tmp_path, monkeypatch):
    """ZimaOS: Dropbox/OneDrive-Mounts liegen auf einem anderen Dateisystem
    als das lokale Archiv; Path.rename wirft dort EXDEV."""
    state = tmp_path / "state"
    state.mkdir()
    monkeypatch.setenv("PPU_STATE_DIR", str(state))
    src_dir, dst_dir = tmp_path / "src", tmp_path / "dst"
    src_dir.mkdir()
    dst_dir.mkdir()
    src = src_dir / "IMG_20260901_120000.jpg"
    src.write_bytes(b"y" * 64)

    real_rename = Path.rename

    def boom(self, target):
        raise OSError(errno.EXDEV, "Invalid cross-device link")

    monkeypatch.setattr(Path, "rename", boom)
    try:
        result, dest = pipeline.move_media_file(src, dst_dir, "EXDEV-Test")
    finally:
        monkeypatch.setattr(Path, "rename", real_rename)
    assert result == "Moved"
    assert dest is not None and dest.read_bytes() == b"y" * 64
    assert not src.exists()


def test_cloud_debris_never_enters_archive(tmp_path, monkeypatch):
    cfg = _roots(tmp_path, monkeypatch)
    dropbox = Path(cfg["DropboxRoot"])
    (dropbox / ".sync").mkdir()
    debris = [
        dropbox / ".sync" / "IMG_20260901_120000.jpg",
        dropbox / "Thumbs.db",
        dropbox / "IMG_20260901_120000.sync-conflict-20240101-1234567.jpg",
        dropbox / "clip.mp4.tmp",
    ]
    for d in debris:
        d.write_bytes(b"q" * 16)
        _old_mtime(d)
    good = dropbox / "IMG_20260902_120000.jpg"
    good.write_bytes(b"z" * 12)
    _old_mtime(good)

    result = pipeline.run_import(cfg)
    assert result["moved"] == 2  # only the real photo travels
    for d in debris:
        assert d.exists(), f"debris must stay untouched: {d}"
    assert not good.exists()


def test_bulk_import_dedupes_with_shared_index(tmp_path, monkeypatch):
    """30 Dateien, 5 byte-identische Duplikate mit anderem Namen: Der Index
    verhindert das quadratische Ordner-Listen pro Datei."""
    cfg = _roots(tmp_path, monkeypatch)
    dropbox = Path(cfg["DropboxRoot"])
    for i in range(30):
        p = dropbox / f"IMG_202609{i:02d}_120000.jpg"
        p.write_bytes(bytes([i % 256]) * 64)
        _old_mtime(p)
    for i in range(5):
        p = dropbox / f"DUP_{i}.jpg"
        p.write_bytes(bytes([i % 256]) * 64)  # same content as IMG_... siblings
        _old_mtime(p)

    result = pipeline.run_import(cfg)
    # 30 unique travel Dropbox -> Inbox -> Archive (2 moves each);
    # the 5 dupes die at the latest when sorting into the archive.
    assert result["moved"] == 60
    assert result["duplicates"] == 5


def test_destination_index_lists_folder_once(tmp_path):
    folder = tmp_path / "dest"
    folder.mkdir()
    (folder / "a.jpg").write_bytes(b"a" * 10)
    index = pipeline._DestinationIndex()
    first = index.candidates(folder, 10)
    assert [p.name for p in first] == ["a.jpg"]
    (folder / "b.jpg").write_bytes(b"b" * 10)
    # Per-run index: newcomers after the first listing stay invisible until
    # note_moved records them — one listing per folder per run.
    assert [p.name for p in index.candidates(folder, 10)] == ["a.jpg"]
    index.note_moved(folder, folder / "c.jpg", 10)
    assert sorted(p.name for p in index.candidates(folder, 10)) == ["a.jpg", "c.jpg"]


def test_import_sweeps_onedrive_and_dropbox(tmp_path, monkeypatch):
    cfg = _roots(tmp_path, monkeypatch)
    onedrive = tmp_path / "onedrive"
    onedrive.mkdir()
    cfg["OneDriveRoot"] = str(onedrive)
    save_config_atomic(cfg)

    db_pic = Path(cfg["DropboxRoot"]) / "IMG_20260901_100000.jpg"
    db_pic.write_bytes(b"1" * 12)
    _old_mtime(db_pic)

    od_pic = onedrive / "IMG_20260902_100000.jpg"
    od_pic.write_bytes(b"2" * 12)
    _old_mtime(od_pic)

    result = pipeline.run_import(cfg)
    assert result["moved"] == 4  # 2 to inbox, 2 to archive
    text = log_path().read_text(encoding="utf-8")
    assert "Dropbox sweep" in text and "OneDrive sweep" in text and "sorting" in text
    assert not db_pic.exists() and not od_pic.exists()
