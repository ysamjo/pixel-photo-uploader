"""Web UI: status, setup form and run buttons. CLI and watcher stay authoritative.

The page is server-rendered HTML with a meta refresh, so it works without
assets, JavaScript or a second port. The buttons only queue a request; the
watcher process is the one that runs the cycle (see runner.py).
"""
from __future__ import annotations

import html
from pathlib import Path
from urllib.parse import parse_qs

try:
    from fastapi import FastAPI, Request
    from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
except ImportError:  # pragma: no cover
    FastAPI = Request = None  # type: ignore

from . import APP_VERSION
from . import log_path as default_log_path
from . import runner
from .setup import apply_setup

REFRESH_SECONDS = 45
COMPANION_LOG_NAME = "companion-log.txt"


def _esc(value) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def overview(cfg: dict) -> dict:
    """Status numbers without printing (shared by CLI and web)."""
    from .batches import backup_timeout_hours, batch_gib_clamped
    from .store import (blocked_fingerprints, load_catalog, load_completion_sets,
                        load_staged)
    from .sync import deep_rescan_days

    catalog = load_catalog()
    fps, _ = load_completion_sets()
    blocked = blocked_fingerprints()
    stable_open = [e for e in catalog
                   if str(e.get("Stable")) == "True"
                   and str(e.get("Fingerprint", "")).lower() not in fps
                   and str(e.get("Fingerprint", "")).lower() not in blocked]
    stable_seconds = int(float(cfg.get("StableMinutes", 2.0)) * 60)
    setup = {
        "DropboxRoot": str(cfg.get("DropboxRoot", "")),
        "OneDriveRoot": str(cfg.get("OneDriveRoot", "")),
        "InboxRoot": str(cfg.get("InboxRoot", "")),
        "SourceRoot": str(cfg.get("SourceRoot", "")),
        "StagingRoot": str(cfg.get("StagingRoot", "")),
        "ControlRoot": str(cfg.get("ControlRoot", "")),
        "BatchGiB": f"{batch_gib_clamped(cfg):g}",
        "StableSeconds": str(stable_seconds),
        "RescanMinutes": str(int(cfg.get("RescanMinutes", 360))),
        "DeepRescanDays": str(int(deep_rescan_days(cfg))),
        "BackupTimeoutHours": f"{backup_timeout_hours(cfg):g}",
    }
    return {
        "version": APP_VERSION,
        "configured": True,
        "archive": setup["SourceRoot"],
        "staging": setup["StagingRoot"],
        "control": setup["ControlRoot"],
        "import_enabled": bool(cfg.get("ImportEnabled")),
        "batch_gib": float(setup["BatchGiB"]),
        "stable_seconds": stable_seconds,
        "rescan_minutes": int(cfg.get("RescanMinutes", 360)),
        "deep_rescan_days": deep_rescan_days(cfg),
        "backup_timeout_hours": backup_timeout_hours(cfg),
        "catalog_files": len(catalog),
        "completed": len(fps),
        "staged": len(load_staged()),
        "blocked": len(blocked),
        "open_stable": len(stable_open),
        "open_bytes": sum(int(e.get("Size", 0) or 0) for e in stable_open),
        "running": runner.holder(),
        "pending": runner.pending_request(),
        "setup": setup,
    }


def _gib(value) -> str:
    try:
        return f"{float(value) / 1024**3:.2f} GiB"
    except (TypeError, ValueError):
        return "-"


def _number(value) -> str:
    try:
        return str(int(value))
    except (TypeError, ValueError):
        return "-"


def _num(value) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "-"
    return str(int(number)) if number.is_integer() else f"{number:g}"


PAGE_STYLE = """
body{font:15px/1.45 ui-sans-serif,system-ui,sans-serif;margin:0;padding:20px;background:#f6f7f9;color:#1c2024}
h1{font-size:19px;margin:0 0 4px}
.sub{color:#6b7480;margin:0 0 18px;font-size:13px}
h2{font-size:13px;text-transform:uppercase;letter-spacing:.04em;color:#6b7480;margin:22px 0 8px}
section{background:#fff;border:1px solid #e3e6ea;border-radius:10px;padding:14px 16px;margin-bottom:14px}
ul{list-style:none;margin:0;padding:0;display:flex;flex-wrap:wrap;gap:6px 26px}
li{min-width:120px}
b{display:block;font-size:22px;font-weight:600}
span{color:#6b7480;font-size:12px}
.pill{display:inline-block;padding:2px 9px;border-radius:99px;font-size:12px;background:#e8f0fe;color:#1a56b4}
.pill.idle{background:#e6f4ea;color:#1e7e34}.pill.busy{background:#fce8e6;color:#b3261e}
.row{display:flex;gap:10px;flex-wrap:wrap;align-items:center}
button{font:inherit;padding:8px 14px;border-radius:8px;border:1px solid #c9ced4;background:#fff;cursor:pointer}
button.primary{background:#1a56b4;border-color:#1a56b4;color:#fff}
label{display:block;font-size:12px;color:#6b7480;margin:10px 0 3px}
input{font:inherit;padding:7px 9px;border:1px solid #c9ced4;border-radius:8px;width:min(460px,100%);box-sizing:border-box}
.note{font-size:13px;color:#6b7480;margin:8px 0}
.err{color:#b3261e}.ok{color:#1e7e34}
pre{background:#12161a;color:#d7dde3;padding:12px;border-radius:8px;font-size:12px;overflow:auto;max-height:330px;margin:0}
"""


