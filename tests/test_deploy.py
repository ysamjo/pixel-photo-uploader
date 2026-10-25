"""Deployment-Konfiguration pruefen, ohne Netzwerk oder Geraetezugriff."""
import copy
import hashlib
import importlib.util
from pathlib import Path
import subprocess

import pytest
import yaml


spec = importlib.util.spec_from_file_location("deploy", Path(__file__).parents[1] / "scripts/deploy.py")
deploy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(deploy)


def test_update_preserves_active_archive_mounts_ports_commands_and_other_services():
    config = {"name": "existing", "x-casaos": {"version": "old", "title": {"de_DE": "Fotos"}},
              "services": {s: {"image": "old", "command": ["old-command", s],
                               "environment": {"PPU_STATE_DIR": "/data/state"},
                               "volumes": ["/media/Data_1/Pictures:/data/archive/Altbestand:ro"],
                               "ports": ["8088:8000"]} for s in deploy.SERVICES}}
    config["services"]["unrelated"] = {"image": "leave-this-alone"}
    expected = copy.deepcopy(config)
    for service in deploy.SERVICES:
        expected["services"][service]["image"] = "pixel-photo-uploader:new"
    expected["x-casaos"]["version"] = "new"
    updated = deploy.updated_compose(yaml.safe_dump(config), "pixel-photo-uploader:new", "new")
    assert yaml.safe_load(updated) == expected


def test_missing_service_aborts_instead_of_generating_partial_deployment():
    with pytest.raises(RuntimeError, match="watcher fehlt"):
        deploy.updated_compose("services:\n  server:\n    image: old\n", "new", "new")


def test_paused_and_active_preferences_remain_distinguishable():
    prefs = deploy.preferences(b'<map><boolean name="enabled" value="false"/>'
                               b'<boolean name="safetyAccepted" value="true"/>'
                               b'<long name="updatedAt" value="123"/></map>')
    assert prefs == {"enabled": "false", "safetyAccepted": "true", "updatedAt": "123"}


def test_compose_plugin_is_preferred_when_available():
    calls = []
    def remote(*command):
        calls.append(command)
        return b"Docker Compose version v2.0.0"
    assert deploy.compose_cli(remote) == ["docker", "compose"]
    assert calls == [("docker", "compose", "version")]


def test_standalone_compose_is_used_when_plugin_is_missing():
    calls = []
    def remote(*command):
        calls.append(command)
        if command[:2] == ("docker", "compose"):
            raise subprocess.CalledProcessError(1, command)
        return b"docker-compose version 1.29.2"
    assert deploy.compose_cli(remote) == ["docker-compose"]
    assert calls == [("docker", "compose", "version"), ("docker-compose", "version")]


def test_missing_compose_aborts_during_read_only_detection():
    def remote(*command):
        assert command[-1] == "version" or command[:2] == ("test", "-x")
        raise subprocess.CalledProcessError(127, command)
    with pytest.raises(RuntimeError, match="weder docker compose noch docker-compose"):
        deploy.compose_cli(remote)


@pytest.mark.parametrize("help_text,expected", [
    (b"--no-build   Do not build an image", ["up", "-d", "--no-build"]),
    (b"--pull      Pull image before running", ["up", "-d", "--no-build"]),
    (b'--pull string  Pull image before running ("always"|"missing"|"never")',
     ["up", "-d", "--no-build", "--pull", "never"]),
])
def test_up_uses_only_supported_pull_options_for_start_and_rollback(help_text, expected):
    command = ["docker-compose", "--project-name", "existing", "-f", "/existing.yml"]
    def remote(*args):
        assert list(args) == command + ["up", "--help"]
        return help_text
    assert deploy.compose_up_options(remote, command) == expected


def test_plugin_outside_ssh_path_is_detected_without_installation():
    plugin = "/usr/libexec/docker/cli-plugins/docker-compose"
    def remote(*command):
        if command in [("test", "-x", plugin), (plugin, "version")]:
            return b"Docker Compose version v2"
        raise subprocess.CalledProcessError(1, command)
    assert deploy.compose_cli(remote) == [plugin]


@pytest.mark.parametrize("arch", ["x86_64", "aarch64"])
def test_provision_compose_checks_checksum_before_upload_and_execution(monkeypatch, arch):
    binary = b"test compose binary"
    digest = hashlib.sha256(binary).hexdigest()
    monkeypatch.setattr(deploy, "COMPOSE_SHA256", {arch: digest})
    calls = []
    def remote(*command, **kwargs):
        calls.append((command, kwargs))
        if command == ("uname", "-s"):
            return b"Linux\n"
        if command == ("uname", "-m"):
            return arch.encode()
        if command[:2] == ("test", "-x"):
            raise subprocess.CalledProcessError(1, command)
        if command[0] == "sha256sum":
            return (digest + "  compose").encode()
        return b"Docker Compose version v2.40.3"
    urls = []
    def fetch(url):
        urls.append(url)
        return binary
    command = deploy.provision_compose(remote, fetch)
    assert urls == [f"https://github.com/docker/compose/releases/download/v2.40.3/docker-compose-linux-{arch}"]
    assert command[0].startswith("/DATA/AppData/pixel-photo-uploader/deploy-tools/")
    assert calls[-2][0] == ("sha256sum", command[0])
    assert calls[-1][0] == (command[0], "version")
    uploads = [kwargs["data"] for _, kwargs in calls if "data" in kwargs]
    assert uploads == [binary]


