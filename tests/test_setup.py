"""Setup ohne SSH: apply_setup ist ohne HTTP und ohne Browser prüfbar."""
from app import config_path
from app.config import load_config
from app.setup import apply_setup


def _values(tmp_path, **over) -> dict:
    v = {
        "DropboxRoot": "", "InboxRoot": "",
        "SourceRoot": str(tmp_path / "archive"),
        "StagingRoot": str(tmp_path / "staging"),
        "ControlRoot": str(tmp_path / "control"),
        "BatchGiB": "5", "StableSeconds": "120",
        "RescanMinutes": "360", "DeepRescanDays": "7",
    }
    v.update(over)
    return v


def test_gueltiges_setup_schreibt_config_und_leggt_ordner_an(tmp_path, monkeypatch):
    monkeypatch.setenv("PPU_STATE_DIR", str(tmp_path / "state"))
    result = apply_setup(_values(tmp_path))
    assert result["ok"], result["errors"]
    cfg = load_config()
    assert cfg["SourceRoot"] == str(tmp_path / "archive")
    assert cfg["StableMinutes"] == 2.0
    assert cfg["ImportEnabled"] is False
    assert (tmp_path / "staging" / "WindowsBatches").is_dir()


def test_verschachtelte_ordner_werden_abgewiesen(tmp_path, monkeypatch):
    monkeypatch.setenv("PPU_STATE_DIR", str(tmp_path / "state"))
    result = apply_setup(_values(tmp_path, StagingRoot=str(tmp_path / "archive" / "handover")))
    assert not result["ok"]
    assert any("nested" in e or "Schachtel" in e for e in result["errors"])
    assert not config_path().exists()


def test_import_braucht_beide_wolken_ordner(tmp_path, monkeypatch):
    monkeypatch.setenv("PPU_STATE_DIR", str(tmp_path / "state"))
    result = apply_setup(_values(tmp_path, InboxRoot=str(tmp_path / "inbox")))
    assert not result["ok"]
    assert any("Dropbox" in e for e in result["errors"])

    both = apply_setup(_values(tmp_path, InboxRoot=str(tmp_path / "inbox"),
                               DropboxRoot=str(tmp_path / "dropbox")))
    assert both["ok"], both["errors"]
    assert load_config()["ImportEnabled"] is True


def test_groesse_und_stabilitaet_bleiben_im_erlaubten_band(tmp_path, monkeypatch):
    monkeypatch.setenv("PPU_STATE_DIR", str(tmp_path / "state"))
    apply_setup(_values(tmp_path, BatchGiB="900", StableSeconds="999999",
                        DeepRescanDays="0"))
    cfg = load_config()
    assert cfg["BatchGiB"] == 10.0
    assert cfg["StableMinutes"] == 43200 / 60
    assert cfg["DeepRescanDays"] == 1
