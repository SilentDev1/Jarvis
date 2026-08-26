"""Guards for local device gateway startup and service discovery.

The physical AiPi resolves Jarvis by an mDNS discovery name. If the gateway is
started without publishing that name, the device cannot resolve Jarvis, never
reaches ONLINE, and the speaker appears broken even though the codec is fine.
These tests pin the supervisor behaviour that prevents that class of failure.
"""

import plistlib
import stat
from pathlib import Path

ROOT = Path(__file__).parents[1]
SUPERVISOR = ROOT / "scripts" / "start-local-device-gateway.sh"
INSTALLER = ROOT / "scripts" / "install-launch-agents.sh"
PLIST = ROOT / "deploy" / "mac" / "com.jarvishome.local-device-gateway.plist"
LAUNCHER = ROOT / "deploy" / "mac" / "launcher" / "jarvis_gateway_launcher.c"


def test_supervisor_publishes_discovery_name_alongside_the_application():
    text = SUPERVISOR.read_text()
    assert "dns-sd -P" in text
    assert "_jarvis-device._tcp" in text
    assert "jarvis.local" in text
    # The advertisement must be started before the application is awaited, so a
    # reachable gateway is never left undiscoverable.
    assert text.index("start_mdns\npython") < text.index("python -m uvicorn")


def test_supervisor_restarts_a_dead_discovery_advertisement():
    text = SUPERVISOR.read_text()
    assert "discovery advertisement died" in text
    # Losing the advertisement does not stop the gateway, so it must be
    # detected by supervision rather than by process exit.
    assert "kill -0 \"$mdns_pid\"" in text


def test_supervisor_shutdown_reaps_children_and_releases_the_lock():
    text = SUPERVISOR.read_text()
    assert "trap cleanup EXIT INT TERM" in text
    cleanup = text.split("cleanup() {", 1)[1].split("}", 1)[0]
    # Both children must die with the supervisor; killing only the supervisor
    # previously orphaned uvicorn and left it holding the port.
    assert 'kill "$mdns_pid"' in cleanup
    assert 'kill "$app_pid"' in cleanup
    assert "kill -9" in cleanup
    assert 'rm -rf "$lock_dir"' in cleanup


def test_supervisor_shutdown_is_not_deferred_by_a_blocking_sleep():
    text = SUPERVISOR.read_text()
    # A foreground `sleep` defers the trap until it expires, which orphans the
    # children. The loop must wait on a backgrounded sleep instead.
    body = text.split("while kill -0 \"$app_pid\"", 1)[1]
    assert "sleep 5 &" in body
    assert "wait $!" in body


def test_supervisor_refuses_duplicate_and_unmanaged_instances():
    text = SUPERVISOR.read_text()
    assert 'mkdir "$lock_dir"' in text
    assert "not starting a second instance" in text
    assert "already in use by unmanaged pid" in text
    # Exit status of lsof is not a reliable "found nothing" signal.
    assert "-t 2>/dev/null" in text


def test_launch_agent_is_keepalive_and_runs_at_load():
    data = plistlib.loads(PLIST.read_bytes())
    assert data["Label"] == "com.jarvishome.local-device-gateway"
    assert data["RunAtLoad"] is True
    assert data["KeepAlive"] is True
    assert data["ThrottleInterval"] >= 10
    # Exactly one program argument: the dedicated launcher, no shell.
    assert data["ProgramArguments"] == ["__LAUNCHER__"]
    # launchd opens these paths before the granted process starts, so they must
    # not live inside the TCC-protected repository.
    assert "__LOGDIR__" in data["StandardOutPath"]


def test_launch_agent_does_not_set_a_protected_working_directory():
    data = plistlib.loads(PLIST.read_bytes())
    assert "WorkingDirectory" not in data


def test_launcher_is_minimal_and_takes_no_arguments():
    source = LAUNCHER.read_text()
    # The launcher exists so Full Disk Access can be granted to one
    # purpose-built binary instead of to /bin/sh. It must stay unrepurposable:
    # the target path is compiled in and no argv is accepted.
    assert "int main(void)" in source
    assert "JARVIS_GATEWAY_SCRIPT" in source
    assert "#error" in source
    assert "system(" not in source
    assert "getenv(" not in source


def test_installer_warns_when_the_repository_is_tcc_protected():
    text = INSTALLER.read_text()
    assert "Full Disk Access" in text
    assert "/Documents/*" in text
    assert "--uninstall" in text


def test_scripts_are_executable():
    for script in (SUPERVISOR, INSTALLER):
        assert script.stat().st_mode & stat.S_IXUSR


def test_every_env_variant_is_ignored_except_the_example():
    # A .env backup or per-host override carries live credentials and is easy
    # to create by accident; only the example may ever be tracked.
    ignore = (ROOT / ".gitignore").read_text()
    assert ".env.*" in ignore
    assert "!.env.example" in ignore
