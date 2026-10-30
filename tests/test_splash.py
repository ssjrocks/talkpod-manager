"""Boot splash: fitting pictures, the A36G coding, and sending against a simulated firmware shell."""

import pytest
from PIL import Image

from talkpod_manager import logo, splash

RED, BLUE, BLACK = (255, 0, 0), (0, 0, 255), (0, 0, 0)


def px(img, x, y):
    return img.getpixel((x, y))


def solid(w, h, colour, alpha=255):
    return Image.new("RGBA", (w, h), colour + (alpha,))


# ---- fitting ------------------------------------------------------------------------------------

def test_fit_keeps_the_shape_and_centres():
    out = splash.fit(solid(256, 128, RED), "fit")
    assert out.size == (128, 128)
    assert px(out, 64, 10) == BLACK and px(out, 64, 40) == RED and px(out, 64, 100) == BLACK


def test_fit_enlarges_small_pictures():
    out = splash.fit(solid(32, 16, RED), "fit")
    assert px(out, 0, 64) == RED and px(out, 127, 64) == RED and px(out, 64, 10) == BLACK


def test_shrink_leaves_small_pictures_alone():
    out = splash.fit(solid(32, 16, RED), "shrink")
    assert px(out, 64, 64) == RED
    assert px(out, 47, 64) == BLACK and px(out, 48, 64) == RED and px(out, 79, 64) == RED and px(out, 80, 64) == BLACK


def test_shrink_makes_big_pictures_smaller():
    assert splash.fit(solid(256, 128, RED), "shrink").tobytes() == splash.fit(solid(256, 128, RED), "fit").tobytes()


def test_stretch_fills_the_screen():
    out = splash.fit(solid(256, 32, RED), "stretch")
    assert all(px(out, x, y) == RED for x, y in [(0, 0), (127, 127), (64, 5)])


def test_fill_crops_the_sides():
    img = Image.new("RGBA", (256, 128), RED + (255,))
    img.paste(BLUE + (255,), (128, 0, 256, 128))
    out = splash.fit(img, "fill")
    assert px(out, 0, 64) == RED and px(out, 63, 64) == RED and px(out, 64, 64) == BLUE and px(out, 127, 0) == BLUE


def test_transparency_shows_the_background():
    out = splash.fit(solid(128, 128, RED, alpha=0), "fit", bg=(0, 255, 0))
    assert px(out, 10, 10) == (0, 255, 0)


# ---- coding -------------------------------------------------------------------------------------

