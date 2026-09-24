"""Hashes, fingerprints, supported extensions.

Fingerprint stays compatible with the Windows PS1:
  normalized = relpath with '/' and '\\' -> '\\', lowercased
  text = f"{normalized}|{size}|{last_write_utc_iso}"
  fingerprint = sha256_utf8(text)
RelativePath itself is stored POSIX-style ('a/b.jpg') on Linux; only the
fingerprint normalizes the separator, so migrated catalogs keep matching.
The timestamp has to be rendered like .NET's round-trip format (see
win_roundtrip_utc) or every migrated fingerprint differs.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

TICKS_PER_SECOND = 10_000_000

SUPPORTED_EXTENSIONS = frozenset(
    {
        ".jpg", ".jpeg", ".jpe", ".png", ".gif", ".webp", ".bmp", ".heic", ".heif",
        ".tif", ".tiff", ".dng", ".arw", ".cr2", ".cr3", ".nef", ".nrw", ".orf",
        ".raf", ".rw2", ".pef", ".srw", ".3gp", ".3g2", ".mp4", ".m4v", ".mov",
        ".mkv", ".avi", ".wmv", ".mpg", ".mpeg", ".mts", ".m2ts", ".webm",
    }
)


def text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def win_roundtrip_utc(epoch_ns: int) -> str:
    """.NET DateTime.ToString('o') for a UTC value: 7 decimal fractions, 'Z'."""
    seconds, ticks = divmod(int(epoch_ns) // 100, TICKS_PER_SECOND)
    stamp = datetime.fromtimestamp(seconds, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    return f"{stamp}.{ticks:07d}Z"


def file_sha256(path: Path | str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def normalize_for_fingerprint(relative_posix: str) -> str:
    return relative_posix.replace("/", "\\").lower()


def fingerprint(relative_posix: str, size: int, last_write_utc_iso: str) -> str:
    normalized = normalize_for_fingerprint(relative_posix)
    return text_sha256(f"{normalized}|{int(size)}|{last_write_utc_iso}")


def is_supported_media(path: Path | str) -> bool:
    return Path(str(path)).suffix.lower() in SUPPORTED_EXTENSIONS
