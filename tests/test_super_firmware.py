"""Reading and writing through the stock programming protocol, as stock and as Talkpod Super Firmware
(1.1 and later answer the same 'R' / 'W' commands), with CHIRP's driver doing the transfers."""

import pytest

from talkpod_manager import radio

IMAGE = "tests/data/a36se-fw126-uhf-cb.img"
STOCK_IDENT = b"\x00\x00\x00\x9C\x00\x20\x04\x05"   # fw 1.26


class FakeRadio:
    """A radio's memory window behind the stock protocol."""

    def __init__(self, ident, memory, version=None):
        self.ident, self.memory, self.version = ident, bytearray(memory), version
        self.writes = []


class FakeSerial:
    def __init__(self, f):
        self.f, self.out, self.inbuf = f, bytearray(), bytearray()

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

    def read_until(self, expected=b"\n", size=None):
        i = self.out.find(expected)
        n = len(self.out) if i < 0 else i + len(expected)
        return self.read(n if size is None else min(n, size))

    def write(self, data):
        self.inbuf += data
        while self.inbuf:
            b = self.inbuf
            if b.startswith(radio.MAGIC):
                self.out += radio.ACK
                del b[:len(radio.MAGIC)]
            elif b[:1] in (b"F", b"E"):
                if b[:1] == b"F":
                    self.out += self.f.ident
                del b[:1]
            elif b.startswith(b"\ri\r"):
                if self.f.version:
                    self.out += f"fw=TSF ver={self.f.version} splash=00120000+0007D000\r\n".encode()
                del b[:3]
            elif b[:1] == b"R" and len(b) >= 4:
                a, n = b[1] << 8 | b[2], b[3]
                self.out += bytes(b[:4]) + bytes(self.f.memory[a:a + n])
                del b[:4]
            elif b[:1] == b"W" and len(b) >= 4 and len(b) >= 4 + b[3]:
                a, n = b[1] << 8 | b[2], b[3]
                self.f.memory[a:a + n] = b[4:4 + n]
                self.f.writes.append(a)
                self.out += radio.ACK
                del b[:4 + n]
            else:
                break
        return len(data)


@pytest.fixture
def image():
    return radio.load_image(IMAGE)


def attach(monkeypatch, fake):
    monkeypatch.setattr(radio, "_open", lambda *a, **k: FakeSerial(fake))
    monkeypatch.setattr(radio.time, "sleep", lambda s: None)


def memory_of(r):
    return bytes(r.get_mmap().get_packed())


def test_read_from_super_firmware(monkeypatch, image):
    fake = FakeRadio(radio.SUPER_IDENT, memory_of(image), version="1.10")
    attach(monkeypatch, fake)
    r = radio.download("/dev/fake")
    assert memory_of(r) == memory_of(image)
    assert r.talkpod_firmware.kind == "super" and r.talkpod_firmware.version == "1.10"
    assert r.talkpod_firmware.name == "Talkpod Super Firmware 1.10"
    assert radio.model_class(r) is radio.mml_jc8810.A36plusRadio     # a plain A36plus image
    assert r.get_memory(101).duplex == "+"


def test_read_from_stock(monkeypatch, image):
    fake = FakeRadio(STOCK_IDENT, memory_of(image))
    attach(monkeypatch, fake)
    r = radio.download("/dev/fake")
    assert r.talkpod_firmware.kind == "stock" and r.talkpod_firmware.name == "stock firmware"


def test_a_stock_image_writes_to_super_firmware(monkeypatch, image):
    edited = radio.copy_radio(image)
    mem = edited.get_memory(300)
    mem.freq, mem.name, mem.empty = 476_500_000, "NEW300", False
    edited.set_memory(mem)
    fake = FakeRadio(radio.SUPER_IDENT, memory_of(image), version="1.10")
    attach(monkeypatch, fake)
    radio.upload("/dev/fake", edited)
    assert fake.writes and radio.compare(edited, radio.download("/dev/fake")) == []


def test_an_8w_image_is_refused_by_a_5w_super_firmware_radio(monkeypatch, image):
    from chirp import memmap
    big = radio.mml_jc8810.A36plus8wRadio(memmap.MemoryMapBytes(memory_of(image)))
    attach(monkeypatch, FakeRadio(radio.SUPER_IDENT, memory_of(image)))
    with pytest.raises(radio.RadioError, match="Nothing was written"):
        radio.upload("/dev/fake", big)


def test_super_firmware_1_0_cant_be_read(monkeypatch, image):
    attach(monkeypatch, FakeRadio(b"A36CFW01", memory_of(image), version="1.00"))
    with pytest.raises(radio.RadioError, match="Super Firmware 1.00, which can't be read"):
        radio.download("/dev/fake")
