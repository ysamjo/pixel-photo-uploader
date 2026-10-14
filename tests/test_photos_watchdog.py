"""Zeitgesteuerte Wiederanlaeufe und ADB-Grenzen ohne Netzwerk pruefen."""
import json
import subprocess

import pytest

from app.photos_watchdog import (Adb, Sample, advance, cycle, eligible, parse_df,
                                 parse_storage, preferences, wifi_tx, MIN_TX_PROGRESS)


def tick(state, seconds, tx=0, remaining=None, batch="batch-a"):
    return advance(state, Sample(batch, tx, remaining), seconds)


def test_restart_then_one_hour_cooldown_and_alert_without_loop():
    state, _ = tick({}, 0)
    for now in range(60, 1800, 60):
        state, action = tick(state, now)
        assert action == "tracking"
    state, action = tick(state, 1800)
    assert action == "restart"
    # Persistenz wie nach einem Prozessneustart.
    state = json.loads(json.dumps(state))
    for now in range(1860, 3600, 60):
        state, action = tick(state, now)
        assert action == "restarted"
    state, action = tick(state, 3600)
    assert action == "cooldown"
    for now in range(3660, 7200, 60):
        state, action = tick(state, now)
        assert action == "cooldown"
    state, action = tick(state, 7200)
    assert action == "alert"
    state, action = tick(state, 7260, MIN_TX_PROGRESS)
    assert action == "alert"  # kein zweiter Neustart desselben Batch
    state, action = tick(state, 7320, batch="batch-b")
    assert action == "tracking"


def test_real_tx_or_decreasing_counter_are_progress_but_tiny_traffic_is_not():
    state, _ = tick({}, 0, remaining=13)
    state, _ = tick(state, 60, 100, 13)
    assert state["last_progress"] == 0
    state, _ = tick(state, 120, 100, 12)
    assert state["last_progress"] == 120
    state, _ = tick(state, 180, MIN_TX_PROGRESS + 100, 12)
    assert state["last_progress"] == 180


def test_disconnect_counter_reset_and_clock_change_cannot_trigger_restart():
    state, _ = tick({}, 0, tx=123)
    state, action = tick(state, 10000, tx=123)
    assert action == "tracking" and state["last_progress"] == 10000
    state, _ = tick(state, 10060, tx=0)
    assert state["last_progress"] == 10060
    state, action = tick(state, 1)
    assert action == "tracking" and state["last_progress"] == 1


def test_progress_in_cooldown_cancels_warning_but_not_restart_budget():
    state = {"batch": "batch-a", "stage": "cooldown", "last_progress": 0,
             "last_sample": 90, "tx_anchor": 0, "remaining": 13, "cooldown_until": 3600}
    state, action = tick(state, 100, remaining=12)
    assert action == "restarted"


def test_uid_parser_excludes_resilio_and_tagged_double_counting():
    text = '''
  ident=[{type=WIFI}] uid=10141 set=DEFAULT tag=0x0
    st=100 rb=99 tb=10 tp=1
  ident=[{type=WIFI}] uid=10141 set=FOREGROUND tag=0x0
    st=100 rb=99 tb=20 tp=1
  ident=[{type=WIFI}] uid=10141 set=FOREGROUND tag=0x123
    st=100 rb=99 tb=20 tp=1
  ident=[{type=WIFI}] uid=10170 set=DEFAULT tag=0x0
    st=100 rb=99 tb=50000 tp=1
'''
    assert wifi_tx(text, 10141) == 30
    with pytest.raises(ValueError):
        wifi_tx(text, 10173)


def active_prefs():
    return {"enabled": True, "safetyAccepted": True, "batchPaths": "file-a",
            "batchStartedAt": 1000, "phase": "WAIT_BACKUP"}


def test_pauses_cleanup_hard_errors_pending_receipts_and_timeout_block_action():
    prefs = active_prefs()
    assert eligible(prefs, 60)
    for changes in [{"enabled": False}, {"safetyAccepted": False}, {"phase": "VERIFY"},
                    {"phase": "CONFIRM_FREE_UP"}, {"pendingReceiptPaths": "file-a"},
                    {"pendingReceiptRefused": "file-a"}, {"phase": "ERROR", "detail": "account storage full"}]:
        assert not eligible(prefs | changes, 60)
    assert not eligible(prefs, 72 * 3600 + 2)
    assert eligible(prefs | {"phase": "ERROR", "detail": "Google Fotos zeigt seit 30 Minuten weder Aktivität noch Abschluss"}, 60)


