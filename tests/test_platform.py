"""What differs between the Linux and Windows builds: serial ports, the state folder, updates."""

import json
from types import SimpleNamespace

import pytest

from talkpod_manager import __version__, paths, radio, updater

REL = "https://github.com/ssjrocks/talkpod-manager/releases/download/v9.0.0/"


def comport(device, vid=None, pid=None, description="n/a"):
    return SimpleNamespace(device=device, vid=vid, pid=pid, description=description)


PORTS = [comport("COM1"), comport("COM10", 0x1A86, 0x7523), comport("COM3", 0x0403, 0x6001),
         comport("COM4", 0x2341, 0x0043, "Arduino Uno (COM4)"), comport("/dev/ttyS0"),
         comport("/dev/ttyUSB0", 0x1A86, 0x7523), comport("/dev/ttyACM0", 0x2341, 0x0043, "ttyACM0")]


def test_ports_on_windows(monkeypatch):
    monkeypatch.setattr(radio.sys, "platform", "win32")
    monkeypatch.setattr(radio.list_ports, "comports", lambda: [p for p in PORTS if p.device.startswith("COM")])
    # USB ones only (COM1 is a built-in port), cables first, COM3 before COM10
    assert [(p.device, p.description) for p in radio.find_ports()] == [
        ("COM3", "FTDI cable"), ("COM10", "CH340 cable"), ("COM4", "Arduino Uno (COM4)")]


def test_ports_on_linux(monkeypatch):
    monkeypatch.setattr(radio.sys, "platform", "linux")
    monkeypatch.setattr(radio.list_ports, "comports", lambda: [p for p in PORTS if p.device.startswith("/dev")])
    assert [p.device for p in radio.find_ports()] == ["/dev/ttyUSB0", "/dev/ttyACM0"]


def test_state_dir_on_windows(tmp_path, monkeypatch):
    monkeypatch.setattr(paths.sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert paths.state_dir() == tmp_path / "Talkpod Manager"
    assert paths.state_dir().is_dir()


def fake_release(monkeypatch, info):
    rel = {"body": "notes", "published_at": "2026-11-08T00:00:00Z", "assets": [
        {"name": n, "browser_download_url": REL + n}
        for n in ("talkpod-manager.json", "talkpod_manager-9.0.0-py3-none-any.whl", "TalkpodManager-9.0.0-setup.exe")]}
    pages = {updater.API: rel, REL + "talkpod-manager.json": info}
    monkeypatch.setattr(updater, "_get", lambda url, timeout=20: json.dumps(pages[url]).encode())


INFO = {"version": "9.0.0", "wheel": "talkpod_manager-9.0.0-py3-none-any.whl", "sha256": "AA" * 32,
        "windows": {"file": "TalkpodManager-9.0.0-setup.exe", "sha256": "BB" * 32}}


@pytest.mark.parametrize("windows, name, sha", [
    (False, "talkpod_manager-9.0.0-py3-none-any.whl", "aa" * 32),
    (True, "TalkpodManager-9.0.0-setup.exe", "bb" * 32),
])
def test_update_picks_the_platforms_file(monkeypatch, windows, name, sha):
    monkeypatch.setattr(updater, "WINDOWS", windows)
    fake_release(monkeypatch, INFO)
    u = updater.check()
    assert (u.version, u.name, u.url, u.sha256) == ("9.0.0", name, REL + name, sha)


def test_no_windows_update_until_its_build_is_added(monkeypatch):
    monkeypatch.setattr(updater, "WINDOWS", True)
    fake_release(monkeypatch, {k: v for k, v in INFO.items() if k != "windows"})
    assert updater.check() is None
    monkeypatch.setattr(updater, "WINDOWS", False)
    assert updater.check().version == "9.0.0"


def test_no_update_to_the_same_version(monkeypatch):
    fake_release(monkeypatch, dict(INFO, version=__version__))
    assert updater.check() is None
