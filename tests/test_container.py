"""Prueft die Container-Dateien gegen die ZimaOS-Vorgaben.

Docker laeuft auf dem Entwicklungsrechner nicht zwingend, deshalb pruefen
diese Tests die Dateien selbst. Die Vorgaben, die ZimaOS an eine
App-Definition stellt, sind formal genug, um sie ohne Docker zu kontrollieren.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
COMPOSE = ROOT / "docker-compose.yml"
COMPOSE_LOCAL = ROOT / "docker-compose.local.yml"
DOCKERFILE = ROOT / "Dockerfile"

APP_PORT = 8088

KATEGORIEN = {
    "Media",
    "Productivity",
    "Home",
    "Networking",
    "AI",
    "Finance",
    "Social",
    "Developer",
    "Others",
}


def _load(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _skalare(wert: Any) -> Iterator[str]:
    """Alle Zeichenketten aus einer verschachtelten Struktur."""
    if isinstance(wert, dict):
        for schluessel, inhalt in wert.items():
            yield str(schluessel)
            yield from _skalare(inhalt)
    elif isinstance(wert, list):
        for eintrag in wert:
            yield from _skalare(eintrag)
    elif wert is not None:
        yield str(wert)


@pytest.fixture(scope="module")
def compose() -> dict[str, Any]:
    return _load(COMPOSE)


@pytest.fixture(scope="module")
def casaos(compose: dict[str, Any]) -> dict[str, Any]:
    return compose["x-casaos"]


@pytest.fixture(scope="module")
def server_dienst(compose: dict[str, Any]) -> dict[str, Any]:
    return compose["services"]["server"]


@pytest.fixture(scope="module")
def dockerfile() -> str:
    return DOCKERFILE.read_text(encoding="utf-8")


# -- Aufbau der Dateien ----------------------------------------------------


def test_name_ist_gesetzt(compose):
    """ZimaOS nimmt den obersten Namen als App-Kennung und Ordnernamen."""
    assert re.fullmatch(r"[a-z0-9][a-z0-9._-]*", str(compose["name"]))


def test_casaos_block_steht_auf_oberster_ebene(compose, casaos):
    assert "x-casaos" in compose
    assert "x-casaos" not in compose["services"]["server"]
    assert isinstance(casaos, dict)


def test_main_zeigt_auf_die_web_anwendung(compose, casaos):
    assert casaos["main"] in compose["services"]
    assert "image" in compose["services"][casaos["main"]]


def test_neustart_ist_eingestellt(server_dienst):
    assert server_dienst["restart"] in {"unless-stopped", "always"}


def test_port_map_ist_zeichenkette(casaos):
    """CasaOS/ZimaOS parst port_map als String."""
    assert isinstance(casaos["port_map"], str)
    assert int(casaos["port_map"]) == APP_PORT


def test_kein_dollar_in_irgendeinem_wert(compose):
    """ZimaOS setzt Variablen selbst ein - Platzhalter fuehren zu Fehlern."""
    for text in _skalare(compose):
        assert "$" not in text, f"Gefunden: {text!r}"


def test_kein_build_im_zimaos_compose(compose):
    """ZimaOS baut keine Images selbst, sondern laedt fertige."""
    for name, dienst in compose.get("services", {}).items():
        assert "build" not in dienst, f"Service {name} hat noch build:"


def test_kategorie_ist_erlaubt(casaos):
    assert casaos["category"] in KATEGORIEN


def test_titel_und_beschreibung_haben_mindestens_en_us(casaos):
    for feld in ("title", "tagline", "description"):
        assert feld in casaos
        wert = casaos[feld]
        assert isinstance(wert, dict)
        assert "en_US" in wert
        assert wert["en_US"].strip()


def test_architekturen_enthalten_amd64_und_arm64(casaos):
    archs = set(casaos.get("architectures", []))
    assert "amd64" in archs
    assert "arm64" in archs


def test_ports_sind_als_zeichenkette_deklariert(server_dienst):
    ports = server_dienst.get("ports", [])
    assert ports, "server-Dienst braucht eine Port-Freigabe"
    for port in ports:
        if isinstance(port, dict):
            assert str(port.get("target")) == "8000"
            assert str(port.get("published")) == str(APP_PORT)
            assert isinstance(port.get("published"), str)


def test_volumes_liegen_unter_data(compose):
    """ZimaOS erwartet Datenpfade unter /DATA/ oder /media/ (fuer Cloud-Mounts)."""
    for dienst_name, dienst in compose.get("services", {}).items():
        for volume in dienst.get("volumes", []):
            host_path = volume.split(":")[0] if isinstance(volume, str) else volume.get("source", "")
            assert host_path.startswith("/DATA/") or host_path.startswith("/media/"), f"{dienst_name}: {host_path} liegt nicht unter /DATA/ oder /media/"


def test_dockerfile_existiert(dockerfile):
    assert "FROM python:3.12-slim" in dockerfile
    assert "WORKDIR /app" in dockerfile
    assert "requirements.txt" in dockerfile


def test_lokale_compose_datei_hat_build(compose):
    assert COMPOSE_LOCAL.exists()
    lokal = _load(COMPOSE_LOCAL)
    for dienst_name, dienst in lokal.get("services", {}).items():
        assert "build" in dienst, f"Lokaler Dienst {dienst_name} sollte build: haben"
