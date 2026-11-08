"""Ready-to-flash firmware: the bundled copy, checksums, trusted sources, the latest-release lookup."""

import hashlib
import json

import pytest

from talkpod_manager import firmware_catalog as fc
from talkpod_manager import radio


@pytest.fixture(autouse=True)
def cache_in_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(fc.paths, "state_dir", lambda: tmp_path)


def no_network(*a, **k):
    raise AssertionError("went online")


def test_bundled_super_firmware_is_valid_and_offline(monkeypatch):
    monkeypatch.setattr(fc, "_get", no_network)
    image = fc.fetch(fc.TSF)
    assert hashlib.sha256(image.data).hexdigest() == fc.TSF.sha256
    assert image.version == "V1.26" and not image.problems


def test_every_build_comes_from_a_trusted_place_with_a_checksum():
    for b in fc.builds():
        assert fc._trusted(b.url), b.url
        assert len(b.sha256) == 64
        assert b.summary and b.warning and b.after
    assert not fc._trusted("https://example.com/firmware.kdhx")
    assert not fc._trusted("https://raw.githubusercontent.com/VR2TE/Talkpod-A36plus-Firmware/main/x.bin")


def test_download_is_checked_and_cached(monkeypatch):
    build = fc.VR2TE[0]
    good = b"pretend firmware"
    build = fc.replace(build, sha256=hashlib.sha256(good).hexdigest())
    calls = []
    monkeypatch.setattr(fc, "_get", lambda url, **k: calls.append(url) or good)
    assert fc.fetch(build).data == good
    assert fc.fetch(build).data == good           # second time from the cache
    assert calls == [build.url]


def test_a_download_that_doesnt_match_is_refused(monkeypatch):
    monkeypatch.setattr(fc, "_get", lambda url, **k: b"something else")
    with pytest.raises(fc.CatalogError, match="checksum") as e:
        fc.fetch(fc.VR2TE[1])
    assert isinstance(e.value, radio.RadioError)  # shown to the user, not reported as a crash


def test_offline_download_says_what_to_do(monkeypatch):
    def fail(url, **k):
        raise OSError("no route to host")
    monkeypatch.setattr(fc, "_get", fail)
    with pytest.raises(fc.CatalogError, match="internet"):
        fc.fetch(fc.VR2TE[0])


def release(tag, name, digest, url=None):
    return json.dumps({"tag_name": tag, "assets": [{
        "name": name, "digest": digest,
        "browser_download_url": url or f"https://github.com/{fc.TSF_REPO}/releases/download/{tag}/{name}"}]}).encode()


def test_latest_release_is_offered(monkeypatch):
    monkeypatch.setattr(fc, "_get", lambda url, *a, **k: release("v1.27", "tsf-1.27.kdhx", "sha256:" + "ab" * 32))
    b = fc.latest_tsf()
    assert (b.version, b.filename, b.sha256, b.bundled) == ("1.27", "tsf-1.27.kdhx", "ab" * 32, "")
    assert b.url.endswith("/v1.27/tsf-1.27.kdhx")


def test_an_older_release_than_the_bundled_copy_isnt_offered(monkeypatch):
    monkeypatch.setattr(fc, "_get", lambda url, *a, **k: release("v1.0", "tsf-1.0.kdhx", "sha256:" + "cd" * 32))
    assert fc.latest_tsf() == fc.TSF


def test_latest_release_that_is_the_bundled_one_uses_the_copy(monkeypatch):
    monkeypatch.setattr(fc, "_get", lambda url, *a, **k: release("v1.26", fc.TSF.filename, "sha256:" + fc.TSF.sha256))
    assert fc.latest_tsf().bundled == fc.TSF.bundled


@pytest.mark.parametrize("body", [
    release("v9", "tsf.kdhx", ""),                                              # no digest
    release("v9", "tsf.kdhx", "sha256:" + "00" * 32, url="https://evil.example/tsf.kdhx"),
    b"not json",
])
def test_unusable_releases_fall_back_to_the_bundled_copy(monkeypatch, body):
    monkeypatch.setattr(fc, "_get", lambda url, *a, **k: body)
    assert fc.latest_tsf() == fc.TSF


def test_offline_lookup_falls_back(monkeypatch):
    def fail(url, *a, **k):
        raise OSError("offline")
    monkeypatch.setattr(fc, "_get", fail)
    assert fc.latest_tsf() == fc.TSF
