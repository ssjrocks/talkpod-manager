"""Firmware updates over the programming cable, the way Talkpod's Windows "KDH Bootloader" tool
does them (also implemented by OpenRTX's rtxflash).

Protocol (from the decompiled Talkpod tool):
  Automatic entry, 57600 baud: send "PROGRAM" + "JC37" + "U", radio answers 0x06; send "UPDATE",
  radio answers 0x06; reopen at 115200 and send INTO_BOOT. Manual entry: the user switches the
  radio on while holding the side keys (white screen) and everything happens at 115200.
  Bootloader frames: AA | cmd | arg | length (2, big-endian) | data | CRC-16/XMODEM (2) | EF,
  CRC over cmd..data. The radio answers with a frame of the same cmd and arg 0x06 (OK) or an
  error code. Sequence: HELLO "BOOTLOADER", COUNT (number of 1 KB chunks), DATA chunk i (padded
  to 1024 with zeros), END.
  The .kdhx file is sent as-is: it's the firmware with some 1 KB blocks XOR-scrambled
  (unscramble() undoes that, only to check the file).
"""

import argparse
import logging
import struct
import sys
import time

from . import radio as rio
from .logo import crc16

LOG = logging.getLogger(__name__)

HEAD, TAIL = 0xAA, 0xEF
CMD_HELLO, CMD_DATA, CMD_COUNT, CMD_INTO_BOOT, CMD_END = 0x01, 0x03, 0x04, 0x42, 0x45
OK = 0x06
ERRORS = {
    0xE1: "the bootloader rejected the handshake",
    0xE2: "a data block failed its checksum",
    0xE3: "the bootloader reported an address error",
    0xE4: "the bootloader couldn't write the flash",
    0xE5: "the bootloader didn't understand a command",
}
CHUNK = 1024
MAX_5W_BYTES = 66 * 1024  # A36plus 5 W / A36SE images are ~63-65 KB; MAX (8 W) images are bigger


class FirmwareError(rio.RadioError):
    pass


def frame(cmd, arg, data=b"", length=None):
    length = len(data) if length is None else length
    body = bytes([cmd, arg & 0xFF, length >> 8 & 0xFF, length & 0xFF]) + data
    c = crc16(body)
    return bytes([HEAD]) + body + bytes([c >> 8, c & 0xFF, TAIL])


def parse(buf):
    """(cmd, arg, data) from one complete frame, or raise ValueError."""
    if len(buf) < 8 or buf[0] != HEAD:
        raise ValueError("not a frame")
    length = buf[3] << 8 | buf[4]
    if len(buf) < 8 + length:
        raise ValueError("short frame")
    if crc16(buf[1:5 + length]) != (buf[5 + length] << 8 | buf[6 + length]):
        raise ValueError("bad CRC")
    return buf[1], buf[2], bytes(buf[5:5 + length])


# --- checking a file before it goes anywhere near the radio -----------------------------------

def unscramble(data):
    out = bytearray(data)
    n = (len(data) + CHUNK - 1) // CHUNK
    for i in range(2, n - 2):
        key = b"KDHT" if i % 3 == 1 else b"RBGI" if i % 3 == 2 else None
        if not key:
            continue
        for j in range(i * CHUNK, min((i + 1) * CHUNK, len(data))):
            b, k = out[j], key[(j - i * CHUNK) % 4]
            if b not in (0, 0xFF, k, k ^ 0xFF):
                out[j] = b ^ k
    return bytes(out)


class Image:
    def __init__(self, data, name=""):
        self.data = data
        self.name = name
        self.fw = unscramble(data)
        self.stack, self.reset = struct.unpack_from("<II", self.fw, 0) if len(self.fw) >= 8 else (0, 0)
        import re

        m = re.search(rb" (V\d+\.\d+\w*)\x00", self.fw)
        self.version = m.group(1).decode() if m else None
        self.problems = []
        if not 0x20000000 <= self.stack <= 0x20020000:
            self.problems.append(f"stack pointer {self.stack:#x} isn't in RAM")
        if not (0x08000000 <= self.reset < 0x08100000 and self.reset & 1):
            self.problems.append(f"reset address {self.reset:#x} isn't in flash")
        if b"PROGRAMJC37U" not in self.fw or b"TalkpodA36Plus" not in self.fw:
            self.problems.append("it isn't Talkpod A36plus firmware (the A36plus markers are missing)")
        if len(data) // CHUNK + 1 > 255:
            self.problems.append("it's too big for the bootloader")

    @property
    def chunks(self):
        return (len(self.data) + CHUNK - 1) // CHUNK

    def describe(self):
        return (f"{self.name}: {len(self.data)} bytes, {self.chunks} blocks, version {self.version or '?'}, "
                f"{'looks valid' if not self.problems else 'PROBLEMS: ' + '; '.join(self.problems)}")


def check_for_radio(image, radio_cls):
    """Refuse images that can't be for the connected model."""
    if image.problems:
        raise FirmwareError("Not flashing this file: " + "; ".join(image.problems))
    if radio_cls is rio.mml_jc8810.A36plusRadio and len(image.data) > MAX_5W_BYTES:
        raise FirmwareError("This file is too big for an A36plus 5 W / A36SE (it looks like 8 W / MAX "
                            "firmware). Not flashing it.")


# --- talking to the bootloader -----------------------------------------------------------------