def frame_of(fn):
    return [fn(i % 128, i // 128) for i in range(128 * 128)]


def test_encode_decode_round_trip_and_deltas():
    a = frame_of(lambda x, y: splash.rgb565(x // 8 * 16, y // 8 * 16, 0))     # 256 colours
    b = list(a)
    for y in range(40, 50):
        for x in range(10, 30):
            b[y * 128 + x] = 0xFFFF
    blob = splash.encode([(a, 100), (b, 50), (b, 70)], bg=0x1234)
    assert blob[:4] == b"A36G"
    frames = splash.decode(blob)
    assert [f for f, _ in frames] == [a, b, b]
    assert [d for _, d in frames] == [100, 50, 70]
    # the second frame stores only the changed 20 x 10 rectangle, the third nothing
    first = 12 + 8 + 2 * len(set(a)) + 4
    first += int.from_bytes(blob[first - 4:first], "little")
    assert blob[first + 2:first + 6] == bytes((10, 40, 20, 10))


def test_packbits_runs_and_literals():
    import struct
    idx = [0] * 300 + [1, 2, 3, 4] + [5] * 3 + list(range(200))
    data = splash._packbits(idx)
    body = struct.pack("<HBBBBH", 20, 0, 0, 128, 4, 256) + struct.pack("<256H", *range(256))
    body += struct.pack("<I", len(data)) + data
    blob = b"A36G" + struct.pack("<HHI", 1, 0, 12 + len(body)) + body
    assert splash.decode(blob)[0][0][:len(idx)] == idx


def test_more_than_256_colours_cannot_be_coded():
    with pytest.raises(ValueError):
        splash.encode([(list(range(300)) + [0] * (128 * 128 - 300), 100)])


def test_many_colours_are_reduced_to_256():
    img = Image.new("RGB", (128, 128))
    img.putdata([(x * 2, y * 2, (x + y) % 256) for y in range(128) for x in range(128)])
    values = splash._pixels565(img)
    assert len(set(values)) <= 256


def test_build_still_picture(tmp_path):
    p = tmp_path / "still.png"
    solid(300, 200, BLUE).save(p)
    src = splash.load(p)
    assert (src.width, src.height, src.animated, src.needs_resize) == (300, 200, False, True)
    s = splash.build(src, "fit", still_ms=2000)
    assert len(s.frames) == 1 and s.duration_ms == 2000 and s.fits
    assert splash.decode(s.blob) == s.frames


def make_gif(path, n, ms=40, size=(64, 64)):
    frames = []
    for i in range(n):
        im = Image.new("RGB", size, BLACK)
        im.paste(RED, (i % size[0], 0, i % size[0] + 4, 4))
        frames.append(im)
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=ms, loop=0)


def test_build_animation_and_skipping_frames(tmp_path):
    p = tmp_path / "a.gif"
    make_gif(p, 10)
    src = splash.load(p)
    assert src.animated and len(src.frames) == 10 and src.duration_ms == 400
    every = splash.build(src, "shrink")
    half = splash.build(src, "shrink", every=2)
    assert len(half.frames) == 5 and half.duration_ms == every.duration_ms == 400
    assert len(half.blob) < len(every.blob)
    assert splash.decode(every.blob) == every.frames


def test_long_animations_are_cut(tmp_path):
    p = tmp_path / "long.gif"
    make_gif(p, 60, ms=500)
    src = splash.load(p)
    assert src.truncated and src.duration_ms == splash.MAX_MS


def test_unreadable_file(tmp_path):
    p = tmp_path / "x.gif"
    p.write_text("not a picture")
    with pytest.raises(splash.SplashError):
        splash.load(p)


# ---- the radio ----------------------------------------------------------------------------------

class FakeShell:
    """The firmware's serial shell, with its flash, a log line now and then, and a CRC error."""

    def __init__(self, answers=True, crc_fail_at=None):
        self.answers = answers
        self.flash = bytearray(b"\xff" * 0x200000)
        self.crc_fail_at = crc_fail_at
        self.out = bytearray()
        self.line = b""
        self.binary = None              # (addr, need)
        self.erased, self.played = [], 0
        self.closed = False

    # pyserial-ish
    @property
    def in_waiting(self):
        return len(self.out)

    def read(self, n=1):
        data, self.out[:] = bytes(self.out[:n]), self.out[n:]
        return data

    def reset_input_buffer(self):
        self.out.clear()

    def close(self):
        self.closed = True

    def write(self, data):
        for b in data:
            if self.binary:
                self.bin += bytes([b])
                if len(self.bin) == self.binary[1] + 2:
                    self._store()
                continue
            if b == 13:
                self._run(self.line.decode())
                self.line = b""
            else:
                self.line += bytes([b])

    def say(self, text):
        self.out += b"key MENU\r\n" + text.encode() + b"\r\n"     # log lines come and go

    def _run(self, cmd):
        if not self.answers or not cmd:
            return
        op, *args = cmd.split()
        if op == "i":
            self.say("fw=TSF ver=1.00 board=HWVER02 splash=00120000+000C0000 splash_fmt=A36G")
        elif op == "E":
            a = int(args[0], 16)
            ok = 0x110000 <= a < 0x1F0000
            if ok:
                self.flash[a:a + 0x1000] = b"\xff" * 0x1000
                self.erased.append(a)
            self.say("ok" if ok else "refused")
        elif op == "W":
            self.binary, self.bin = (int(args[0], 16), int(args[1])), b""
        elif op == "X":
            a, n = int(args[0], 16), int(args[1])
            data = bytes(self.flash[a:a + n])
            self.out += data + logo.crc16(data).to_bytes(2, "big")
        elif op == "G":
            self.played += 1
            self.say("ok" if self.flash[0x120000:0x120004] == b"A36G" else "no splash")

    def _store(self):
        (addr, n), data = self.binary, self.bin
        self.binary = None
        if self.crc_fail_at == addr:
            self.crc_fail_at = None
            self.say("crc")
            return
        assert logo.crc16(data[:n]) == int.from_bytes(data[n:], "big")
        for i, v in enumerate(data[:n]):
            self.flash[addr + i] &= v
        self.say("ok")


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(splash.time, "sleep", lambda s: None)


def test_send_writes_checks_and_plays(tmp_path):
    p = tmp_path / "a.gif"
    make_gif(p, 6)
    s = splash.build(splash.load(p))
    fake = FakeShell(crc_fail_at=0x120100)
    steps = []
    splash.send("/dev/fake", s.blob, lambda f, t: steps.append((f, t)), opener=lambda *a, **k: fake)
    assert bytes(fake.flash[0x120000:0x120000 + len(s.blob)]) == s.blob
    assert fake.erased[0] == 0x120000 and len(fake.erased) == (len(s.blob) + 0xFFF) // 0x1000
    assert fake.played == 1 and fake.closed
    fractions = [f for f, _ in steps]
    assert fractions == sorted(fractions) and fractions[-1] == 1.0


def test_stock_firmware_gets_a_clear_message():
    with pytest.raises(splash.SplashError, match="Talkpod Super Firmware"):
        splash.send("/dev/fake", b"A36G", opener=lambda *a, **k: FakeShell(answers=False))


def test_too_big_is_refused_before_anything_is_erased():
    fake = FakeShell()
    with pytest.raises(splash.SplashError, match="room"):
        splash.send("/dev/fake", b"A36G" + bytes(splash.CAPACITY), opener=lambda *a, **k: fake)
    assert not fake.erased


def test_play_and_remove():
    fake = FakeShell()
    open_ = lambda *a, **k: fake  # noqa: E731
    assert splash.play("/dev/fake", open_) is False
    fake.flash[0x120000:0x120004] = b"A36G"
    assert splash.play("/dev/fake", open_) is True
    splash.remove("/dev/fake", open_)
    assert fake.erased == [0x120000] and fake.flash[0x120000] == 0xFF