def test_invalid_download_is_never_uploaded_or_executed():
    def remote(*command):
        if command == ("uname", "-s"):
            return b"Linux"
        if command == ("uname", "-m"):
            return b"x86_64"
        if command[:2] == ("test", "-x"):
            raise subprocess.CalledProcessError(1, command)
        pytest.fail(f"Kein Remote-Schreibzugriff oder Ausführen erwartet: {command}")
    with pytest.raises(RuntimeError, match="Prüfsumme"):
        deploy.provision_compose(remote, lambda url: b"corrupt")


def test_verified_existing_deploy_tool_is_reused_without_download_or_upload(monkeypatch):
    monkeypatch.setattr(deploy, "COMPOSE_SHA256", {"x86_64": "known-digest"})
    def remote(*command):
        if command == ("uname", "-s"):
            return b"Linux"
        if command == ("uname", "-m"):
            return b"x86_64"
        if command[:2] == ("test", "-x"):
            return b""
        if command[0] == "sha256sum":
            return b"known-digest  compose"
        if command[-1] == "version":
            return b"v2.40.3"
        pytest.fail(f"Unerwartete Änderung: {command}")
    def fetch(url):
        pytest.fail("Vorhandene geprüfte Datei benötigt keinen Download.")
    assert deploy.provision_compose(remote, fetch)[0].endswith("v2.40.3-x86_64")


def test_unknown_architecture_aborts_before_download_or_installation():
    def remote(*command):
        assert command[0] == "uname"
        return b"Linux" if command[1] == "-s" else b"unsupported"
    def fetch(url):
        pytest.fail("Unbekannte Architektur darf keinen Download auslösen.")
    with pytest.raises(RuntimeError, match="Architektur"):
        deploy.provision_compose(remote, fetch)


def test_compose_writer_uses_direct_write_when_file_is_writable():
    assert deploy.compose_writer(lambda *args: b"", "/compose.yml") == "user"


def test_compose_writer_uses_noninteractive_sudo_for_zimaos_owned_file():
    calls = []
    def remote(*args):
        calls.append(args)
        if args[:2] == ("test", "-w"):
            raise subprocess.CalledProcessError(1, args)
        return b""
    assert deploy.compose_writer(remote, "/compose.yml") == "sudo"
    assert calls == [("test", "-w", "/compose.yml"),
                     ("sudo", "-n", "test", "-w", "/compose.yml")]


def test_compose_writer_stops_before_mutation_if_sudo_is_unavailable():
    calls = []
    def remote(*args):
        calls.append(args)
        raise subprocess.CalledProcessError(1, args)
    with pytest.raises(RuntimeError, match="sudo -n darf sie nicht ändern"):
        deploy.compose_writer(remote, "/compose.yml")
    assert calls == [("test", "-w", "/compose.yml"),
                     ("sudo", "-n", "test", "-w", "/compose.yml")]


def test_compose_writer_authenticates_interactively_before_any_deploy_changes():
    calls = []
    authenticated = []
    def remote(*args):
        calls.append(args)
        if args[:2] == ("test", "-w"):
            raise subprocess.CalledProcessError(1, args)
        if args[:2] == ("sudo", "-n") and not authenticated:
            raise subprocess.CalledProcessError(1, args)
        return b""
    def authenticate():
        authenticated.append(True)
    assert deploy.compose_writer(remote, "/compose.yml", authenticate) == "sudo"
    assert calls == [("test", "-w", "/compose.yml"),
                     ("sudo", "-n", "test", "-w", "/compose.yml"),
                     ("sudo", "-n", "test", "-w", "/compose.yml")]
    assert authenticated == [True]


def test_compose_replacement_preserves_root_ownership_and_permissions():
    calls = []
    def remote(*args, **kwargs):
        calls.append((args, kwargs.get("data")))
        if args == ("cat", "/backup/new.yml"):
            return b"compose"
        return b""
    deploy.replace_compose(remote, "sudo", "/app/docker-compose.yml",
                           "/backup/new.yml", "0:0:644")
    assert calls == [(("sudo", "-n", "install", "-o", "0", "-g", "0", "-m", "644",
                       "/backup/new.yml", "/app/docker-compose.yml"), None)]
