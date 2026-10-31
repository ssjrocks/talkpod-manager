"""Talkpod Super Firmware's own settings in the programming window (1.13+): reading them from an image,
editing them, and Write sending them only when the image has them."""

import struct

import pytest

from talkpod_manager import features, radio, tsf_settings as ts

from test_super_firmware import IMAGE, FakeRadio, attach, memory_of


@pytest.fixture
def image():
    return radio.load_image(IMAGE)


def setting(group, name):
    return next(s for s in group if s.get_name() == ts.PREFIX + name)


def change(img, name, value):
    s = setting(ts.group(img), name)
    s.value.set_value(value)
    ts.apply(img, s)


def test_an_image_without_them_shows_the_firmwares_defaults(image):
    assert not ts.present(image)
    v = ts.values(image)
    assert (v["squelch"], v["step"], v["dual"], v["backlight"], v["tot"]) == (1, "12.5 kHz", True, "30 s", "3 min")
    assert (v["msg_speed"], v["msg_receipts"], v["beep"], v["voice"]) == ("1200 bit/s", True, True, True)
    assert (v["aprs_call"], v["aprs_path"], v["aprs_text"]) == ("", "WIDE1-1", "A36SE CFW")
    assert (v["pager_ric"], v["pager_speed"], v["scramble_key"]) == (1234567, "1200 bit/s", "")
    assert len(ts.group(image)) == len(ts.FIELDS) == 16


def test_a_change_writes_its_area_as_one_fresh_record(image):
    change(image, "squelch", 5)
    data = image.get_mmap().get_packed()
    sector = data[ts.BASE:ts.BASE + ts.SECTOR]
    assert struct.unpack_from("<HB", sector) == (0xA36C, 24)
    assert sector[32:] == b"\xff" * (ts.SECTOR - 32)
    assert data[ts.BASE + ts.SECTOR:ts.END] == b"\xff" * (3 * ts.SECTOR)   # other areas untouched
    assert ts.present(image) and ts.values(image)["squelch"] == 5
    # slots say "keep" (channel 0, VFO 0): the firmware leaves its own slots alone
    assert struct.unpack_from(ts.MAIN_FMT, ts.record(ts.MAIN, data))[:8] == (1, 0, 0, 0, 1, 0, 0, 0)


def test_the_newest_record_wins_and_slots_are_kept(image):
    old = struct.pack(ts.MAIN_FMT, 1, 4, 11, 47667500, 0, 2, 40, 47740000, 1, 0, 3, 2, 0, 1, 5, 6)
    newer = struct.pack(ts.MAIN_FMT, 1, 4, 11, 47667500, 0, 2, 40, 47740000, 1, 0, 7, 2, 0, 1, 5, 6)
    ts.write(image, ts.MAIN, old)
    mm = image.get_mmap()
    second = bytearray(mm.get(ts.BASE, 32))
    second[4:4 + 24] = newer
    second[30:32] = struct.pack("<H", ts._crc(bytes(second[:30])))
    mm.set(ts.BASE + 32, bytes(second))
    v = ts.values(image)
    assert (v["squelch"], v["dual"], v["backlight"], v["tot"], v["beep"], v["voice"]) == (7, False, "Always on",
                                                                                          "5 min", True, False)
    assert (v["msg_speed"], v["msg_receipts"]) == ("450 bit/s", False)
    change(image, "tot", "Off")
    m = struct.unpack(ts.MAIN_FMT, ts.record(ts.MAIN, image.get_mmap().get_packed()))
    assert m[:8] == (1, 4, 11, 47667500, 0, 2, 40, 47740000) and m[8 + 2] == 7 and m[8 + 6] == 0


def test_text_settings(image):
    change(image, "aprs_call", "VK2ABC-7")
    change(image, "aprs_text", "hello there")
    change(image, "scramble_key", "our key")
    change(image, "pager_ric", 99)
    v = ts.values(image)
    assert (v["aprs_call"], v["aprs_text"], v["scramble_key"], v["pager_ric"]) == ("VK2ABC-7", "hello there",
                                                                                  "our key", 99)
    assert v["aprs_path"] == "WIDE1-1"                  # the rest of the area keeps its value
    with pytest.raises(Exception):
        setting(ts.group(image), "aprs_call").value.set_value("too-long-call")


def test_write_sends_them_only_when_the_image_has_them(monkeypatch, image):
    in_range = lambda writes: [a for a in writes if ts.BASE <= a < ts.END]   # noqa: E731
    fake = FakeRadio(radio.SUPER_IDENT, memory_of(image), version="1.13")
    fake.memory[ts.BASE:ts.BASE + 4] = b"\x6c\xa3\x18\x00"      # the radio's own settings, not in the image
    attach(monkeypatch, fake)
    radio.upload("/dev/fake", radio.copy_radio(image))
    assert not in_range(fake.writes) and fake.memory[ts.BASE:ts.BASE + 4] == b"\x6c\xa3\x18\x00"

    edited = radio.copy_radio(image)
    change(edited, "scramble_key", "abc")
    fake.writes.clear()
    radio.upload("/dev/fake", edited)
    assert in_range(fake.writes)
    assert ts.values(radio.download("/dev/fake"))["scramble_key"] == "abc"


def test_stock_radios_never_get_them(monkeypatch, image):
    from test_super_firmware import STOCK_IDENT
    edited = radio.copy_radio(image)
    change(edited, "squelch", 3)
    fake = FakeRadio(STOCK_IDENT, memory_of(image))
    attach(monkeypatch, fake)
    radio.upload("/dev/fake", edited)
    assert not [a for a in fake.writes if ts.BASE <= a < ts.END]


@pytest.mark.parametrize("version, own", [("1.12", False), ("1.13", True), ("1.20", True)])
def test_which_firmware_has_them(version, own):
    fw = radio.Firmware(radio.SUPER_IDENT, version)
    assert features.own_settings(fw) is own
    assert ("1.13 or later" in features.settings_note(fw)) is not own
    assert not features.own_settings(radio.Firmware(b"\x00" * 8))
