"""Statusseite: Zaehler, Knoepfe und Setup ohne SSH. Handlers sind ohne HTTP pruefbar."""
import pytest

from app import runner
from app.server import handle_request_sync, handle_setup, render_page


def _info(**over) -> dict:
    info = {
        "version": "3.3.12", "configured": True, "archive": "/data/archive",
        "catalog_files": 1234, "open_stable": 21, "open_bytes": 3221225472,
        "staged": 5, "completed": 900, "batch_gib": 5.0, "stable_seconds": 120,
        "rescan_minutes": 360, "deep_rescan_days": 7, "running": "", "pending": "",
    }
    info.update(over)
    return info


def test_seite_zeigt_zaehler_beide_knoepfe_und_log():
    html = render_page(_info(), log_lines=["2026-09-23 12:00:00 [OK] Catalog: 1 files"])
    assert "1234" in html and "21" in html and "3.00 GiB" in html
    assert 'value="deep"' in html
    assert "Sync jetzt" in html and "Vollabgleich" in html
    assert "Catalog: 1 files" in html


def test_seite_ohne_config_bietet_setup_an(tmp_path):
    html = render_page({"configured": False, "hint": "Noch nicht eingerichtet"})
    assert 'name="SourceRoot"' in html and 'name="StagingRoot"' in html
    assert "Noch nicht eingerichtet" in html


def test_abgelehntes_setup_erscheint_auf_der_seite():
    html = render_page(_info(),
                       message="Folders 'InboxRoot' and 'SourceRoot' must not be equal or nested")
    assert "must not be equal or nested" in html


def test_setup_form_hinterlaesst_keine_halbe_config(tmp_path, monkeypatch):
    monkeypatch.setenv("PPU_STATE_DIR", str(tmp_path / "state"))
    (tmp_path / "state").mkdir(parents=True)
    bad = handle_setup({"SourceRoot": "", "StagingRoot": "", "ControlRoot": ""})
    assert "required" in bad["message"]
    assert not (tmp_path / "state" / "config.json").exists()

    good = handle_setup({
        "DropboxRoot": "", "InboxRoot": "", "SourceRoot": str(tmp_path / "archive"),
        "StagingRoot": str(tmp_path / "staging"), "ControlRoot": str(tmp_path / "control"),
        "BatchGiB": "5", "StableSeconds": "120", "RescanMinutes": "360", "DeepRescanDays": "7",
    })
    assert good["message"].startswith("Eingerichtet")


def test_synchronisationsbitte_landet_beim_watcher(tmp_path, monkeypatch):
    monkeypatch.setenv("PPU_STATE_DIR", str(tmp_path))
    handle_request_sync({"kind": "deep"})
    assert runner.pending_request() == "deep"
    handle_request_sync({})
    assert runner.pending_request() == "sync"


@pytest.fixture
def client(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from app.server import create_app
    monkeypatch.setenv("PPU_STATE_DIR", str(tmp_path / "state"))
    return TestClient(create_app())


def test_routes_ohne_config(client, tmp_path):
    assert client.get("/").status_code == 200
    status = client.get("/api/status").json()
    assert status["configured"] is False
    assert client.get("/api/log").status_code == 200


def test_setup_ueber_http_und_bitte_danach(client, tmp_path):
    form = {
        "DropboxRoot": "", "InboxRoot": "", "SourceRoot": str(tmp_path / "archive"),
        "StagingRoot": str(tmp_path / "staging"), "ControlRoot": str(tmp_path / "control"),
        "BatchGiB": "5", "StableSeconds": "120", "RescanMinutes": "360",
        "DeepRescanDays": "7",
    }
    page = client.post("/api/setup", data=form)
    assert page.status_code == 200
    assert "Eingerichtet" in page.text
    assert client.get("/api/status").json()["configured"] is True

    queued = client.post("/api/sync", data={"kind": "deep"}, follow_redirects=False)
    assert queued.status_code == 303 and queued.headers["location"] == "/"
    assert runner.pending_request() == "deep"
    assert "Vollabgleich eingereiht" in client.get("/").text


def test_eingabe_wird_escapiert_und_beibehalten(client, tmp_path):
    page = client.post("/api/setup", data={
        "SourceRoot": "</title><img src=x onerror=alert(1)>", "StagingRoot": "",
        "ControlRoot": ""})
    assert page.status_code == 200
    assert "<img" not in page.text
    assert "&lt;img" in page.text
    assert "StagingRoot is required" in page.text
