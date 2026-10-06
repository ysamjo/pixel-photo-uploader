"""Lock + Bitte-an-den-Watcher: ein Zyklus zur Zeit, auch über Prozesse hinweg."""
import json
import os
from datetime import datetime, timedelta, timezone

from app import runner


def test_zweiter_laeufer_bekommt_keine_sperre(tmp_path, monkeypatch):
    monkeypatch.setenv("PPU_STATE_DIR", str(tmp_path))
    assert runner.acquire("watch")
    assert not runner.acquire("api")
    runner.release()
    assert runner.acquire("api")
    runner.release()


def test_sperre_eines_toten_prozesses_wird_gebrochen(tmp_path, monkeypatch):
    monkeypatch.setenv("PPU_STATE_DIR", str(tmp_path))
    runner.lock_path().write_text(json.dumps({
        "pid": 4_100_000_000, "reason": "watch",
        "takenUtc": datetime.now(timezone.utc).isoformat()}), encoding="utf-8")
    assert runner.acquire("api")


def test_sperre_ohne_startzeit_ist_unbewiesen(tmp_path, monkeypatch):
    """Altbestand vor dem Fix: pid 1 wiederholt sich bei jedem Container-Start."""
    monkeypatch.setenv("PPU_STATE_DIR", str(tmp_path))
    runner.lock_path().write_text(json.dumps({
        "pid": os.getpid(), "reason": "watch",
        "takenUtc": datetime.now(timezone.utc).isoformat()}), encoding="utf-8")
    assert runner.acquire("api")


def test_neue_sperre_ist_erkennbar_an_der_startzeit(tmp_path, monkeypatch):
    """Container-Neustart vergeben pid 1 neu: die Zahl allein ist kein Lebenszeichen."""
    monkeypatch.setenv("PPU_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(runner, "_proc_starttime", lambda pid: 5_000)
    runner.lock_path().write_text(json.dumps({
        "pid": os.getpid(), "started": 4_000, "reason": "watch",
        "takenUtc": datetime.now(timezone.utc).isoformat()}), encoding="utf-8")
    assert runner.acquire("api")
    assert runner._read(runner.lock_path())["started"] == 5_000


def test_uralte_sperre_wird_gebrochen_und_gemeldet(tmp_path, monkeypatch):
    monkeypatch.setenv("PPU_STATE_DIR", str(tmp_path))

    assert runner.acquire("watch")
    old = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
    runner.lock_path().write_text(json.dumps(
        {"pid": os.getpid(), "reason": "watch", "takenUtc": old}), encoding="utf-8")
    assert runner.acquire("api")
    assert "watch" in runner.holder() or "api" in runner.holder()


def test_bitte_wird_nur_einmal_abgeholt(tmp_path, monkeypatch):
    monkeypatch.setenv("PPU_STATE_DIR", str(tmp_path))
    assert runner.take_request() is None
    runner.request_sync("deep")
    assert runner.pending_request() == "deep"
    assert runner.take_request() == "deep"
    assert runner.take_request() is None
    assert runner.pending_request() == ""
