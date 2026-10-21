"""The boot-logo upload against a simulated radio that follows Talkpod's protocol."""

import pytest

from talkpod_manager import logo, radio

IDENT_126 = bytes.fromhex("0000009C00200405")


class FakeRadio:
    """Shared state for every serial port opened during one upload."""

    def __init__(self, refuse=None):
        self.refuse = refuse
        self.flash = {}
        self.erased = None
        self.address = None
        self.picture_mode = False
        self.over = False
        self.commands = []

    def open(self, port, baud=57600, timeout=0.5):
        return FakeSerial(self, baud)


class FakeSerial:
    def __init__(self, fake, baud):
        self.fake = fake
        self.baud = baud
        self.out = bytearray()
        self.inbuf = bytearray()

    # pyserial-ish API
    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()

    def close(self):
        pass

    def flush(self):
        pass

    def reset_input_buffer(self):
        self.out.clear()

    @property
    def in_waiting(self):
        return len(self.out)

    def read(self, n=1):
        data = bytes(self.out[:n])
        del self.out[:n]
        return data

    def write(self, data):
        f = self.fake
        if self.baud == 57600:
            if data == radio.MAGIC:
                self.out += radio.ACK
            elif data == b"F":
                self.out += IDENT_126
            elif data == b"D":
                f.picture_mode = True
            return len(data)
        assert f.picture_mode, "115200 traffic before picture mode"
        self.inbuf += data
        while len(self.inbuf) >= 8:
            length = self.inbuf[4] << 8 | self.inbuf[5]
            if len(self.inbuf) < 8 + length:
                break
            cmd, pid, payload = logo.parse_frame(bytes(self.inbuf[:8 + length]))
            del self.inbuf[:8 + length]
            f.commands.append(cmd)
            if cmd == logo.CMD_ERASE:
                assert pid == logo.ERASE_ID
                f.erased = (int.from_bytes(payload[:4], "little"), int.from_bytes(payload[4:6], "big"))
            elif cmd == logo.CMD_SETADDRESS:
                f.address = int.from_bytes(payload, "little")
            elif cmd == logo.CMD_WRITE:
                f.flash[pid] = payload
            elif cmd == logo.CMD_OVER:
                f.over = True
                continue
            answer = b"N" if f.refuse == cmd else b"Y"
            self.out += logo.frame(cmd, 0, answer)
        return len(data)


@pytest.fixture
def fake(monkeypatch):
    f = FakeRadio()
    monkeypatch.setattr(radio, "_open", f.open)
    return f


def test_upload_sequence(fake):
    pixels = bytes(i % 251 for i in range(logo.IMAGE_BYTES))
    seen = []
    logo.send("/dev/fake", pixels, lambda frac, text: seen.append(frac))
    assert fake.commands[:3] == [logo.CMD_HANDSHAKE, logo.CMD_ERASE, logo.CMD_SETADDRESS]
    assert fake.commands[-1] == logo.CMD_OVER
    assert fake.erased == (0x10000, 1)
    assert fake.address == 0x10000
    assert b"".join(fake.flash[i] for i in range(32)) == pixels
    assert fake.over
    assert seen[-1] == 1.0


def test_refusal_is_reported(monkeypatch):
    f = FakeRadio(refuse=logo.CMD_ERASE)
    monkeypatch.setattr(radio, "_open", f.open)
    with pytest.raises(logo.LogoError):
        logo.send("/dev/fake", bytes(logo.IMAGE_BYTES))
    assert logo.CMD_WRITE not in f.commands


def test_wrong_size_rejected():
    with pytest.raises(ValueError):
        logo.send("/dev/fake", b"\x00" * 100)
