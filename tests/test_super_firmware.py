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


def scramble_of(mem):
    return next(s for s in mem.extra if s.get_name() == "scramble").value


@pytest.mark.parametrize("raw, label", [(0, "Off"), (4, "2600 Hz (SCRAM1)"), (8, "2700 Hz (SCRAM2)"),
                                        (12, "2800 Hz"), (40, "3500 Hz"), (60, "Rolling")])
def test_scramble_values_of_super_firmware_read_and_round_trip(image, raw, label):
    image._memobj.memory[10].scramble = raw            # channel 11
    m = image.get_memory(11)
    assert str(scramble_of(m)) == label
    copy = radio.copy_radio(image)                     # an image of either firmware keeps the value
    copy.set_memory(m)
    assert int(copy._memobj.memory[10].scramble) == raw


def test_choosing_rolling_writes_the_firmwares_value(image):
    m = image.get_memory(11)
    scramble_of(m).set_value("Rolling")
    image.set_memory(m)
    assert int(image._memobj.memory[10].scramble) == radio.SCRAMBLE_ROLLING == 60


# ---- the stock settings and VFO logs

def raw_log(base, size, map_bytes, records):
    """A sector as stock leaves it: the bitmap, then the records, the newest last."""
    sector = bytearray(b"\xff" * 0x1000)
    for i in range(len(records) - 1):
        sector[i // 8] &= ~(1 << (i % 8)) & 0xFF
    for i, r in enumerate(records):
        body = r.ljust(size - 2, b"\0")
        crc = radio.tsf_settings.crc16(body)
        sector[0x10 + i * size:0x10 + (i + 1) * size] = body + crc.to_bytes(2, "little")
    return bytes(sector)


def test_an_image_with_raw_logs_gets_its_live_records_back(image):
    mm = image.get_mmap()
    settings = bytes(mm.get(0x9000, 0x40))
    vfo = bytes(mm.get(0x8000, 0x40))
    mm.set(0x9000, raw_log(0x9000, 0x60, 6, [bytes(0x40), bytes(0x20) * 2, settings]))
    mm.set(0x8000, raw_log(0x8000, 0x42, 8, [bytes(0x40), vfo]))
    radio.repair_stock_blocks(image)
    assert mm.get(0x9000, 0x40) == settings and mm.get(0x8000, 0x40) == vfo
    before = memory_of(image)
    radio.repair_stock_blocks(image)                    # a healthy image stays as it is
    assert memory_of(image) == before


@pytest.mark.parametrize("version, sent", [("1.13", False), ("1.14", True)])
def test_the_stock_blocks_only_go_to_firmware_that_shows_them(monkeypatch, image, version, sent):
    fake = FakeRadio(radio.SUPER_IDENT, memory_of(image), version=version)
    attach(monkeypatch, fake)
    radio.upload("/dev/fake", radio.copy_radio(image))
    assert (0x9000 in fake.writes) is sent and (0x8000 in fake.writes) is sent
    assert 0x0000 in fake.writes
    assert radio.compare(image, radio.download("/dev/fake")) == []
