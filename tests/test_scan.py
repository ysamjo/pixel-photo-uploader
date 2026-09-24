"""Zweistufiger Grundabgleich: Frontier, Wochenfrist, Ordnerstandzeit (Windows 3.3.12)."""
import os
from datetime import datetime, timedelta, timezone

import pytest

from app import store

NOW = datetime(2026, 9, 23, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def state_dir(tmp_path, monkeypatch):
    state = tmp_path / "state"
    state.mkdir()
    monkeypatch.setenv("PPU_STATE_DIR", str(state))
    return state


def _decision(scanned=None, deep=None, root="/archiv", rescan_minutes=360, deep_days=7):
    if scanned is not None or deep is not None:
        store.save_scan_state(scanned or datetime.min.replace(tzinfo=timezone.utc),
                              root, deep=deep)
    return store.scan_decision(NOW, root, rescan_minutes, deep_days)


def test_ohne_beweis_keines_durchlaufs_wird_voll_gelesen(state_dir):
    d = _decision()
    assert d["deep"] and d["due"]


def test_andere_archivwurzel_zaehlt_noch_nie(state_dir):
    store.save_scan_state(NOW - timedelta(hours=6), "/archiv")
    d = store.scan_decision(NOW, "/anderes-archiv", 360, 7)
    assert d["deep"]


def test_frischer_vollstaendiger_durchlauf_laesst_ordner_zu(state_dir):
    scanned = NOW - timedelta(minutes=400)
    d = _decision(scanned=scanned, deep=scanned)
    assert d["due"] and not d["deep"]
    assert d["prune_before"] == scanned - timedelta(hours=store.SCAN_PRUNE_GRACE_HOURS)


def test_wochenfrist_holt_den_vollstaendigen_durchlauf(state_dir):
    d = _decision(scanned=NOW - timedelta(minutes=400), deep=NOW - timedelta(days=8))
    assert d["deep"]


def test_zu_kurzes_intervall_wartet_nur(state_dir):
    d = _decision(scanned=NOW - timedelta(minutes=10), deep=NOW - timedelta(hours=1))
    assert not d["due"] and d["wait_minutes"] > 0


def _archive(tmp_path):
    root = tmp_path / "archiv"
    (root / "2020.01").mkdir(parents=True)
    (root / "2020.01" / "ruhig.jpg").write_bytes(b"a" * 5)
    (root / "2026.09").mkdir(parents=True)
    (root / "2026.09" / "betrieben.jpg").write_bytes(b"b" * 7)
    return root


def test_standzeitlauf_oeffnet_geschlossenen_ordner_nicht_verliert_aber_keine_zeile(
        tmp_path, state_dir):
    root = _archive(tmp_path)
    catalog = state_dir / "catalog.csv"
    assert len(store.update_catalog(root, 0.0, catalog)) == 2

    quiet = root / "2020.01"
    stamp = int((datetime.now(timezone.utc) - timedelta(days=3)).timestamp())
    (quiet / "versteckt.jpg").write_bytes(b"c" * 9)
    os.utime(quiet, ns=(stamp * 10**9, stamp * 10**9))

    pruned = store.update_catalog(root, 0.0, catalog,
                                  prune_before=datetime.now(timezone.utc) - timedelta(days=1))
    paths = sorted(str(r["RelativePath"]) for r in pruned)
    assert paths == ["2020.01/ruhig.jpg", "2026.09/betrieben.jpg"]

    full = store.update_catalog(root, 0.0, catalog)
    assert len(full) == 3


def test_standzeitlauf_setzt_die_wochenfrist_nicht_zurueck(state_dir, tmp_path):
    root = _archive(tmp_path)
    catalog = state_dir / "catalog.csv"
    long_ago = datetime.now(timezone.utc) - timedelta(days=9)
    store.update_catalog(root, 0.0, catalog)
    store.save_scan_state(long_ago, str(root), deep=long_ago)

    store.update_catalog(root, 0.0, catalog, prune_before=long_ago + timedelta(hours=1))
    scanned, deep = store.load_scan_state(str(root))
    assert deep == long_ago
    assert scanned > long_ago


def test_vollstaendiger_durchlauf_setzt_beide_merker(state_dir, tmp_path):
    root = _archive(tmp_path)
    store.update_catalog(root, 0.0, state_dir / "catalog.csv")
    scanned, deep = store.load_scan_state(str(root))
    assert deep.tzinfo is not None and deep > datetime.now(timezone.utc) - timedelta(minutes=5)
    assert scanned == deep