def test_preferences_decode_types_and_missing_counter():
    assert preferences('<map><boolean name="enabled" value="false"/><long name="n" value="13"/><string name="phase">ERROR</string></map>') == {"enabled": False, "n": 13, "phase": "ERROR"}


class FakeAdb:
    def __init__(self):
        self.restarts = 0
        self.reported = []
    def connect(self):
        pass
    def sample(self, now):
        return Sample("batch-a", 0)
    def storage(self):
        return {"freeBytes": 3 * 1024**3, "totalBytes": 24 * 1024**3,
                "hogs": {"share": 100}, "partialCount": 1, "partialBytes": 2048}
    def restart_photos(self, expected_batch):
        self.restarts += 1
    def report(self, status):
        self.reported.append(status)


DF_OUTPUT = ("Filesystem     1K-blocks     Used Available Use% Mounted on\n"
             "/dev/block/dm-4 25000000 16749000  8251000  67% /data\n")


def test_df_und_du_ausgaben_werden_in_bytes_uebersetzt():
    assert parse_df(DF_OUTPUT) == {"freeBytes": 8251000 * 1024,
                                  "totalBytes": 25000000 * 1024}
    assert parse_df("kein df") is None
    assert parse_df("") is None


def test_speicherausgabe_laesst_unbekanntes_weg_statt_zu_raten():
    text = ("@@df\n" + DF_OUTPUT + "@@share\n1048576\t/sdcard/DCIM/PixelSync\n"
            "@@photos_external\n\n@@lost_dir\nkeine zahl\n"
            "@@partial_count\n3\n@@partial_kb\n2048\n@@temp_count\n0\n")
    parsed = parse_storage(text)
    assert parsed["hogs"]["share"] == 1048576 * 1024
    assert "photos_external" not in parsed["hogs"]
    assert "lost_dir" not in parsed["hogs"]
    assert parsed["partialCount"] == 3
    assert parsed["partialBytes"] == 2048 * 1024
    assert parsed["tempCount"] == 0
    assert parsed["freeBytes"] == 8251000 * 1024


def test_speichermessung_landet_im_status_ohne_das_budget_zu_beruehren(tmp_path):
    adb = FakeAdb()
    status = cycle(adb, tmp_path / "state.json", True, 60)
    assert status["storage"]["hogs"]["share"] == 100
    assert status["storage"]["observedAt"] == 60
    assert status["state"] == "tracking"


def test_adb_skript_ueberlebt_eine_echte_shell_und_findet_auch_tiefe_teilkopien(tmp_path):
    """Das Skript ist eine einzige Quoting-Kette; hier laeuft es wirklich durch `sh`.

    Ein Glob auf feste Tiefe hat in der Erprobung still 0 Byte gemeldet, weil die
    Teilkopien unter staging/Batches/<id>/... liegen. Deshalb `find`: der Test legt
    genau diese Tiefe an und verlangt ihre Bytes zurueck.
    """
    import shutil
    import subprocess
    for tool in ("sh", "find", "du", "awk", "wc"):
        if not shutil.which(tool):
            pytest.skip(f"{tool} fehlt")

    adb = Adb("adb", "dummy")
    captured = []
    def fake_run(*args):
        if args and args[0] == "shell":
            captured.append(args[1])
        return ""
    adb.run = fake_run
    assert adb.storage() == {"hogs": {}}  # leere ADB-Ausgabe bleibt ehrlich leer
    command = captured[-1]

    root = tmp_path / "PixelSync"
    (root / "staging/Batches/b1/deep/nested").mkdir(parents=True)
    (root / "staging/Batches/b1/a.jpg.!sync").write_bytes(b"x" * 8192)
    (root / "staging/Batches/b1/deep/nested/b.jpg.!sync").write_bytes(b"x" * 4096)
    # Nutzdatei und Marker sind keine Reste und duerfen die Zaehlung nicht verfaelschen.
    (root / "staging/Batches/b1/c.jpg").write_bytes(b"z" * 4096)
    (root / "staging/Batches/b1/_batch-manifest.json").write_text("{}", encoding="utf-8")
    (root / "control").mkdir()
    (root / "control/.receipt-1.tmp").write_bytes(b"y" * 512)
    local = command.replace("/sdcard/DCIM/PixelSync", str(root))
    result = subprocess.run(["sh", "-c", local], capture_output=True, text=True, timeout=60)

    parsed = parse_storage(result.stdout)
    assert parsed["partialCount"] == 2
    assert parsed["partialBytes"] >= 8192 + 4096  # 1K-Bloecke, nie stillschweigend 0
    assert parsed["tempCount"] == 1
    assert parsed["hogs"]["staging"] >= 8192


