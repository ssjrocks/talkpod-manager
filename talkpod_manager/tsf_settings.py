"""Talkpod Super Firmware's own settings: the ones its menu changes.

From 1.13 the firmware keeps them in the programming window, so Read and Write carry them like the
channels. Each area is one 4 KB sector from 0x4000, a log of 32-byte records (the firmware's
src/settings.c): u16 magic 0xA36C, u8 length, u8 0, the payload zero-padded to 26 bytes, u16
CRC-16/XMODEM of the first 30 bytes. The newest valid record wins; an older, shorter record only
fills the start, and the rest keeps the firmware's defaults. An area changed here is written as a
fresh log: that one record, the rest erased.

The payloads are the firmware's structs (saved_t in src/ui.c, aprs.h, pocsag.h, roll.h).
"""

import os
import struct

os.environ.setdefault("CHIRP_TESTENV", "1")    # as radio.py: before chirp is first imported

from chirp.settings import (RadioSetting, RadioSettingGroup, RadioSettingValueBoolean,  # noqa: E402
                            RadioSettingValueInteger, RadioSettingValueList, RadioSettingValueString)

BASE, SECTOR, REC, MAGIC, PAYLOAD = 0x4000, 0x1000, 32, 0xA36C, 26
END = BASE + 4 * SECTOR
MAIN, APRS, PAGER, SCRAMBLE = range(4)
FIRST_VERSION = (1, 13)
PREFIX = "tsf_"

STEPS = ["2.5 kHz", "5 kHz", "6.25 kHz", "10 kHz", "12.5 kHz", "25 kHz", "100 kHz", "1 MHz"]
BACKLIGHT = ["Always on", "10 s", "30 s", "60 s"]
TOT = ["Off", "30 s", "60 s", "2 min", "3 min", "5 min"]
MSG_SPEED = ["1200 bit/s", "700 bit/s", "450 bit/s"]
APRS_PATH = ["None", "WIDE1-1", "WIDE2-1", "WIDE1-1, WIDE2-1"]
PAGER_SPEED = ["512 bit/s", "1200 bit/s", "2400 bit/s"]
CALL_CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-"
TEXT_CHARS = "".join(chr(c) for c in range(32, 127))

# saved_t: two slots (u8 is_channel, u8 flags, u16 channel, u32 vfo), then u8 selected, dual, squelch,
# step, backlight, sounds (1 key beep, 2 voice), tot, msg (speed | 4: no receipts). Without a record
# the slots say "keep": channel 0 and VFO 0 aren't valid, so the firmware leaves its slots alone.
MAIN_FMT = "<BBHIBBHI8B"
MAIN_DEFAULT = struct.pack(MAIN_FMT, 1, 0, 0, 0, 1, 0, 0, 0, 0, 1, 1, 4, 2, 3, 4, 0)
APRS_FMT, APRS_DEFAULT = "<10sB15s", struct.pack("<10sB15s", b"", 1, b"A36SE CFW")
PAGER_FMT, PAGER_DEFAULT = "<IBB", struct.pack("<IBB", 1234567, 1, 0)
KEY_FMT, KEY_DEFAULT = "<15s", bytes(15)
DEFAULTS = {MAIN: MAIN_DEFAULT, APRS: APRS_DEFAULT, PAGER: PAGER_DEFAULT, SCRAMBLE: KEY_DEFAULT}


def _crc(b):
    c = 0
    for x in b:
        c ^= x << 8
        for _ in range(8):
            c = (c << 1 ^ 0x1021 if c & 0x8000 else c << 1) & 0xFFFF
    return c


def _image(radio):
    return radio.get_mmap().get_packed()


