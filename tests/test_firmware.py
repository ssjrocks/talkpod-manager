"""The firmware flasher against a simulated radio that follows Talkpod's bootloader protocol."""

import struct

import pytest

from talkpod_manager import firmware, radio

IDENT_126 = bytes.fromhex("0000009C00200405")


def fake_image(size=63 * 1024):
    """Something that passes Image's checks: vector table + the A36plus markers."""
    fw = bytearray(size)
    struct.pack_into("<II", fw, 0, 0x20003E48, 0x080004E1)
    fw[0x100:0x10C] = b"PROGRAMJC37U"
    fw[0x200:0x20E] = b"TalkpodA36Plus"
    fw[0x300:0x308] = b" V9.99X\x00"
    return firmware.unscramble(bytes(fw))  # scramble (it's its own inverse)


class FakeRadio:
    def __init__(self, fail_block=None, error=None):
        self.state = "app"
        self.blocks = {}
        self.count = None
        self.ended = False
        self.fail_block = fail_block
        self.error = error
        self.log = []

    def open(self, port, baud=57600, timeout=0.5):
        return FakeSerial(self, baud)


class FakeSerial:
    def __init__(self, fake, baud):
        self.f, self.baud, self.out, self.inbuf = fake, baud, bytearray(), bytearray()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass

    def close(self):
        pass

    def reset_input_buffer(self):
        self.out.clear()

    @property
    def in_waiting(self):
        return len(self.out)

    def read(self, n=1):
        d = bytes(self.out[:n])
        del self.out[:n]
        return d

    def write(self, data):
        f = self.f
        if self.baud == 57600:
            if data == radio.MAGIC:          # identify()
                self.out += radio.ACK
            elif data == b"F":
                self.out += IDENT_126
            elif data == b"PROGRAMJC37U":
                self.out += radio.ACK
            elif data == b"UPDATE":
                f.state = "boot-pending"
                self.out += radio.ACK
            return len(data)
        self.inbuf += data
        while len(self.inbuf) >= 8:
            length = self.inbuf[3] << 8 | self.inbuf[4]
            if len(self.inbuf) < 8 + length:
                break
            assert self.inbuf[7 + length] == firmware.TAIL
            cmd, arg, payload = firmware.parse(bytes(self.inbuf[:8 + length]))
            del self.inbuf[:8 + length]
            f.log.append(cmd)
            if cmd == firmware.CMD_INTO_BOOT:
                assert f.state == "boot-pending"
                f.state = "boot"
            elif cmd == firmware.CMD_HELLO:
                assert f.state == "boot" and payload == b"BOOTLOADER"
            elif cmd == firmware.CMD_COUNT:
                f.count = payload[0]
            elif cmd == firmware.CMD_DATA:
                assert len(payload) == 1024
                if arg == f.fail_block:
                    self.out += firmware.frame(f.error, 0)
                    continue
                f.blocks[arg] = payload
            elif cmd == firmware.CMD_END:
                f.ended = True
            self.out += firmware.frame(cmd, firmware.OK)
        return len(data)


@pytest.fixture
def fake(monkeypatch):
    f = FakeRadio()
    monkeypatch.setattr(radio, "_open", f.open)
    return f


def test_image_checks():
    img = firmware.Image(fake_image(), "x.kdhx")
    assert img.problems == [] and img.version == "V9.99X" and img.chunks == 63
    bad = firmware.Image(b"\x00" * 4096, "junk")
    assert bad.problems


def test_automatic_flash(fake):
    data = fake_image(63 * 1024 + 100)  # last block is short and gets padded
    img = firmware.Image(data, "t.kdhx")
    firmware.flash("/dev/fake", img)
    assert fake.log[:3] == [firmware.CMD_INTO_BOOT, firmware.CMD_HELLO, firmware.CMD_COUNT]
    assert fake.count == 64 and fake.ended
    sent = b"".join(fake.blocks[i] for i in range(64))
    assert sent[:len(data)] == data and sent[len(data):] == b"\x00" * (64 * 1024 - len(data))


def test_manual_flash_skips_restart(fake):
    fake.state = "boot"
    firmware.flash("/dev/fake", firmware.Image(fake_image(), "t"), manual=True)
    assert fake.log[0] == firmware.CMD_HELLO and fake.ended


def test_flash_error_stops(monkeypatch):
    f = FakeRadio(fail_block=5, error=0xE4)
    monkeypatch.setattr(radio, "_open", f.open)
    with pytest.raises(firmware.FirmwareError, match="couldn't write"):
        firmware.flash("/dev/fake", firmware.Image(fake_image(), "t"))
    assert not f.ended


def test_max_image_refused_for_5w():
    big = firmware.Image(fake_image(100 * 1024), "max.kdhx")
    with pytest.raises(firmware.FirmwareError, match="too big"):
        firmware.check_for_radio(big, radio.mml_jc8810.A36plusRadio)
