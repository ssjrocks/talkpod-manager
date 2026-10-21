import shutil
from pathlib import Path

import pytest

from talkpod_manager import backups, channels, logo, plans, radio

DATA = Path(__file__).parent / "data"
IMAGE = DATA / "a36se-fw126-uhf-cb.img"


@pytest.fixture
def img():
    return radio.load_image(IMAGE)


def test_load_image(img):
    assert img.MODEL == "A36plus"
    assert channels.used_count(img) == 93
    assert list(channels.bounds(img))[-1] == 512


def test_au_uhf_cb_plan_matches_programmed_radio(img):
    fresh = radio.copy_radio(img)
    plans.apply(fresh, plans.au_uhf_cb(fresh, repeater_base=100))
    for n in channels.bounds(img):
        a, b = img.get_memory(n), fresh.get_memory(n)
        assert a.empty == b.empty, n
        if not a.empty:
            assert (a.freq, a.duplex, a.offset, a.mode, a.skip, a.name.strip()) == \
                   (b.freq, b.duplex, b.offset, b.mode, b.skip, b.name.strip()), n


def test_plan_frequencies_and_rules(img):
    mems = plans.au_uhf_cb(img, repeater_base=400, tx_on_repeater_inputs=False)
    assert mems[1].freq == 476_425_000
    assert mems[40].freq == 477_400_000
    assert mems[41].freq == 476_437_500
    assert mems[80].freq == 477_412_500
    assert 61 not in mems and 62 not in mems and 63 not in mems
    assert mems[22].duplex == "off" and mems[23].duplex == "off"
    assert mems[31].duplex == "off" and mems[78].duplex == "off"
    assert channels.tx_freq(mems[401]) == 477_175_000  # repeater on ch 1 transmits on ch 31
    assert channels.tx_freq(mems[441]) == 477_187_500  # repeater on ch 41 transmits on ch 71
    for m in mems.values():
        assert channels.errors_for(img, m) == [], m.number


def test_plan_rejects_channels_past_512(img):
    with pytest.raises(ValueError):
        plans.apply(img, plans.au_uhf_cb(img, repeater_base=500))


def test_csv_round_trip(img, tmp_path):
    path = tmp_path / "ch.csv"
    assert channels.export_csv(img, path) == 93
    other = radio.copy_radio(img)
    for n in channels.bounds(other):
        channels.clear(other, n)
    count, problems = channels.import_csv(other, path)
    assert problems == []
    assert count == 93
    for n in channels.bounds(img):
        a, b = img.get_memory(n), other.get_memory(n)
        assert a.empty == b.empty
        if not a.empty:
            assert (a.freq, a.duplex, a.offset, a.mode, a.name.strip(), str(a.power)) == \
                   (b.freq, b.duplex, b.offset, b.mode, b.name.strip(), str(b.power))


def test_backups_save_and_list(img, tmp_path):
    p = backups.save(img, "before write", folder=tmp_path)
    items = backups.list_all(folder=tmp_path)
    assert [b.path for b in items] == [p]
    assert items[0].label == "before write"
    assert items[0].channels() == 93


def test_compare_detects_changes(img):
    other = radio.copy_radio(img)
    assert radio.compare(img, other) == []
    channels.clear(other, 5)
    assert radio.compare(img, other)


def test_crc_and_frame():
    # CRC-16/XMODEM check value
    assert logo.crc16(b"123456789") == 0x31C3
    f = logo.frame(logo.CMD_HANDSHAKE, 0, b"PROGRAM")
    assert f[:6] == bytes([0xA5, 0x02, 0, 0, 0, 7])
    assert logo.parse_frame(f) == (0x02, 0, b"PROGRAM")
    bad = bytearray(f)
    bad[-1] ^= 1
    with pytest.raises(ValueError):
        logo.parse_frame(bytes(bad))


def test_rgb565_packing():
    px = bytes([255, 0, 0, 0, 255, 0, 0, 0, 255, 255, 255, 255])
    out = logo.rgb565(px, width=4, height=1)
    assert out == bytes([0x00, 0xF8, 0xE0, 0x07, 0x1F, 0x00, 0xFF, 0xFF])


def test_fixture_is_not_modified():
    # keep the fixture byte-identical so the plan test stays meaningful
    copy = DATA / "a36se-fw126-uhf-cb.img"
    assert shutil.disk_usage(copy.parent)  # exists
    assert copy.stat().st_size == 46305


def test_apply_setting_changes_only_that_setting(img):
    other = radio.copy_radio(img)
    s = other.get_settings()
    ponmsg = next(e for g in s for e in g if getattr(e, "get_name", lambda: "")() == "ponmsg")
    new = next(o for o in ponmsg.value.get_options() if str(o) != str(ponmsg.value))
    ponmsg.value.set_value(new)
    radio.apply_setting(other, ponmsg)
    a, b = img.get_mmap().get_packed(), other.get_mmap().get_packed()
    assert [i for i in range(len(a)) if a[i] != b[i]] == [0x901C]


def test_8w_only_settings_hidden_on_5w_image(img):
    assert radio.missing_settings(img) == {"single_mode", "dis_s_table"}