def record(area, data):
    """The newest valid payload of an area in an image's bytes, or None."""
    found = None
    base = BASE + area * SECTOR
    for i in range(SECTOR // REC):
        r = data[base + i * REC:base + (i + 1) * REC]
        if len(r) < REC or r == b"\xff" * REC:
            break
        magic, n = struct.unpack_from("<HB", r)
        if magic == MAGIC and 0 < n <= PAYLOAD and _crc(r[:30]) == struct.unpack_from("<H", r, 30)[0]:
            found = r[4:4 + n]
    return found


def present(radio):
    """True when the image holds settings of Super Firmware 1.13 or later."""
    data = _image(radio)
    return any(record(a, data) is not None for a in DEFAULTS)


def _payload(data, area):
    p = bytearray(DEFAULTS[area])
    r = record(area, data)
    if r:
        p[:min(len(r), len(p))] = r[:len(p)]
    return bytes(p)


def write(radio, area, payload):
    """Put a fresh log with one record for the area into the image."""
    r = struct.pack("<HBB", MAGIC, len(payload), 0) + payload.ljust(PAYLOAD, b"\0")
    r += struct.pack("<H", _crc(r))
    radio.get_mmap().set(BASE + area * SECTOR, r + b"\xff" * (SECTOR - REC))


def _text(b):
    return b.split(b"\0", 1)[0].decode("ascii", "replace")


def values(radio):
    """{setting name: value} as the radio will use them."""
    data = _image(radio)
    m = list(struct.unpack(MAIN_FMT, _payload(data, MAIN)))
    selected, dual, squelch, step, backlight, sounds, tot, msg = m[8:]
    call, path, text = struct.unpack(APRS_FMT, _payload(data, APRS))
    ric, pspeed, pinvert = struct.unpack(PAGER_FMT, _payload(data, PAGER))
    (key,) = struct.unpack(KEY_FMT, _payload(data, SCRAMBLE))

    def pick(i, options, default):
        return options[i] if i < len(options) else options[default]

    return {
        "squelch": squelch if squelch <= 9 else 1,
        "step": pick(step, STEPS, 4),
        "dual": bool(dual),
        "backlight": pick(backlight, BACKLIGHT, 2),
        "tot": pick(tot, TOT, 4),
        "msg_speed": pick(msg & 3, MSG_SPEED, 0),
        "msg_receipts": not msg & 4,
        "beep": bool(sounds & 1),
        "voice": bool(sounds & 2),
        "aprs_call": _text(call),
        "aprs_path": pick(path, APRS_PATH, 1),
        "aprs_text": _text(text),
        "pager_ric": ric if ric < 1 << 21 else 1234567,
        "pager_speed": pick(pspeed, PAGER_SPEED, 1),
        "pager_invert": bool(pinvert),
        "scramble_key": _text(key),
    }


# name: (title, area, kind, options or limits)
FIELDS = {
    "squelch": ("Squelch", MAIN, "int", (0, 9)),
    "step": ("Tuning step", MAIN, "list", STEPS),
    "dual": ("Dual watch", MAIN, "bool", None),
    "backlight": ("Backlight", MAIN, "list", BACKLIGHT),
    "tot": ("TX timeout", MAIN, "list", TOT),
    "beep": ("Key beep", MAIN, "bool", None),
    "voice": ("Voice", MAIN, "bool", None),
    "msg_speed": ("Message speed", MAIN, "list", MSG_SPEED),
    "msg_receipts": ("Message receipts", MAIN, "bool", None),
    "aprs_call": ("APRS callsign", APRS, "text", (9, CALL_CHARS)),
    "aprs_path": ("APRS path", APRS, "list", APRS_PATH),
    "aprs_text": ("APRS beacon text", APRS, "text", (14, TEXT_CHARS)),
    "pager_ric": ("Pager RIC", PAGER, "int", (0, (1 << 21) - 1)),
    "pager_speed": ("Pager speed", PAGER, "list", PAGER_SPEED),
    "pager_invert": ("Pager invert", PAGER, "bool", None),
    "scramble_key": ("Scramble key", SCRAMBLE, "text", (14, TEXT_CHARS)),
}


def group(radio):
    """The settings as a CHIRP RadioSettingGroup, named tsf_<field>."""
    v = values(radio)
    g = RadioSettingGroup("tsf", "Talkpod Super Firmware")
    for name, (title, _area, kind, extra) in FIELDS.items():
        if kind == "int":
            val = RadioSettingValueInteger(extra[0], extra[1], v[name])
        elif kind == "list":
            val = RadioSettingValueList(extra, current_index=extra.index(v[name]))
        elif kind == "bool":
            val = RadioSettingValueBoolean(v[name])
        else:
            val = RadioSettingValueString(0, extra[0], v[name], autopad=False, charset=extra[1])
        g.append(RadioSetting(PREFIX + name, title, val))
    return g


def owns(setting):
    return setting.get_name().startswith(PREFIX)


def apply(radio, setting):
    """Write one changed setting into the image (its area as a fresh record)."""
    name = setting.get_name()[len(PREFIX):]
    v = values(radio)
    value = setting.value.get_value()
    v[name] = value.rstrip() if isinstance(value, str) else value
    data = _image(radio)
    area = FIELDS[name][1]
    if area == MAIN:
        m = list(struct.unpack(MAIN_FMT, _payload(data, MAIN)))
        m[8 + 1] = int(v["dual"])
        m[8 + 2] = int(v["squelch"])
        m[8 + 3] = STEPS.index(v["step"])
        m[8 + 4] = BACKLIGHT.index(v["backlight"])
        m[8 + 5] = int(v["beep"]) | int(v["voice"]) << 1
        m[8 + 6] = TOT.index(v["tot"])
        m[8 + 7] = MSG_SPEED.index(v["msg_speed"]) | (0 if v["msg_receipts"] else 4)
        payload = struct.pack(MAIN_FMT, *m)
    elif area == APRS:
        payload = struct.pack(APRS_FMT, v["aprs_call"].upper().encode(), APRS_PATH.index(v["aprs_path"]),
                              v["aprs_text"].encode())
    elif area == PAGER:
        payload = struct.pack(PAGER_FMT, int(v["pager_ric"]), PAGER_SPEED.index(v["pager_speed"]),
                              int(v["pager_invert"]))
    else:
        payload = struct.pack(KEY_FMT, v["scramble_key"].encode())
    write(radio, area, payload)
