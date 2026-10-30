"""Boot splash for radios running Talkpod Super Firmware 1.0 or later: an animation (or a still
picture) the radio plays once when it is switched on. Pictures are fitted to the 128 x 128 screen,
coded in the firmware's A36G format and written over the firmware's serial shell. Stock firmware
has no splash; it shows a still boot logo instead (logo.py).

A36G, little-endian, at external flash 0x120000 (at most 768 KB):
  "A36G", u16 frames, u16 background RGB565, u32 total bytes
  per frame: u16 delay ms, u8 x, y, w, h (w = 0: nothing changes), u16 colours, colours x u16
             RGB565, u32 data bytes, then PackBits over the palette indices of the w x h rectangle,
             row by row (n < 128: n + 1 literal indices follow; n >= 128: the next index n - 125 times)

The firmware's shell (57600 8N1, commands end in CR, replies in CRLF; the radio may print log
lines in between, so replies are picked out by their content):
  i            "fw=TSF ver=1.00 board=HWVER02 splash=00120000+000C0000 splash_fmt=A36G"
  E ADDR       erase the 4 KB sector at ADDR (hex): ok / refused
  W ADDR LEN   then LEN bytes (1-256) and their CRC-16/XMODEM, big-endian: ok / crc / refused / timeout
  X ADDR LEN   LEN raw bytes, then their CRC-16/XMODEM, big-endian
  G            play the splash now: ok / no splash
"""

import logging
import time
from dataclasses import dataclass, field

from . import radio as rio
from .logo import crc16

LOG = logging.getLogger(__name__)

SIZE = 128
BASE = 0x120000
CAPACITY = 0xC0000                      # 768 KB
MAX_MS = 15000                          # longer animations are cut here
MIN_DELAY = 20                          # ms per frame at the least
SECTOR = 0x1000
BYTES_PER_SECOND = 1700                 # sending incl. the check: 157 KB took 91 s on an A36SE
STILL_SECONDS = (1, 2, 3, 5, 8)

# (key, label, explanation)
FIT_MODES = [
    ("fit", "Shrink or enlarge to fit", "Fills the width or the height, keeping the picture's shape"),
    ("shrink", "Shrink to fit", "Bigger pictures are made smaller, keeping their shape; smaller ones stay as they are"),
    ("stretch", "Stretch to fill", "Fills the whole screen; the shape changes unless the picture is square"),
    ("fill", "Crop to fill", "Fills the whole screen, keeping the shape; the edges are cut off"),
]


class SplashError(rio.RadioError):
    pass


# ---- pictures -----------------------------------------------------------------------------------

@dataclass
class Source:
    """A picture or animation as loaded: RGBA frames with their delays (ms)."""
    path: str
    width: int
    height: int
    frames: list = field(default_factory=list)      # [(PIL RGBA image, delay ms)]
    truncated: bool = False                         # cut at MAX_MS

    @property
    def animated(self):
        return len(self.frames) > 1

    @property
    def duration_ms(self):
        return sum(d for _, d in self.frames)

    @property
    def needs_resize(self):
        return (self.width, self.height) != (SIZE, SIZE)


def load(path, max_ms=MAX_MS):
    """Any picture Pillow reads: GIF, APNG and WebP animations, PNG, JPEG, BMP..."""
    from PIL import Image, ImageOps, ImageSequence, UnidentifiedImageError
    try:
        im = Image.open(path)
        frames, total, truncated = [], 0, False
        for fr in ImageSequence.Iterator(im):
            delay = max(MIN_DELAY, int(fr.info.get("duration") or 100))
            if not getattr(im, "is_animated", False):
                fr = ImageOps.exif_transpose(fr)        # photos taken sideways
            frames.append((fr.convert("RGBA"), delay))
            total += delay
            if total >= max_ms:
                truncated = getattr(im, "n_frames", 1) > len(frames)
                break
    except (OSError, UnidentifiedImageError, ValueError) as e:
        raise SplashError(f"Can't read {path}: {e}") from e
    if not frames:
        raise SplashError(f"{path} has no pictures in it")
    w, h = frames[0][0].size
    return Source(str(path), w, h, frames, truncated)