def test_fehlgeschlagene_speichermessung_haelt_den_waechter_nicht_an(tmp_path):
    """Ein fehlgeschlagenes `du` ist kein Stillstand von Google Fotos."""
    adb = FakeAdb()
    def broken():
        raise ValueError("du nicht moeglich")
    adb.storage = broken
    status = None
    for now in range(0, 1920, 60):
        status = cycle(adb, tmp_path / "state.json", True, now)
    assert adb.restarts >= 1  # der Neustart-Automat laeuft unveraendert weiter
    assert status["state"] == "restarted"
    assert status["storage"] is None


def test_restart_is_persisted_before_action_and_does_not_repeat_after_crash(tmp_path):
    adb = FakeAdb()
    state = tmp_path / "state.json"
    for now in range(0, 1800, 60):
        cycle(adb, state, True, now)
    def crash(expected_batch):
        assert json.loads(state.read_text())["stage"] == "restarted"
        adb.restarts += 1
        raise subprocess.TimeoutExpired("adb", 30)
    adb.restart_photos = crash
    assert cycle(adb, state, True, 1800)["state"] == "offline"
    cycle(adb, state, True, 1860)
    assert adb.restarts == 1


def test_wrong_device_is_rejected_before_any_mutation(monkeypatch):
    adb = Adb("adb", "usb-device")
    calls = []
    def run(*args, **kwargs):
        calls.append(args)
        return "5C230DLCH003RC"
    monkeypatch.setattr(adb, "run", run)
    with pytest.raises(ValueError):
        adb.restart_photos("batch-a")
    assert all("force-stop" not in call for call in calls)


def test_observation_only_cannot_restart(tmp_path):
    adb = FakeAdb()
    state = tmp_path / "state.json"
    for now in range(0, 1860, 60):
        cycle(adb, state, False, now)
    assert adb.restarts == 0
    assert adb.reported[-1]["state"] == "alert"


def test_actual_restart_only_stops_photos_and_rechecks_batch(monkeypatch):
    import app.photos_watchdog as module
    prefs = active_prefs()
    xml = '<map>' + ''.join(
        f'<boolean name="{k}" value="{str(v).lower()}"/>' if isinstance(v, bool)
        else f'<long name="{k}" value="{v}"/>' if isinstance(v, int)
        else f'<string name="{k}">{v}</string>'
        for k, v in prefs.items()) + '</map>'
    adb = Adb("adb", "usb-device")
    calls = []
    def run(*args, **kwargs):
        calls.append(args)
        if "ro.serialno" in args:
            return module.PIXEL_SERIAL
        if "ro.product.model" in args:
            return "Pixel"
        if "run-as" in args:
            return xml
        return ""
    monkeypatch.setattr(adb, "run", run)
    monkeypatch.setattr(module.time, "time", lambda: 60)
    adb.restart_photos(module.batch_key(prefs))
    assert calls[-2:] == [("shell", "am", "force-stop", module.PHOTOS),
                          ("shell", "am", "start", "-n", module.PHOTOS + "/.home.HomeActivity")]
    calls.clear()
    with pytest.raises(ValueError):
        adb.restart_photos("other-batch")
    assert all("force-stop" not in call for call in calls)


def test_unknown_metrics_leave_budget_and_status_safe(tmp_path):
    adb = FakeAdb()
    def unavailable(now):
        raise ValueError("Keine UID-Messung")
    adb.sample = unavailable
    status = cycle(adb, tmp_path / "state.json", True, 1800)
    assert status["state"] == "offline"
    assert adb.restarts == 0
