"""Channel (memory) helpers: display text, validation, CSV import/export."""

import logging

from . import radio as _radio  # noqa: F401  (sets CHIRP_TESTENV before chirp is imported)
from chirp import chirp_common, import_logic
from chirp.drivers import generic_csv

LOG = logging.getLogger(__name__)

DUPLEX_LABELS = {
    "": "Simplex",
    "+": "Repeater +",
    "-": "Repeater −",
    "split": "Split (own TX freq)",
    "off": "Receive only",
}


def bounds(radio):
    lo, hi = radio.get_features().memory_bounds
    return range(lo, hi + 1)


def all_memories(radio):
    return [radio.get_memory(n) for n in bounds(radio)]


def used_count(radio):
    return sum(1 for m in all_memories(radio) if not m.empty)


def mhz(hz):
    return f"{hz / 1e6:.4f}"


def tx_freq(mem):
    """Transmit frequency in Hz, or None for receive-only."""
    if mem.duplex == "off":
        return None
    if mem.duplex == "+":
        return mem.freq + mem.offset
    if mem.duplex == "-":
        return mem.freq - mem.offset
    if mem.duplex == "split":
        return mem.offset
    return mem.freq


def tx_text(mem):
    if mem.duplex == "off":
        return "RX only"
    if mem.duplex in ("+", "-"):
        return f"{mhz(tx_freq(mem))} ({mem.duplex}{mem.offset / 1e6:g})"
    if mem.duplex == "split":
        return mhz(mem.offset)
    return "Simplex"


def tone_text(mem):
    if mem.tmode == "Tone":
        return f"Tone {mem.rtone:.1f}"
    if mem.tmode == "TSQL":
        return f"TSQL {mem.ctone:.1f}"
    if mem.tmode == "DTCS":
        return f"DCS {mem.dtcs:03d}{mem.dtcs_polarity[0]}"
    if mem.tmode == "Cross":
        return f"Cross {mem.cross_mode}"
    return ""


def power_text(mem):
    """e.g. "5 W" (CHIRP keeps power levels in dBm)."""
    if mem.power is None:
        return ""
    watts = 10 ** ((float(mem.power) - 30) / 10)
    return f"{watts:.0f} W" if watts >= 1 else f"{watts:.1f} W"


def errors_for(radio, mem):
    """Validation errors (not warnings) CHIRP reports for this memory on this radio."""
    msgs = radio.validate_memory(mem)
    return [str(m) for m in msgs if isinstance(m, chirp_common.ValidationError)]


def clear(radio, number):
    m = chirp_common.Memory()
    m.number = number
    m.empty = True
    radio.set_memory(m)


# --- CSV (CHIRP's generic CSV format, so files round-trip with CHIRP and RepeaterBook) ---------


def export_csv(radio, path):
    out = generic_csv.CSVRadio(None)
    out.clear()
    count = 0
    for m in all_memories(radio):
        if m.empty:
            continue
        out.set_memory(m)
        count += 1
    out.save(str(path))
    return count


def import_csv(radio, path, replace=True):
    """Load channels from a CHIRP-format CSV into the image.

    The CSV's Location column picks the channel number. With replace=True every channel not in
    the file is cleared. Returns (imported count, [problem strings]).
    """
    src = generic_csv.CSVRadio(str(path))
    src_rf = src.get_features()
    lo, hi = radio.get_features().memory_bounds
    imported, problems, numbers = 0, [], set()
    for m in src.get_memories():
        if m.empty:
            continue
        if not lo <= m.number <= hi:
            problems.append(f"Location {m.number}: outside channels {lo}–{hi}, skipped")
            continue
        try:
            dst = import_logic.import_mem(radio, src_rf, m, overrides={"number": m.number})
        except import_logic.DestNotCompatible as e:
            problems.append(f"Location {m.number} ({m.name.strip() or mhz(m.freq)}): {e}")
            continue
        radio.set_memory(dst)
        numbers.add(m.number)
        imported += 1
    if replace and imported:
        for n in range(lo, hi + 1):
            if n not in numbers:
                clear(radio, n)
    return imported, problems
