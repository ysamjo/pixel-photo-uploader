"""Ein Ueberwachungszyklus: ueberlebt Fehler, laesst niemanden zweimal laufen."""
from pathlib import Path

from app import runner, store, watch
from app.config import DEFAULTS, save_config_atomic


def _roots(tmp_path, monkeypatch, **over):
    state = tmp_path / "state"
    state.mkdir(exist_ok=True)
    monkeypatch.setenv("PPU_STATE_DIR", str(state))
    for name in ("archive", "staging", "control"):
        (tmp_path / name).mkdir(exist_ok=True)
    cfg = dict(DEFAULTS)
    cfg.update({
        "SourceRoot": str(tmp_path / "archive"), "StagingRoot": str(tmp_path / "staging"),
        "ControlRoot": str(tmp_path / "control"), "StableMinutes": 0,
    })
    cfg.update(over)
    save_config_atomic(cfg)
    return tmp_path / "archive"


def _paths() -> set[str]:
    return {str(r["RelativePath"]) for r in store.load_catalog()}


def test_zyklus_ohne_config_wird_gemeldet_statt_zu_werfen(tmp_path, monkeypatch):
    monkeypatch.setenv("PPU_STATE_DIR", str(tmp_path / "state"))
    (tmp_path / "state").mkdir(parents=True)
    assert watch.run_cycle() is False


def test_zweiter_zyklus_waehrend_lauf_bekommt_die_sperre_nicht(tmp_path, monkeypatch):
    _roots(tmp_path, monkeypatch)
    assert runner.acquire("watch")
    assert watch.run_cycle() is False
    runner.release()
    assert watch.run_cycle() is True


def test_zyklus_erfasst_neue_dateien_und_weckt_den_schlaefer_nicht_ewig(tmp_path, monkeypatch):
    archive = _roots(tmp_path, monkeypatch)
    (archive / "2026.09").mkdir(parents=True)
    (archive / "2026.09" / "a.jpg").write_bytes(b"a" * 10)
    assert watch.run_cycle() is True
    assert _paths() == {"2026.09/a.jpg"}

    runner.request_sync("deep")
    assert watch._wait(600) < 600  # a request wakes the loop instead of a ten-minute sleep
