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
    (1, 14): ("encrypt",),
}

# stock settings (CHIRP names) Super Firmware acts on, from the version that first did; prefixes for
# the lists. The rest are greyed out and stay in the radio for stock firmware.
SUPER_STOCK_SETTINGS = {
    (1, 14): ("sql", "tot", "vox", "voxd", "voice", "abr", "screv", "save", "mdfa", "mdfb", "pttlt", "ani",
              "skey2_sp", "skey2_lp", "skey3_sp", "topkey_sp", "tone", "ponmsg", "ste", "rpste", "rptrl",
              "menuquit", "autolk", "dualtx", "almode", "alarmsound", "roger", "rxendtail", "tdr", "beep",
              "dtmf.dtmfon", "dtmf.dtmfoff", "pttid/", "anicodes/"),
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


def stock_settings_usable(fw):
    """False when the firmware ignores all the stock settings: greyed out, shown only for reference."""
    return not _super(fw) or fw.stock_blocks


def unused_stock_setting(fw, name):
    """True when stock setting name (CHIRP's) does nothing on firmware fw, which uses the others."""
    if not _super(fw) or not fw.stock_blocks:
        return False
    return not any(name == u or (u.endswith("/") and name.startswith(u))
                   for u in _table(SUPER_STOCK_SETTINGS, fw))


def settings_note(fw):
    """What to know about the settings on this firmware, or None when it uses them all."""
    if not _super(fw):
        return None
    if fw.stock_blocks:
        return (f"This radio runs {fw.name}. It uses the stock settings below; the few greyed out don't do "
                "anything on it yet. They stay in the radio for stock firmware.")
    if own_settings(fw):
        return (f"This radio runs {fw.name}. Its own settings are in the first group below, and Write "
                "sends them to the radio. It doesn't use the stock settings after them; they stay in the "
                "radio unchanged, for when it runs stock firmware again. Update it to 1.14 or later to "
                "use them.")
    return (f"This radio runs {fw.name}. It keeps its own settings, changed from the radio's menu, so it "
            "doesn't use the stock settings below. They stay in the radio unchanged, for when it runs stock "
            "firmware again. Update it to Super Firmware 1.13 or later to edit its settings here.")