SETUP_FIELDS = (
    ("SourceRoot", "Archiv-Ordner (von hier wird nur kopiert)", True),
    ("StagingRoot", "Uebergabe-Ordner (Resilio-Freigabe A)", True),
    ("ControlRoot", "Rueckbeleg-Ordner (Resilio-Freigabe B)", True),
    ("InboxRoot", "Inbox-Ordner (lokaler Eingang)", False),
    ("DropboxRoot", "Dropbox-Ordner (leer = kein Import)", False),
    ("OneDriveRoot", "OneDrive-Ordner (leer = kein Import)", False),
    ("BatchGiB", "Batch-groesse in GiB (0,25 bis 10)", False),
    ("StableSeconds", "Stabilitaet in Sekunden", False),
    ("RescanMinutes", "Grundabgleich alle Minuten", False),
    ("DeepRescanDays", "Vollabgleich alle Tage", False),
    ("BackupTimeoutHours", "Abbruch nach Stunden ohne Rueckbeleg (1 bis 720)", False),
)
SETUP_DEFAULTS = {
    "SourceRoot": "/data/archive", "StagingRoot": "/data/staging",
    "ControlRoot": "/data/control", "InboxRoot": "/data/inbox",
    "DropboxRoot": "/data/dropbox", "OneDriveRoot": "/data/onedrive",
    "BatchGiB": "5", "StableSeconds": "120", "RescanMinutes": "360",
    "DeepRescanDays": "7", "BackupTimeoutHours": "72",
}


def render_page(info: dict, log_lines=(), message: str = "",
                message_kind: str = "ok", values: dict | None = None,
                companion_lines=()) -> str:
    if info.get("configured"):
        pending = str(info.get("pending") or "")
        running = str(info.get("running") or "")
        if running:
            state, css = "Laeuft gerade", "busy"
        elif pending:
            state, css = ("Vollabgleich eingereiht" if pending == "deep"
                          else "Sync eingereiht"), "busy"
        else:
            state, css = "Bereit", "idle"
        counters = (
            f"<li><b>{_number(info.get('catalog_files'))}</b>im Katalog</li>"
            f"<li><b>{_number(info.get('open_stable'))}</b>offen ({_gib(info.get('open_bytes'))})</li>"
            f"<li><b>{_number(info.get('staged'))}</b>auf dem Pixel</li>"
            f"<li><b>{_number(info.get('completed'))}</b>abgeschlossen</li>"
            f"<li><b>{_number(info.get('blocked'))}</b>blockiert</li>"
        )
        settings = (
            f"Grundabgleich: alle {_number(info.get('rescan_minutes'))} min &middot; "
            f"Vollabgleich: alle {_num(info.get('deep_rescan_days'))} Tage &middot; "
            f"Stabilitaet: {_number(info.get('stable_seconds'))} s &middot; "
            f"Batch: {_num(info.get('batch_gib'))} GiB &middot; "
            f"Abbruch: nach {_num(info.get('backup_timeout_hours'))} h ohne Beleg"
        )
        status_section = (
            f"<section><ul>{counters}</ul>"
            f"<p class=\"note\">{settings}</p>"
            "<p class=\"note\">"
            f"Archiv: {_esc(info.get('archive'))}<br>"
            f"Ubergabe: {_esc(info.get('staging'))}<br>"
            f"Rueckbelege: {_esc(info.get('control'))}</p></section>"
        )
        actions = (
            "<section><div class=\"row\">"
            "<form method=\"post\" action=\"/api/sync\">"
            "<input type=\"hidden\" name=\"kind\" value=\"sync\">"
            "<button class=\"primary\" type=\"submit\">Sync jetzt</button></form>"
            "<form method=\"post\" action=\"/api/sync\">"
            "<input type=\"hidden\" name=\"kind\" value=\"deep\">"
            "<button type=\"submit\">Vollabgleich jetzt</button></form>"
            "</div></section>"
        )
        refresh = f"<meta http-equiv=\"refresh\" content=\"{REFRESH_SECONDS}\">"
        setup_open = ""
    else:
        state, css = _esc(info.get("hint") or "Nicht eingerichtet"), "busy"
        status_section = actions = refresh = ""
        setup_open = " open"

    saved = dict(SETUP_DEFAULTS)
    saved.update({str(k): str(v) for k, v in (info.get("setup") or {}).items()})
    typed = dict(saved)
    typed.update({str(k): str(v) for k, v in (values or {}).items()})
    fields = "".join(
        f"<label>{_esc(label)}</label>"
        f"<input name=\"{name}\" value=\"{_esc(typed.get(name, ''))}\""
        f"{' required' if required else ''}>"
        for name, label, required in SETUP_FIELDS
    )
    setup = (
        "<h2>Einrichtung</h2><section><details" + setup_open + ">"
        "<summary class=\"note\">Pfade und Groessen setzen (einmalig)</summary>"
        f"<form method=\"post\" action=\"/api/setup\">{fields}"
        "<div class=\"row\" style=\"margin-top:14px\">"
        "<button class=\"primary\" type=\"submit\">Speichern</button></div>"
        "</form></details></section>"
    )

    note = f"<p class=\"note {message_kind}\">{_esc(message)}</p>" if message else ""
    log = "\n".join(str(line) for line in log_lines) or "(noch kein Log)"
    pixel = ("\n".join(str(line) for line in companion_lines)
             if info.get("configured") and companion_lines else "")
    pixel_section = (f"<h2>Pixel meldet</h2><section><pre>{_esc(pixel)}</pre></section>"
                     if pixel else "")
    return (
        "<!doctype html><html lang=\"de\"><head><meta charset=\"utf-8\">"
        f"<title>Pixel Photo Uploader</title>{refresh}"
        f"<style>{PAGE_STYLE}</style></head><body>"
        "<h1>Pixel Photo Uploader</h1>"
        f"<p class=\"sub\">v{_esc(info.get('version'))} &middot; App + Resilio "
        f"&middot; <span class=\"pill {css}\">{_esc(state)}</span></p>"
        f"{note}{status_section}{actions}{setup}"
        f"{pixel_section}"
        "<h2>Letzte Meldungen</h2><section>"
        f"<pre>{_esc(log)}</pre></section>"
        "</body></html>"
    )


