"""Every setting the radio exposes has hover help, and the help renders."""

from pathlib import Path

import pytest
import gi

gi.require_version("Pango", "1.0")
from gi.repository import Pango  # noqa: E402

from talkpod_manager import descriptions, radio
from chirp import settings as cs

IMAGE = Path(__file__).parent / "data" / "a36se-fw126-uhf-cb.img"


def all_settings(group):
    for el in group:
        if isinstance(el, cs.RadioSetting):
            yield el
        else:
            yield from all_settings(el)


@pytest.fixture(scope="module")
def img():
    return radio.load_image(IMAGE)


def test_every_setting_has_help(img):
    missing = [s.get_name() for g in img.get_settings() for s in all_settings(g)
               if descriptions.lookup(s.get_name()) is None]
    assert missing == []


def test_every_channel_extra_has_help(img):
    names = [s.get_name() for s in img.get_memory(1).extra]
    assert names and all(descriptions.lookup(n, descriptions.EXTRAS) for n in names)


@pytest.mark.parametrize("table", [descriptions.SETTINGS, descriptions.EXTRAS, descriptions.FIELDS])
def test_markup_parses(table):
    for name, h in table.items():
        Pango.parse_markup(descriptions.markup(f"Title & <{name}>", h), -1, "\0")
        assert h.what.strip() and h.use.strip(), name
