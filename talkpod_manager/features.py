"""What each firmware does with the radio's channel and settings data, so the editor can grey out what
the radio would ignore. The data itself always stays in the image, for when other firmware runs:
stock firmware, VR2TE's builds of it and Talkpod Super Firmware 1.1+ all keep channels and settings
in the same layout."""

from . import tsf_settings
from .updater import parse_version

# channel extras (CHIRP names) that Talkpod Super Firmware doesn't act on yet, from the version that
# first had channel programming
SUPER_UNUSED_EXTRAS = {
    (1, 10): ("encrypt", "pttid", "scode"),
}


def _super(fw):
    return fw is not None and fw.kind == "super"


def _table(table, fw):
    """the entry for the newest version in table that isn't newer than fw's"""
    v = parse_version(fw.version or "0")
    best = None
    for key in sorted(table):
        if key <= v:
            best = table[key]
    return best if best is not None else table[min(table)]


def unused_channel_extras(fw):
    """{extra name: why it's greyed out} for the firmware fw (a radio.Firmware, or None: unknown)"""
    if not _super(fw):
        return {}
    why = f"Not used by {fw.name} yet; kept for stock firmware"
    return {name: why for name in _table(SUPER_UNUSED_EXTRAS, fw)}


def own_settings(fw):
    """True when the firmware keeps its own settings where Read and Write reach them (1.13+)."""
    return _super(fw) and parse_version(fw.version or "0") >= tsf_settings.FIRST_VERSION


def settings_note(fw):
    """Why the stock settings don't apply, or None when the radio uses them."""
    if not _super(fw):
        return None
    if own_settings(fw):
        return (f"This radio runs {fw.name}. Its own settings are in the first group below, and Write "
                "sends them to the radio. It doesn't use the stock settings after them; they stay in the "
                "radio unchanged, for when it runs stock firmware again.")
    return (f"This radio runs {fw.name}. It keeps its own settings, changed from the radio's menu, so it "
            "doesn't use the stock settings below. They stay in the radio unchanged, for when it runs stock "
            "firmware again. Update it to Super Firmware 1.13 or later to edit its settings here.")
