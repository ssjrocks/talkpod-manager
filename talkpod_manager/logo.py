"""Boot logo upload, as done by Talkpod's "Import Picture tools" for the A36plus.

Protocol (worked out from Talkpod's Windows tool):
  1. 57600 baud: send "PROGRAMJC37U", radio answers 0x06, send "D" (picture mode).
  2. Reopen at 115200 baud. Frames are
       A5 | cmd | packet id (2, big-endian) | length (2, BE) | data | CRC-16/XMODEM (2, BE)
     with the CRC over cmd..data. The radio answers each frame with a frame of the same
     command whose data is b"Y".
  3. HANDSHAKE "PROGRAM", ERASE (id 0x4504, data: address LE32 + block count BE16),
     SET ADDRESS (address LE32), then WRITE 1024-byte packets (id 0, 1, ...), then OVER "Over".
  The picture is 128 x 128 RGB565, little-endian, rows top to bottom, at flash address 0x10000.
"""

import logging
import time

from . import radio as _radio

LOG = logging.getLogger(__name__)

WIDTH = HEIGHT = 128
IMAGE_BYTES = WIDTH * HEIGHT * 2
ADDRESS = 0x10000
PACKET = 1024

FRAME = 0xA5
CMD_WRITE = 0x57
CMD_HANDSHAKE = 0x02
CMD_SETADDRESS = 0x03
CMD_ERASE = 0x04
CMD_OVER = 0x06
ERASE_ID = 0x4504


def crc16(data: bytes) -> int:
    crc = 0
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if crc & 0x8000 else (crc << 1)
            crc &= 0xFFFF
    return crc


def frame(cmd: int, packet_id: int, data: bytes) -> bytes:
    body = bytes([cmd, packet_id >> 8 & 0xFF, packet_id & 0xFF, len(data) >> 8 & 0xFF, len(data) & 0xFF]) + data
    c = crc16(body)
    return bytes([FRAME]) + body + bytes([c >> 8, c & 0xFF])


def parse_frame(buf: bytes):
    """(cmd, packet id, data) from a complete frame, or raise ValueError."""
    if len(buf) < 8 or buf[0] != FRAME:
        raise ValueError("not a frame")
    length = buf[4] << 8 | buf[5]
    if len(buf) < 8 + length:
        raise ValueError("short frame")
    body = buf[1:6 + length]
    got = buf[6 + length] << 8 | buf[7 + length]
    if crc16(body) != got:
        raise ValueError("bad CRC")
    return buf[1], buf[2] << 8 | buf[3], bytes(buf[6:6 + length])


def rgb565(rgb: bytes, width=WIDTH, height=HEIGHT, stride=None, channels=3) -> bytes:
    """Pack 8-bit RGB(A) pixels (rows top to bottom) into the radio's RGB565 little-endian format."""
    stride = stride or width * channels
    out = bytearray(width * height * 2)
    o = 0
    for y in range(height):
        row = y * stride
        for x in range(width):
            i = row + x * channels
            v = (rgb[i] >> 3) << 11 | (rgb[i + 1] >> 2) << 5 | (rgb[i + 2] >> 3)
            out[o] = v & 0xFF
            out[o + 1] = v >> 8
            o += 2
    return bytes(out)


class LogoError(_radio.RadioError):
    pass


def _read_frame(s, timeout):
    deadline = time.monotonic() + timeout
    buf = b""
    while time.monotonic() < deadline:
        chunk = s.read(1 if not buf else max(1, s.in_waiting))
        if not chunk:
            continue
        buf += chunk
        if buf[0] != FRAME:
            buf = b""
            continue
        if len(buf) >= 6:
            need = 8 + (buf[4] << 8 | buf[5])
            if len(buf) >= need:
                return parse_frame(buf[:need])
    return None


def _exchange(s, cmd, packet_id, data, timeout=2.0, tries=5):
    packet = frame(cmd, packet_id, data)
    for attempt in range(tries):
        s.write(packet)
        try:
            reply = _read_frame(s, timeout)
        except ValueError as e:
            LOG.warning("logo: bad reply to cmd %02x: %s", cmd, e)
            reply = None
        if reply is None:
            LOG.warning("logo: no reply to cmd %02x packet %d (try %d)", cmd, packet_id, attempt + 1)
            continue
        rcmd, _, rdata = reply
        if rcmd == cmd and rdata == b"Y":
            return
        raise LogoError(f"The radio refused the picture (step {cmd:#04x}, answer {rdata!r}).")
    raise LogoError("The radio stopped answering while receiving the picture. Switch it off and on and try again.")


def send(port, pixels: bytes, progress=None):
    """Send a 128x128 RGB565 picture to the radio's boot logo."""
    if len(pixels) != IMAGE_BYTES:
        raise ValueError(f"picture must be {IMAGE_BYTES} bytes, got {len(pixels)}")
    _radio.identify(port)  # fails early (and clearly) if the radio isn't there or isn't an A36plus

    s = _radio._open(port, 57600, timeout=1.0)
    try:
        s.reset_input_buffer()
        for _ in range(5):
            s.write(_radio.MAGIC)
            if s.read(1) == _radio.ACK:
                break
        else:
            raise LogoError("The radio didn't enter picture mode.")
        s.write(b"D")
        s.flush()
    finally:
        s.close()

    time.sleep(0.1)
    s = _radio._open(port, 115200, timeout=0.1)
    try:
        time.sleep(0.1)
        s.reset_input_buffer()
        step = lambda f, msg: progress and progress(f, msg)  # noqa: E731
        step(0.02, "Handshake")
        _exchange(s, CMD_HANDSHAKE, 0, b"PROGRAM")
        step(0.05, "Erasing old picture")
        addr = ADDRESS.to_bytes(4, "little")
        _exchange(s, CMD_ERASE, ERASE_ID, addr + (1).to_bytes(2, "big"), timeout=5.0)
        _exchange(s, CMD_SETADDRESS, 0, addr)
        packets = IMAGE_BYTES // PACKET
        for i in range(packets):
            _exchange(s, CMD_WRITE, i, pixels[i * PACKET:(i + 1) * PACKET])
            step(0.08 + 0.9 * (i + 1) / packets, "Sending picture")
        s.write(frame(CMD_OVER, 0, b"Over"))
        s.flush()
        time.sleep(0.2)
        step(1.0, "Done")
    finally:
        s.close()
    LOG.info("boot logo sent to %s", port)
