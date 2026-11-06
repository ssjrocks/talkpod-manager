"""The receiver event log of Talkpod Super Firmware 1.22 and later, read over the cable and explained.

The radio keeps its last 128 receiver events in RAM. Plugging in the cable doesn't restart it, so after
a problem the log of what led to it is still there; switching off clears it. The shell command `L`
answers `EVLOG NOW COUNT`, one `MS NAME A V` line per event (oldest first, all hex), then `END`.
The firmware repository's docs/serial-interface.md has the format.
"""

import logging
import time
from dataclasses import dataclass

from . import radio as rio
from .splash import Shell
from .updater import parse_version

LOG = logging.getLogger(__name__)

FIRST_VERSION = (1, 22)
MODULATION = {0: "FM", 1: "AM", 2: "SSB"}
HOLDS = [(1, "a sound playing"), (2, "data arriving"), (4, "a squelch tail")]
IRQ_FLAGS = [(0x0002, "FSK sync word"), (0x0400, "squelch-tail tone"), (0x2000, "packet complete")]
PACKET_TYPES = {100: "message", 101: "encrypted message", 102: "delivery receipt"}

# what each event means, shown on hover
DESCRIPTIONS = {
    "BOOT": "The radio was switched on. The log starts empty at every power-on.",
    "TUNE": "The receiver moved to this frequency: a channel change, a typed frequency, a scan step. Dual "
            "watch's two frequencies are logged once, not at every switch, and a scan at most every 0.3 s.",
    "OPEN": "The squelch opened: a signal is there (with the channel's tone, if it has one), and its audio "
            "goes to the speaker unless a mute below holds it. The strength is the signal when it opened.",
    "CLOSE": "The squelch closed: the signal went, or its tone did.",
    "CARRIER": "A carrier came or went while the squelch stayed as it was. On a channel with CTCSS, DCS or "
               "ENCRY this is a signal without the channel's tone: its audio isn't played.",
    "HOLD": "What mutes the received audio now, even with the squelch open: a sound playing (a beep or "
            "prompt), data arriving (a message or rolling-scramble burst, at most 3 s), or a squelch tail "
            "(Tail cut: until the carrier goes, at most 0.5 s since firmware 1.22). \"Nothing\": the audio "
            "plays again.",
    "IRQ": "The receiver chip flagged something. FSK sync word: the start of a data packet, or tones that "
           "look like one. Squelch-tail tone: the end of another radio's transmission, or tones that look like "
           "it; with Tail cut on, the audio is muted for it. Packet complete: a data packet ended.",
    "PKT": "A data packet arrived. Messages, encrypted messages and delivery receipts are UV-K5 messenger "
           "packets; any other type is noise that happened to match the sync word.",
    "PKT_LOST": "A sync word came, then no complete packet within 3 s: usually tones or noise that looked "
                "like the start of a packet. The audio was muted meanwhile.",
    "TX": "The radio started or stopped transmitting on this frequency.",
    "SQUELCH": "The squelch level changed. 0 is always open.",
}


class EventLogError(rio.RadioError):
    """Something the user can act on: no answer, firmware too old."""


@dataclass
class Event:
    ms: int                 # since the radio's power-on
    name: str
    a: int
    v: int

    @property
    def mhz(self):
        return f"{self.v / 100000:.5f} MHz"

    def summary(self):
        """One line: what happened."""
        n, a, v = self.name, self.a, self.v
        if n == "BOOT":
            return "Switched on"
        if n == "TUNE":
            mod = MODULATION.get(a & 15, "?")
            width = " narrow" if a >> 4 and mod == "FM" else " wide" if mod == "FM" else ""
            return f"Tuned to {self.mhz}, {mod}{width}"
        if n in ("OPEN", "CLOSE"):
            return f"Squelch {'opened' if n == 'OPEN' else 'closed'} on {self.mhz}, {a - 160} dBm"
        if n == "CARRIER":
            return f"Carrier {'without the right tone' if a else 'gone'} on {self.mhz}"
        if n == "HOLD":
            held = [text for bit, text in HOLDS if a & bit]
            return "Received audio muted for " + " and ".join(held) if held else "Received audio no longer muted"
        if n == "IRQ":
            flags = [text for bit, text in IRQ_FLAGS if v & bit]
            other = v & ~sum(bit for bit, _ in IRQ_FLAGS)
            if other:
                flags.append(f"flags {other:#06x}")
            return "Receiver chip: " + ", ".join(flags)
        if n == "PKT":
            return f"Data packet: {PACKET_TYPES.get(a, f'type {a}, noise')} on {self.mhz}"
        if n == "PKT_LOST":
            return f"Data packet started and never finished on {self.mhz}"
        if n == "TX":
            return f"{'Transmitting' if a else 'Stopped transmitting'} on {self.mhz}"
        if n == "SQUELCH":
            return f"Squelch level {a}"
        return f"{n} {a:#x} {v:#x}"

    def description(self):
        return DESCRIPTIONS.get(self.name, "An event this version of Talkpod Manager doesn't know.")


def parse(lines):
    """(radio's milliseconds at reading, [Event] oldest first) from the reply to `L`."""
    now, events, started = None, [], False
    for line in lines:
        parts = line.split()
        if not parts:
            continue
        if parts[0] == "EVLOG" and len(parts) >= 2:
            now, started = int(parts[1], 16), True
        elif parts[0] == "END":
            break
        elif started and len(parts) == 4:
            try:
                events.append(Event(int(parts[0], 16), parts[1], int(parts[2], 16), int(parts[3], 16)))
            except ValueError:
                LOG.info("event log: skipped %r", line)     # a log line of the radio's in between
    if now is None:
        raise EventLogError("The radio didn't send its event log.")
    return now, events


def _version(sh):
    line = sh.command("i", lambda l: l.startswith("fw="))
    if not line:
        raise EventLogError("The radio didn't answer. The event log needs Talkpod Super Firmware 1.22 or later "
                            "on the radio, switched on, with the programming cable plugged in.")
    info = dict(kv.split("=", 1) for kv in line.split() if "=" in kv)
    ver = info.get("ver", "0")
    if parse_version(ver) < FIRST_VERSION:
        raise EventLogError(f"The radio runs Talkpod Super Firmware {ver}. The event log needs 1.22 or later: "
                            "flash it from Flash firmware….")
    return ver


def read(port, opener=None):
    """(radio's milliseconds at reading, PC time at reading, [Event]); the radio keeps its log."""
    with Shell(port, opener) as sh:
        _version(sh)
        sh.s.reset_input_buffer()
        sh.s.write(b"L\r")
        t0, buf, lines = time.monotonic(), b"", []
        while time.monotonic() - t0 < 5:
            buf += sh.s.read(max(1, sh.s.in_waiting))
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                lines.append(line.decode("latin-1").strip())
            if lines and lines[-1] == "END":
                break
        read_at = time.time()
    now, events = parse(lines)
    LOG.info("event log: %d events read from %s", len(events), port)
    return now, read_at, events


def clear(port, opener=None):
    with Shell(port, opener) as sh:
        _version(sh)
        if sh.command("l", lambda l: l == "ok") != "ok":
            raise EventLogError("The radio didn't clear its event log.")