def fit(img, mode="fit", bg=(0, 0, 0)):
    """An RGBA picture placed on the 128 x 128 screen (RGB) as mode says (FIT_MODES)."""
    from PIL import Image
    w, h = img.size
    if mode == "stretch":
        size = (SIZE, SIZE)
    else:
        scale = {"fit": min(SIZE / w, SIZE / h), "shrink": min(1.0, SIZE / w, SIZE / h),
                 "fill": max(SIZE / w, SIZE / h)}[mode]
        size = (max(1, round(w * scale)), max(1, round(h * scale)))
    if size != (w, h):
        enlarging = size[0] > w or size[1] > h
        two_x = size[0] >= 2 * w and size[1] >= 2 * h
        img = img.resize(size, Image.NEAREST if two_x else Image.BICUBIC if enlarging else Image.LANCZOS)
    canvas = Image.new("RGBA", (SIZE, SIZE), tuple(bg) + (255,))
    # centred; a picture bigger than the screen (crop to fill) loses the same on both sides
    x, y = (SIZE - img.width) // 2, (SIZE - img.height) // 2
    sx, sy = max(0, -x), max(0, -y)
    img = img.crop((sx, sy, sx + min(img.width, SIZE), sy + min(img.height, SIZE)))
    canvas.alpha_composite(img, (max(0, x), max(0, y)))
    return canvas.convert("RGB")


def rgb565(r, g, b):
    return (r & 0xF8) << 8 | (g & 0xFC) << 3 | b >> 3


def to_rgb(c):
    """RGB565 back to 8-bit RGB, as the screen shows it"""
    r, g, b = c >> 11 & 0x1F, c >> 5 & 0x3F, c & 0x1F
    return (r << 3 | r >> 2, g << 2 | g >> 4, b << 3 | b >> 2)


def _pixels565(img):
    """the screen's RGB565 values of a 128 x 128 RGB picture, at most 256 different ones"""
    from PIL import Image

    def values(im):
        b = im.tobytes()
        return [(b[i] & 0xF8) << 8 | (b[i + 1] & 0xFC) << 3 | b[i + 2] >> 3 for i in range(0, len(b), 3)]

    px = values(img)
    if len(set(px)) > 256:
        px = values(img.quantize(256, dither=getattr(Image, "Dither", Image).NONE).convert("RGB"))
    return px


def _packbits(idx):
    out, i, n = bytearray(), 0, len(idx)
    while i < n:
        run = 1
        while i + run < n and idx[i + run] == idx[i] and run < 130:
            run += 1
        if run >= 3:
            out += bytes((run + 125, idx[i]))
            i += run
            continue
        j = i
        while j < n and j - i < 128:
            if j + 2 < n and idx[j] == idx[j + 1] == idx[j + 2]:
                break
            j += 1
        out.append(j - i - 1)
        out += bytes(idx[i:j])
        i = j
    return bytes(out)


def encode(frames, bg=0):
    """A36G bytes from [(128 * 128 RGB565 values, delay ms)]; each frame stores what changed"""
    import struct
    body, prev = bytearray(), None
    for px, delay in frames:
        delay = max(MIN_DELAY, min(65535, int(delay)))
        if prev is None:
            x0, y0, x1, y1 = 0, 0, SIZE - 1, SIZE - 1
        else:
            rows = [y for y in range(SIZE) if px[y * SIZE:(y + 1) * SIZE] != prev[y * SIZE:(y + 1) * SIZE]]
            if not rows:
                body += struct.pack("<HBBBBHI", delay, 0, 0, 0, 0, 0, 0)
                continue
            y0, y1 = rows[0], rows[-1]
            cols = [x for x in range(SIZE) if any(px[y * SIZE + x] != prev[y * SIZE + x] for y in range(y0, y1 + 1))]
            x0, x1 = cols[0], cols[-1]
        w, h = x1 - x0 + 1, y1 - y0 + 1
        region = [px[(y0 + y) * SIZE + x0 + x] for y in range(h) for x in range(w)]
        palette = sorted(set(region))
        if len(palette) > 256:
            raise ValueError("a frame has more than 256 colours (build() reduces them)")
        index = {c: i for i, c in enumerate(palette)}
        data = _packbits([index[c] for c in region])
        body += struct.pack("<HBBBBH", delay, x0, y0, w, h, len(palette))
        body += struct.pack(f"<{len(palette)}H", *palette)
        body += struct.pack("<I", len(data)) + data
        prev = px
    return b"A36G" + struct.pack("<HHI", len(frames), bg, 12 + len(body)) + bytes(body)


