"""Import/Sortierung: Zeitanteile im Log, damit ein langer Lauf erklärbar bleibt."""
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
