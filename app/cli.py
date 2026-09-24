"""CLI: setup / sync / watch / status / preflight. App+Resilio only."""
from __future__ import annotations

import argparse

from . import APP_VERSION
from .config import ensure_state_dir, load_config
from .setup import apply_setup
from .sync import preflight, status, sync_once
from .watch import watch


def _ask(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    answer = input(f"{prompt}{suffix}: ").strip()
    return answer or default


def cmd_setup() -> None:
    print("Pixel Photo Uploader - Setup (Umbrel / Linux, App + Resilio)")
    print("Dropbox/Inbox are optional: leave empty to disable the import step.")
    values = {
        "DropboxRoot": _ask("Dropbox 'Camera Uploads' dir (empty = off)"),
        "InboxRoot": _ask("Inbox 'Eigene Aufnahmen' dir (empty = off)"),
        "SourceRoot": _ask("Archive dir (e.g. /data/archive)", "/data/archive"),
        "StagingRoot": _ask("Empty Resilio handover dir", "/data/staging"),
        "ControlRoot": _ask("Receipt dir synced from Pixel", "/data/control"),
        "BatchGiB": _ask("Max batch GiB", "5"),
        "StableSeconds": _ask("Stability wait seconds", "120"),
        "RescanMinutes": _ask("Archive check every minutes", "360"),
        "DeepRescanDays": _ask("Full archive pass every days", "7"),
    }
    result = apply_setup(values)
    if not result["ok"]:
        for err in result["errors"]:
            print(f"  - {err}")
        raise SystemExit("Setup aborted; nothing saved.")
    print("Pixel steps: handover share -> /storage/emulated/0/DCIM/ResilioInbox "
          "(read-only), control folder /storage/emulated/0/Documents/PixelPhotoControl "
          "-> this control dir.")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="ppu", description=f"Pixel Photo Uploader {APP_VERSION} (Umbrel port)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("setup")
    s = sub.add_parser("sync")
    s.add_argument("--deep", action="store_true", help="force a full archive pass")
    sub.add_parser("status")
    sub.add_parser("preflight")
    w = sub.add_parser("watch")
    w.add_argument("--poll-seconds", type=int, default=60)
    args = ap.parse_args(argv)
    ensure_state_dir()
    if args.cmd == "setup":
        cmd_setup()
    elif args.cmd == "sync":
        try:
            print(sync_once(force_deep=args.deep))
        except BlockingIOError as exc:
            raise SystemExit(str(exc))
    elif args.cmd == "watch":
        watch(args.poll_seconds)
    elif args.cmd == "status":
        status()
    elif args.cmd == "preflight":
        print(preflight(load_config()))
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