def _read_frame(s, timeout):
    deadline = time.monotonic() + timeout
    buf = b""
    while time.monotonic() < deadline:
        chunk = s.read(1 if not buf else max(1, s.in_waiting))
        if not chunk:
            continue
        buf += chunk
        if buf[0] != HEAD:
            buf = b""
            continue
        if len(buf) >= 5:
            need = 8 + (buf[3] << 8 | buf[4])
            if len(buf) >= need:
                return parse(buf[:need])
    return None


def _exchange(s, packet, cmd, what, tries=5, timeout=2.0):
    for attempt in range(tries):
        s.write(packet)
        try:
            reply = _read_frame(s, timeout)
        except ValueError as e:
            LOG.warning("firmware: bad reply during %s: %s", what, e)
            continue
        if reply is None:
            LOG.warning("firmware: no reply during %s (try %d)", what, attempt + 1)
            continue
        rcmd, arg, _ = reply
        if arg == OK and rcmd == cmd:
            return
        if rcmd == 0xE2:  # checksum error: the tool resends
            continue
        raise FirmwareError(f"Firmware update failed during {what}: "
                            f"{ERRORS.get(rcmd, f'unexpected answer {rcmd:#04x}/{arg:#04x}')}.")
    raise FirmwareError(f"The radio stopped answering during {what}. Switch it on while holding the side "
                        "keys (white screen) and use manual mode to try again; the bootloader is untouched.")


def _enter_bootloader(port):
    """Ask the running radio firmware to restart into its bootloader (Talkpod's AUTO UPDATE)."""
    with rio._open(port, 57600, timeout=2.0) as s:
        s.reset_input_buffer()
        for _ in range(5):
            s.write(b"PROGRAM" + b"JC37" + b"U")
            if s.read(1) == rio.ACK:
                break
        else:
            raise FirmwareError("The radio didn't answer. Check it's switched on and the cable is pushed in.")
        s.write(b"UPDATE")
        if s.read(1) != rio.ACK:
            raise FirmwareError("The radio didn't accept the update request.")
    time.sleep(0.05)


def flash(port, image, progress=None, manual=False):
    """Send a .kdhx image to the radio's bootloader. manual=True: the radio is already showing the
    bootloader's white screen (switched on while holding the side keys)."""
    step = progress or (lambda f, t: None)
    if not manual:
        step(0.0, "Restarting the radio into its bootloader")
        _enter_bootloader(port)
    s = rio._open(port, 115200, timeout=0.2)
    try:
        time.sleep(0.02)
        s.reset_input_buffer()
        if not manual:
            _exchange(s, frame(CMD_INTO_BOOT, 0), CMD_INTO_BOOT, "entering the bootloader")
        step(0.02, "Handshake")
        _exchange(s, frame(CMD_HELLO, 0, b"BOOTLOADER"), CMD_HELLO, "the handshake")
        _exchange(s, frame(CMD_COUNT, 0, bytes([image.chunks])), CMD_COUNT, "sending the size")
        for i in range(image.chunks):
            block = image.data[i * CHUNK:(i + 1) * CHUNK].ljust(CHUNK, b"\x00")
            _exchange(s, frame(CMD_DATA, i, block), CMD_DATA, f"block {i + 1} of {image.chunks}")
            step(0.03 + 0.95 * (i + 1) / image.chunks, f"Writing block {i + 1} of {image.chunks}")
        _exchange(s, frame(CMD_END, 0), CMD_END, "finishing", timeout=5.0)
        step(1.0, "Done")
    finally:
        s.close()
    LOG.info("firmware %s (%s) flashed to %s", image.name, image.version, port)


# --- command line ------------------------------------------------------------------------------

def main(argv=None):
    p = argparse.ArgumentParser(prog="talkpod-firmware",
                                description="Check or flash Talkpod A36plus / A36SE firmware (.kdhx) on Linux.")
    sub = p.add_subparsers(dest="cmd", required=True)
    i = sub.add_parser("info", help="check a firmware file without touching the radio")
    i.add_argument("file")
    f = sub.add_parser("flash", help="flash a firmware file to the radio")
    f.add_argument("file")
    f.add_argument("--port", help="serial port (default: the first programming cable found)")
    f.add_argument("--manual", action="store_true",
                   help="the radio is already in bootloader mode (switched on holding the side keys)")
    f.add_argument("--yes", action="store_true", help="don't ask for confirmation")
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    data = open(args.file, "rb").read()
    image = Image(data, args.file.rsplit("/", 1)[-1])
    print(image.describe())
    if args.cmd == "info":
        return 0 if not image.problems else 1

    ports = rio.find_ports()
    port = args.port or (ports[0].device if ports else None)
    if not port:
        print("No programming cable found.")
        return 1
    if not args.manual:
        cls, ident = rio.identify(port)
        print(f"Radio on {port}: {rio.describe_model(cls)}, identification {ident.hex(' ')}")
        check_for_radio(image, cls)
    else:
        check_for_radio(image, rio.mml_jc8810.A36plusRadio)
    if not args.yes:
        answer = input(f"Flash {image.name} (version {image.version}) to the radio on {port}? "
                       "Type 'flash' to continue: ")
        if answer.strip().lower() != "flash":
            print("Cancelled; nothing was sent.")
            return 1
    last = [-1]

    def progress(fraction, text):
        pct = int(fraction * 100)
        if pct != last[0]:
            last[0] = pct
            print(f"\r{pct:3d}% {text:40s}", end="", flush=True)

    flash(port, image, progress, manual=args.manual)
    print("\nDone. The radio restarts with the new firmware.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