def decode(blob):
    """[(128 * 128 RGB565 values, delay ms)] as the radio draws them; ValueError if it isn't A36G"""
    import struct
    if blob[:4] != b"A36G":
        raise ValueError("not a splash")
    count, bg, total = struct.unpack_from("<HHI", blob, 4)
    if total != len(blob):
        raise ValueError(f"length {total} in the header, {len(blob)} bytes given")
    screen, out, p = [bg] * (SIZE * SIZE), [], 12
    for _ in range(count):
        delay, x, y, w, h, n = struct.unpack_from("<HBBBBH", blob, p)
        p += 8
        palette = struct.unpack_from(f"<{n}H", blob, p)
        p += 2 * n
        (length,) = struct.unpack_from("<I", blob, p)
        p += 4
        data, p = blob[p:p + length], p + length
        if x + w > SIZE or y + h > SIZE:
            raise ValueError("a frame is outside the screen")
        idx, i = [], 0
        while i < len(data) and len(idx) < w * h:
            c = data[i]
            if c < 128:
                idx += data[i + 1:i + 2 + c]
                i += c + 2
            else:
                idx += [data[i + 1]] * (c - 125)
                i += 2
        for k, v in enumerate(idx[:w * h]):
            screen[(y + k // w) * SIZE + x + k % w] = palette[v]
        out.append((list(screen), delay))
    return out


@dataclass
class Splash:
    """A picture made ready for the radio."""
    frames: list                        # [(RGB565 values, delay ms)], what the radio will show
    blob: bytes                         # the A36G data that goes to the radio

    @property
    def duration_ms(self):
        return sum(d for _, d in self.frames)

    @property
    def fits(self):
        return len(self.blob) <= CAPACITY

    @property
    def percent(self):
        return len(self.blob) * 100 / CAPACITY

    @property
    def upload_seconds(self):
        return len(self.blob) / BYTES_PER_SECOND + 3


def build(source, mode="fit", bg=(0, 0, 0), still_ms=3000, every=1):
    """source fitted to the screen and coded; every: keep every n-th frame of an animation (its
    delay goes to the frames kept, so the animation still takes as long)."""
    frames = []
    if source.animated:
        for i in range(0, len(source.frames), every):
            group = source.frames[i:i + every]
            frames.append((group[0][0], sum(d for _, d in group)))
    else:
        frames = [(source.frames[0][0], still_ms)]
    out = [(_pixels565(fit(img, mode, bg)), delay) for img, delay in frames]
    return Splash(out, encode(out, rgb565(*bg)))


# ---- the radio ----------------------------------------------------------------------------------

NOT_THIS_FIRMWARE = ("The radio didn't answer. The boot splash needs Talkpod Super Firmware 1.0 or later "
                     "on the radio, switched on, with the programming cable plugged in. Stock firmware "
                     "has a still boot logo instead (Logo page).")


class Shell:
    """The firmware's serial shell."""

    def __init__(self, port, opener=None):
        self.s = (opener or rio._open)(port, 57600, timeout=0.2)
        self.s.write(b"\r")
        time.sleep(0.3)
        self.s.reset_input_buffer()

    def close(self):
        self.s.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def _reply(self, want, wait):
        t0, buf = time.monotonic(), b""
        while time.monotonic() - t0 < wait:
            buf += self.s.read(max(1, self.s.in_waiting))
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                line = line.decode("latin-1").strip()
                if want(line):
                    return line
        return None

    def command(self, cmd, want, wait=3.0):
        self.s.reset_input_buffer()
        self.s.write(cmd if isinstance(cmd, bytes) else (cmd + "\r").encode())
        return self._reply(want, wait)

    def info(self):
        """{'fw': 'TSF', 'ver': '1.00', 'splash': '00120000+000C0000', ...}"""
        line = self.command("i", lambda l: l.startswith("fw="))
        if not line:
            raise SplashError(NOT_THIS_FIRMWARE)
        info = dict(kv.split("=", 1) for kv in line.split() if "=" in kv)
        if info.get("splash_fmt") != "A36G":
            raise SplashError(f"The radio's firmware ({info.get('fw')} {info.get('ver')}) doesn't take this "
                              "kind of splash. Update Talkpod Super Firmware.")
        try:
            base, size = (int(v, 16) for v in info["splash"].split("+"))
        except (KeyError, ValueError):
            raise SplashError("The radio's firmware didn't say where the splash goes.") from None
        info["base"], info["capacity"] = base, size
        return info

    def erase(self, addr):
        if self.command(f"E {addr:X}", lambda l: l in ("ok", "refused")) != "ok":
            raise SplashError(f"The radio didn't erase its flash at {addr:#08x}.")

    def write(self, addr, data):
        for _ in range(3):
            self.s.reset_input_buffer()
            self.s.write(f"W {addr:X} {len(data)}\r".encode())
            time.sleep(0.05)                # the radio reads the command line before the bytes
            self.s.write(data + crc16(data).to_bytes(2, "big"))
            if self._reply(lambda l: l in ("ok", "crc", "refused", "timeout"), 3.0) == "ok":
                return
        raise SplashError(f"The radio didn't take the data for {addr:#08x}.")

    def read(self, addr, n):
        for _ in range(4):
            self.s.reset_input_buffer()
            self.s.write(f"X {addr:X} {n}\r".encode())
            t0, data = time.monotonic(), b""
            while time.monotonic() - t0 < 3 + n / 4000 and len(data) < n + 2:
                data += self.s.read(n + 2 - len(data))
            if len(data) == n + 2 and crc16(data[:n]) == int.from_bytes(data[n:], "big"):
                return data[:n]
        raise SplashError(f"Couldn't read the radio's flash at {addr:#08x} back.")

    def play(self):
        return self.command("G", lambda l: l in ("ok", "no splash"), wait=30) == "ok"


def send(port, blob, progress=None, opener=None):
    """Writes the splash, reads it back to check it, and plays it. progress(fraction, text)."""
    step = progress or (lambda f, t: None)
    with Shell(port, opener) as sh:
        info = sh.info()
        base, capacity = info["base"], info["capacity"]
        if len(blob) > capacity:
            raise SplashError(f"The splash is {len(blob) // 1024} KB; the radio has room for {capacity // 1024} KB.")
        sectors = range(base, base + len(blob), SECTOR)
        for i, addr in enumerate(sectors):
            sh.erase(addr)
            step(0.05 * (i + 1) / len(sectors), "Making room")
        for off in range(0, len(blob), 256):
            sh.write(base + off, blob[off:off + 256])
            step(0.05 + 0.6 * min(off + 256, len(blob)) / len(blob), "Sending the splash")
        for off in range(0, len(blob), 4096):
            n = min(4096, len(blob) - off)
            if sh.read(base + off, n) != blob[off:off + n]:
                raise SplashError("The splash on the radio doesn't match what was sent. Try again.")
            step(0.65 + 0.33 * (off + n) / len(blob), "Checking")
        step(0.99, "Playing it on the radio")
        sh.play()
        step(1.0, "Done")
    LOG.info("boot splash (%d bytes) sent to %s", len(blob), port)


def play(port, opener=None):
    with Shell(port, opener) as sh:
        sh.info()
        return sh.play()


def remove(port, opener=None):
    with Shell(port, opener) as sh:
        sh.erase(sh.info()["base"])
