"""Config-Guard: App-Transport, gefuellte und getrennte Wurzeln."""
import json
from pathlib import Path

import pytest

from app.config import DEFAULTS, load_config, save_config_atomic


@pytest.fixture
def roots(tmp_path, monkeypatch):
    state = tmp_path / "state"
    state.mkdir()
    monkeypatch.setenv("PPU_STATE_DIR", str(state))
    base = dict(DEFAULTS)
    base.update({
        "SourceRoot": str(tmp_path / "archive"), "StagingRoot": str(tmp_path / "staging"),
        "ControlRoot": str(tmp_path / "control"),
    })
    return base


def _load(cfg: dict):
    save_config_atomic(cfg)
    return load_config()


def test_adb_transport_bleibt_verboten(roots):
    roots["TransportMode"] = "USB"
    with pytest.raises(ValueError, match="TransportMode"):
        _load(roots)


def test_import_ohne_quellordner_ist_verboten(roots):
    roots.update({"ImportEnabled": True, "DropboxRoot": "", "InboxRoot": str(roots["StagingRoot"])})
    with pytest.raises(ValueError, match="Dropbox"):
        _load(roots)


def test_inbox_im_archiv_wuerde_Archiv_dateien_verschieben(roots):
    archive = Path(roots["SourceRoot"])
    archive.mkdir(parents=True)
    roots.update({"ImportEnabled": True, "DropboxRoot": str(archive.parent / "dropbox"),
                  "InboxRoot": str(archive / "inbox")})
    with pytest.raises(ValueError, match="Inbox"):
        _load(roots)


def test_leere_archivwurzel_ist_verboten(roots):
    roots["SourceRoot"] = "  "
    with pytest.raises(ValueError, match="SourceRoot"):
        _load(roots)


def test_import_aus_ist_ohne_cloud_ordner_erlaubt(roots):
    assert _load(roots)["ImportEnabled"] is False


def test_wochenfrist_ist_standard(roots):
    assert _load(roots)["DeepRescanDays"] == DEFAULTS["DeepRescanDays"]


def test_legacy_ohne_wochenfrist_bekommt_sie(roots, tmp_path):
    del roots["DeepRescanDays"]
    save_config_atomic(roots)
    assert load_config()["DeepRescanDays"] == DEFAULTS["DeepRescanDays"]
