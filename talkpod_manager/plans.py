"""Ready-made channel layouts."""

from . import radio as _radio  # noqa: F401  (sets CHIRP_TESTENV before chirp is imported)
from chirp import chirp_common

from .channels import bounds, clear

# Australian 80-channel UHF CB (ACMA CB class licence; 12.5 kHz since 2011).
EMERGENCY = (5, 35)
DATA = (22, 23)          # telemetry/telecommand only: no voice
RESERVED = (61, 62, 63)  # guard channels for the 25 kHz data channels: no transmitting
REPEATER_OUTPUTS = tuple(range(1, 9)) + tuple(range(41, 49))
REPEATER_INPUTS = tuple(range(31, 39)) + tuple(range(71, 79))
REPEATER_SHIFT = 750_000

NAMES = {
    5: "CB05 EMERG", 35: "CB35 EMERG", 11: "CB11 CALL",
    22: "CB22 DATA", 23: "CB23 DATA", 10: "CB10 4WD",
    18: "CB18 CARAVN", 29: "CB29 HWY", 40: "CB40 ROAD",
}


def uhf_cb_freq(ch):
    if 1 <= ch <= 40:
        return 476_425_000 + (ch - 1) * 25_000
    if 41 <= ch <= 80:
        return 476_437_500 + (ch - 41) * 25_000
    raise ValueError(f"no UHF CB channel {ch}")


def au_uhf_cb(radio, repeater_base=100, tx_on_repeater_inputs=True, power_index=0):
    """The Australian UHF CB plan as {channel number: Memory}.

    1-80 simplex (61-63 left out, 22/23 receive-only); repeater copies of channels 1-8 and
    41-48 at repeater_base + channel (e.g. 101, 141) with +750 kHz transmit. repeater_base=None
    leaves the repeater copies out. tx_on_repeater_inputs=False makes 31-38 / 71-78 receive-only.
    """
    level = radio.POWER_LEVELS[power_index]
    mems = {}
    for ch in range(1, 81):
        if ch in RESERVED:
            continue
        m = chirp_common.Memory()
        m.number = ch
        m.freq = uhf_cb_freq(ch)
        m.power = level
        m.mode = "NFM"
        m.name = NAMES.get(ch, f"CB{ch:02d}")
        if ch in DATA:
            m.duplex = "off"
            m.mode = "FM"  # 25 kHz channels
            m.skip = "S"
        elif ch in REPEATER_INPUTS and not tx_on_repeater_inputs:
            m.duplex = "off"
        mems[ch] = m
    if repeater_base is not None:
        for ch in REPEATER_OUTPUTS:
            m = chirp_common.Memory()
            m.number = repeater_base + ch
            m.freq = uhf_cb_freq(ch)
            m.duplex = "+"
            m.offset = REPEATER_SHIFT
            m.power = level
            m.mode = "NFM"
            m.name = f"RPT{ch:02d}" + (" EMERG" if ch in EMERGENCY else "")
            m.skip = "S"  # same receive frequency as the simplex channel
            mems[m.number] = m
    return mems


def apply(radio, mems, clear_others=True):
    """Write a plan into an image (not the radio). Returns the channel numbers set."""
    valid = bounds(radio)
    bad = [n for n in mems if n not in valid]
    if bad:
        raise ValueError(f"channels {bad} don't exist on this radio ({valid.start}–{valid.stop - 1})")
    for n in valid:
        if n in mems:
            radio.set_memory(mems[n])
        elif clear_others:
            clear(radio, n)
    return sorted(mems)


PLANS = {
    "au_uhf_cb": "Australian UHF CB (80 channels)",
}
