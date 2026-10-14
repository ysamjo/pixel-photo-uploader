"""Statusseite: Zaehler, Knoepfe und Setup ohne SSH. Handlers sind ohne HTTP pruefbar."""
import pytest

from app import runner
from app.server import companion_lines, handle_request_sync, handle_setup, render_page


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


def test_pixel_protok_liest_die_letzten_zeilen(tmp_path):
    control = tmp_path / "control"
    assert companion_lines(str(control)) == []
    control.mkdir()
    (control / "companion-log.txt").write_text("a\nb\nc\n", encoding="utf-8")
    assert companion_lines(str(control), limit=2) == ["b", "c"]


def test_pixel_protok_showt_auf_der_seite_und_escapt(tmp_path):
    control = tmp_path / "control"
    control.mkdir()
    (control / "companion-log.txt").write_text(
        "Kein Bestaetigungsknopf <img src=x onerror=alert(1)>\n", encoding="utf-8")
    html = render_page(_info(), companion_lines=companion_lines(str(control)))
    assert "Pixel meldet" in html
    assert "Kein Bestaetigungsknopf" in html
    assert "<img" not in html


def test_seite_ohne_pixel_protok_nennt_keine_leere_grouppe():
    html = render_page(_info())
    assert "Pixel meldet" not in html


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


def test_watchdog_status_ist_frisch_und_enthaelt_keine_rohen_adb_fehler(tmp_path, monkeypatch):
    import json
    from app.server import watchdog_status
    monkeypatch.setenv("PPU_STATE_DIR", str(tmp_path))
    monkeypatch.setattr("app.server.time.time", lambda: 1000)
    d = tmp_path / "photos-watchdog"
    d.mkdir()
    p = d / "photos-watchdog-status.json"
    p.write_text(json.dumps({"state": "offline", "message": "Pixel nicht erreichbar", "observedAt": 990, "error": "internal command"}))
    assert watchdog_status() == {"state": "offline", "message": "Pixel nicht erreichbar", "observedAt": 990}
    p.write_text(json.dumps({"observedAt": 1}))
    assert watchdog_status()["state"] == "stale"
    p.write_text('[]')
    assert watchdog_status()["state"] == "unavailable"


def test_watchdog_status_reicht_die_speichermessung_durch(tmp_path, monkeypatch):
    import json
    from app.server import watchdog_status
    monkeypatch.setenv("PPU_STATE_DIR", str(tmp_path))
    monkeypatch.setattr("app.server.time.time", lambda: 1000)
    d = tmp_path / "photos-watchdog"
    d.mkdir()
    (d / "photos-watchdog-status.json").write_text(json.dumps({
        "state": "tracking", "message": "laeuft", "observedAt": 990,
        "storage": {"freeBytes": 1024, "hogs": {"share": 4096}}}))
    assert watchdog_status()["storage"] == {"freeBytes": 1024, "hogs": {"share": 4096}}


def test_speicherseite_zeigt_bericht_restbestand_und_den_fehlenden_bericht():
    html = render_page(_info(reserve_gib=1.5))
    assert "Pixel-Speicher" in html
    assert "Noch kein Speicherbericht" in html

    html = render_page(_info(reserve_gib=1.5, pixel_storage={
        "freeBytes": 2 * 1024**3, "totalBytes": 24 * 1024**3, "ageSeconds": 120.0,
        "fresh": True, "warnLevel": "warn", "partialCount": 2,
        "partialBytes": 1024**3, "tempCount": 1, "tempBytes": 512,
        "reclaimedBytes": 4096}))
    assert "2.00 GiB" in html and "24.00 GiB" in html
    assert "wird knapp" in html
    assert "Resilio-Teilkopien: 2 (1.00 GiB)" in html
    assert "Gemeldet vor 2 min" in html
    # 4 KiB duerfen nicht als "0.00 GiB" durchgehen — das liest sich wie "nichts frei gegeben".
    assert "zuletzt freigegeben: 4.0 KiB" in html

    html = render_page(_info(reserve_gib=1.5, pixel_storage={
        "freeBytes": 1024, "totalBytes": 2048, "ageSeconds": 4000.0,
        "fresh": False, "warnLevel": "ok"}))
    assert "veraltet" in html


def test_waechter_fresser_erscheinen_und_werden_escapiert():
    html = render_page(_info(photos_watchdog={
        "state": "tracking", "message": "laeuft",
        "storage": {"hogs": {"share": 1024**3, "thumbnails": "<img src=x>"}}}))
    assert "Auf dem Gerät gemessen" in html
    assert "share 1.00 GiB" in html
    assert "<img" not in html


def test_status_meldet_speicherbericht_und_reserve(client, tmp_path):
    import json
    import time
    client.post("/api/setup", data={
        "DropboxRoot": "", "InboxRoot": "", "SourceRoot": str(tmp_path / "archive"),
        "StagingRoot": str(tmp_path / "staging"), "ControlRoot": str(tmp_path / "control"),
        "BatchGiB": "5", "ReserveGiB": "2", "StableSeconds": "120",
        "RescanMinutes": "360", "DeepRescanDays": "7"})
    (tmp_path / "control" / "pixel-storage.json").write_text(json.dumps({
        "version": 1, "observedAtEpochMs": int(time.time() * 1000),
        "freeBytes": 3 * 1024**3, "totalBytes": 24 * 1024**3,
        "warnLevel": "warn"}), encoding="utf-8")

    status = client.get("/api/status").json()
    assert status["configured"] is True
    assert status["pixel_storage"]["freeBytes"] == 3 * 1024**3
    assert status["pixel_storage"]["fresh"] is True
    assert status["reserve_gib"] == 2.0