def handle_setup(values: dict) -> dict:
    result = apply_setup(values)
    if not result["ok"]:
        return {"ok": False, "message": "; ".join(result["errors"]),
                "message_kind": "err"}
    cfg = result["config"]
    return {"ok": True,
            "message": f"Eingerichtet: Grundabgleich alle {cfg['RescanMinutes']} min, "
                       f"Vollabgleich alle {cfg['DeepRescanDays']} Tage.",
            "message_kind": "ok"}


def handle_request_sync(values: dict) -> dict:
    kind = "deep" if str(values.get("kind", "")).lower() == "deep" else "sync"
    runner.request_sync(kind)
    return {"ok": True, "kind": kind,
            "message": "Vollabgleich eingereiht." if kind == "deep"
            else "Sync eingereiht."}


def _form(request_body: bytes) -> dict:
    parsed = parse_qs(request_body.decode("utf-8", "replace"))
    return {k: v[0] for k, v in parsed.items() if v}


def read_log(lines: int = 200, path: Path | None = None) -> list[str]:
    p = path or default_log_path()
    if not p.exists():
        return []
    return p.read_text(encoding="utf-8", errors="replace").splitlines()[-max(1, lines):]


def companion_lines(control_root, limit: int = 15) -> list[str]:
    """Tail of what the Pixel app wrote into the return-receipt share."""
    if not str(control_root or "").strip():
        return []
    p = Path(str(control_root)) / COMPANION_LOG_NAME
    if not p.is_file():
        return []
    return p.read_text(encoding="utf-8", errors="replace").splitlines()[-max(1, limit):]


def create_app() -> "FastAPI":
    app = FastAPI(title=f"Pixel Photo Uploader {APP_VERSION}")

    def _page(message: str = "", kind: str = "ok", values: dict | None = None) -> str:
        from .config import load_config
        try:
            info = overview(load_config())
        except FileNotFoundError:
            info = {"version": APP_VERSION, "configured": False}
        except ValueError as exc:
            info = {"version": APP_VERSION, "configured": False}
            message, kind = str(exc), "err"
        return render_page(info, log_lines=read_log(120), message=message,
                           message_kind=kind, values=values,
                           companion_lines=companion_lines(info.get("control")))

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return _page()

    @app.post("/api/setup", response_class=HTMLResponse)
    async def setup(request: "Request") -> str:
        form = _form(await request.body())
        result = handle_setup(form)
        return _page(result["message"], result.get("message_kind", "ok"), form)

    @app.post("/api/sync")
    async def sync_now(request: "Request") -> "RedirectResponse":
        handle_request_sync(_form(await request.body()))
        return RedirectResponse(url="/", status_code=303)

    @app.get("/api/status")
    def api_status() -> dict:
        from .config import load_config
        try:
            return overview(load_config())
        except FileNotFoundError:
            return {"version": APP_VERSION, "configured": False,
                    "hint": "Noch nicht eingerichtet: Seite oeffnen und Einrichtung ausfuellen."}
        except ValueError as exc:
            return {"version": APP_VERSION, "configured": False, "hint": str(exc)}

    @app.get("/api/log", response_class=PlainTextResponse)
    def api_log(lines: int = 200) -> str:
        tail = read_log(lines)
        return "\n".join(tail) if tail else "(no log yet)"

    return app


if FastAPI is not None:
    app = create_app()
