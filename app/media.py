"""Media helpers: stability check, date detection, category.

Windows uses System.Drawing + Shell.Application (COM). Both are unavailable
on Linux, so this uses Pillow (EXIF DateTimeOriginal) with filename/mtime
fallback. Behavior for Screenshots/Memes rules is kept identical.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

DATE_RE = re.compile(
    r"(?<!\d)(?P<year>20\d{2})[-._]?(?P<month>0[1-9]|1[0-2])[-._]?(?P<day>0[1-9]|[12]\d|3[01])(?!\d)"
)
SCREENSHOT_RE = re.compile(r"screenshot|screen[ _-]?shot|bildschirmfoto|bildschirmaufnahme", re.I)
MEME_RE = re.compile(r"meme|sticker|giphy|tenor|9gag", re.I)


def is_file_ready(path: Path, stable_before_utc: datetime) -> bool:
    """Stable = mtime older than threshold + readable. Linux has no Win32
    exclusive-open semantics; readability + mtime is the portable equivalent."""
    try:
        st = path.stat()
    except OSError:
        return False
    mtime = datetime.fromtimestamp(st.st_mtime, tz=timezone.utc)
    if mtime > stable_before_utc:
        return False
    try:
        with path.open("rb"):
            pass
    except OSError:
        return False
    return True


def media_date(path: Path) -> datetime:
    suffix = path.suffix.lower()
    if suffix in {".jpg", ".jpeg", ".tif", ".tiff"}:
        dt = _exif_original(path)
        if dt is not None:
            return dt
    m = DATE_RE.search(path.name)
    if m:
        try:
            return datetime(int(m["year"]), int(m["month"]), int(m["day"]))
        except ValueError:
            pass
    try:
        return datetime.fromtimestamp(path.stat().st_mtime)
    except OSError:
        return datetime.now()


def _exif_original(path: Path) -> datetime | None:
    try:
        from PIL import Image  # type: ignore
        from PIL.ExifTags import TAGS  # type: ignore
    except Exception:
        return None
    try:
        with Image.open(path) as img:
            exif = img.getexif()
            if not exif:
                return None
            for tag_id, value in exif.items():
                if TAGS.get(tag_id) == "DateTimeOriginal":
                    try:
                        return datetime.strptime(str(value), "%Y:%m:%d %H:%M:%S")
                    except ValueError:
                        return None
    except Exception:
        return None
    return None


def image_dimensions(path: Path) -> tuple[int, int]:
    try:
        from PIL import Image  # type: ignore
    except Exception:
        return (0, 0)
    try:
        with Image.open(path) as img:
            return (int(img.width), int(img.height))
    except Exception:
        return (0, 0)


def media_category(path: Path) -> str:
    if SCREENSHOT_RE.search(path.name):
        return "Screenshots"
    ext = path.suffix.lower()
    width, height = (0, 0)
    try:
        size = path.stat().st_size
    except OSError:
        size = 0
    if ext in {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"} and size <= 5 * 1024 * 1024:
        width, height = image_dimensions(path)
    if ext == ".png" and width > 0 and height > 0:
        portrait = height >= 1200 and (height / float(width)) >= 1.45
        landscape = width >= 1200 and (width / float(height)) >= 1.45
        if portrait or landscape:
            return "Screenshots"
    if MEME_RE.search(path.name):
        return "Memes"
    if ext in {".gif", ".webp"} and size <= 1024 * 1024:
        return "Memes"
    return "Archive"
