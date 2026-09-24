"""Fingerprint compat with the Windows PS1 (PixelPhotoUploader.ps1:195-204)."""
from app.fingerprints import fingerprint, win_roundtrip_utc


def test_windows_vector():
    # PS1: Get-TextSha256("{normalized}|{size}|{lastwrite}") UTF8.
    # 'a/b.jpg' and 'a\\b.jpg' must yield the same fingerprint.
    a = fingerprint("a/b.jpg", 123, "2024-01-01T00:00:00+00:00")
    b = fingerprint("a\\b.jpg", 123, "2024-01-01T00:00:00+00:00")
    assert a == b
    assert len(a) == 64


def test_case_insensitive():
    assert fingerprint("A/B.JPG", 1, "x") == fingerprint("a/b.jpg", 1, "x")


def test_roundtrip_format_matches_net_tostring_o():
    # PowerShell: (Get-Item probe).LastWriteTimeUtc.ToString('o')
    # for st_mtime_ns 1790178669558542156 -> '...5585421Z'
    assert win_roundtrip_utc(1790178669558542156) == "2026-09-23T15:51:09.5585421Z"


def test_whole_second_keeps_seven_zeros():
    assert win_roundtrip_utc(1790178669000000000) == "2026-09-23T15:51:09.0000000Z"


def test_fingerprint_equals_the_measured_windows_digest():
    # Same file, measured on both sides: PS1 produced
    # c513f5fe12b10b03337b5d2d267e0b9b810fcf130044b316e537037a35e72ee7
    last_write = win_roundtrip_utc(1790178669558542156)
    assert fingerprint("a/b.jpg", 1, last_write) == (
        "c513f5fe12b10b03337b5d2d267e0b9b810fcf130044b316e537037a35e72ee7")
