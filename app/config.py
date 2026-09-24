"""Config load/save. Schema mirrors config.json v3 from the Windows script."""
from __future__ import annotations

import json
from pathlib import Path

from . import config_path, state_root

DEFAULTS: dict = {
    "Version": 3,
    "TransportMode": "App",  # Umbrel port supports App (+Resilio) only
    "ConnectionMode": "App",
    "Serial": "",
    "UsbSerial": "",
    "WiFiEndpoint": "",
    "StagingRoot": "",
    "ControlRoot": "",
    "ResilioEnabled": False,
    "ResilioRemoteRoot": "/sdcard/DCIM/ResilioInbox",
    "KeepAwake": True,
    "RequireUnlocked": True,
    "ImportEnabled": False,
    "DropboxRoot": "",
    "InboxRoot": "",
    "SourceRoot": "",
    "BatchGiB": 5.0,
    "ReserveGiB": 1.5,
    "StableMinutes": 2.0,
    "RescanMinutes": 360,
    "DeepRescanDays": 7,
    "ScanGraceMinutes": 5,
    "BackupPollSeconds": 45,
    "BackupTimeoutHours": 72,
    "RemoteRoot": "/sdcard/DCIM/Camera/PixelUploader",
}


def _validate_roots(cfg: dict) -> None:
    """Re-check on every load: setup is not the only writer of config.json.

    An empty root would become '.' and a folder inside the archive would let the
    sort step move archive files instead of only copying them out.
    """
    required = ["SourceRoot", "StagingRoot", "ControlRoot"]
    if cfg.get("ImportEnabled"):
        required = ["DropboxRoot", "InboxRoot"] + required
    roots: dict[str, Path] = {}
    for name in required:
        raw = str(cfg.get(name, "")).strip()
        if not raw:
            raise ValueError(
                f"{name} is empty while the config expects it. Re-run 'setup'.")
        roots[name] = Path(raw).expanduser().resolve()
    names = sorted(roots)
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            a, b = names[i], names[j]
            if roots[a] == roots[b] or roots[a].is_relative_to(roots[b]) \
                    or roots[b].is_relative_to(roots[a]):
                raise ValueError(
                    f"Folders '{a}' and '{b}' must not be equal or nested "
                    f"(found {roots[a]} and {roots[b]}).")


def load_config(path: Path | None = None) -> dict:
    cfg_path = path or config_path()
    if not cfg_path.exists():
        raise FileNotFoundError(
            f"Not configured yet: {cfg_path} missing. Run 'setup' first."
        )
    data = json.loads(cfg_path.read_text(encoding="utf-8"))
    merged = dict(DEFAULTS)
    merged.update(data)
    # Legacy: TransportMode empty -> derive from ConnectionMode.
    if not str(merged.get("TransportMode", "")).strip():
        merged["TransportMode"] = (
            "WiFi" if str(merged.get("ConnectionMode")) == "WiFi" else "USB"
        )
    if str(merged["TransportMode"]) != "App":
        raise ValueError(
            "Umbrel port supports TransportMode='App' only "
            f"(found {merged['TransportMode']!r}). ADB stays Windows-only."
        )
    _validate_roots(merged)
    return merged


def save_config_atomic(cfg: dict, path: Path | None = None) -> None:
    cfg_path = path or config_path()
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = cfg_path.with_suffix(cfg_path.suffix + ".tmp")
    tmp.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(cfg_path)


def ensure_state_dir() -> Path:
    root = state_root()
    root.mkdir(parents=True, exist_ok=True)
    return root
