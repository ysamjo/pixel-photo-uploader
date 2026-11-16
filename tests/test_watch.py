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


def test_stall_watchdog_ruft_neustart_und_loest_lock_bei_haenger(tmp_path, monkeypatch):
    import threading
    from app import cli, log_path

    state = tmp_path / "state"
    state.mkdir()
    monkeypatch.setenv("PPU_STATE_DIR", str(state))
    hung = threading.Event()

    def stuck_sync(**_kwargs):
        assert runner.acquire("watch")
        runner.touch_heartbeat("import:OneDrive", force_disk=True)
        assert hung.wait(timeout=3.0)

    monkeypatch.setattr(watch, "sync_once", stuck_sync)
    calls = []

    def fake_hang():
        calls.append(True)
        hung.set()

    watch.watch(poll_seconds=0, hang_seconds=0.08, on_hang=fake_hang, max_cycles=1)
    assert calls == [True]
    assert runner.holder() == ""
    log_text = log_path().read_text(encoding="utf-8")
    assert "Watcher hung in phase 'import:OneDrive'" in log_text
    assert "stuck_sync" in log_text

    recorded = []
    monkeypatch.setattr(cli, "watch", lambda poll, hang_seconds=None: recorded.append((poll, hang_seconds)))
    cli.main(["watch", "--poll-seconds", "15", "--hang-seconds", "120"])
    assert recorded == [(15, 120)]


def test_stall_watchdog_greift_nicht_wenn_fortschritt_gemeldet_wird(tmp_path, monkeypatch):
    import time

    state = tmp_path / "state"
    state.mkdir()
    monkeypatch.setenv("PPU_STATE_DIR", str(state))
    calls = []

    def active_sync(**_kwargs):
        for _ in range(4):
            runner.touch_heartbeat("catalog")
            time.sleep(0.03)

    monkeypatch.setattr(watch, "sync_once", active_sync)
    watch.watch(poll_seconds=0, hang_seconds=0.09, on_hang=lambda: calls.append(True), max_cycles=1)
    assert calls == []
