"""The receiver event log: parsing the firmware's dump, explaining it, reading it over the shell, keeping it."""

import datetime as dt
import time

import pytest

from talkpod_manager import eventlog, radio

# as firmware 1.22 printed it in the emulator: a false squelch tail on a steady signal, then CH 40
DUMP = """EVLOG 00000E10 000A
000001E9 SQUELCH 0001 02D7B110
000001E9 TUNE 0000 02D7B110
000001ED TUNE 0010 02D7592C
000001F6 SQUELCH 0005 02D7592C
0000025E BOOT 0000 00000000
0000025F OPEN 0059 02D7592C
000007D6 IRQ 0000 00000400
000007D6 HOLD 0004 02D7592C
key 0
000009CA HOLD 0000 02D7592C
00000C68 TUNE 0010 02D87460
END
""".splitlines()


def test_parse_reads_every_event_and_skips_log_lines():
    now, events = eventlog.parse(DUMP)
    assert now == 0xE10
    assert [e.name for e in events] == ["SQUELCH", "TUNE", "TUNE", "SQUELCH", "BOOT", "OPEN", "IRQ", "HOLD",
                                        "HOLD", "TUNE"]
    assert events[5].ms == 0x25F and events[5].v == 47667500


def test_summaries_say_what_happened():
    _, events = eventlog.parse(DUMP)
    s = [e.summary() for e in events]
    assert s[2] == "Tuned to 476.67500 MHz, FM narrow"
    assert s[5] == "Squelch opened on 476.67500 MHz, -71 dBm"
    assert s[6] == "Receiver chip: squelch-tail tone"
    assert s[7] == "Received audio muted for a squelch tail"
    assert s[8] == "Received audio no longer muted"
    assert s[3] == "Squelch level 5"


@pytest.mark.parametrize("line, text", [
    ("1 CARRIER 0001 02D7592C", "Carrier without the right tone on 476.67500 MHz"),
    ("1 PKT 0064 02D7592C", "Data packet: message on 476.67500 MHz"),
    ("1 PKT 0007 02D7592C", "Data packet: type 7, noise on 476.67500 MHz"),
    ("1 PKT_LOST 0000 02D7592C", "Data packet started and never finished on 476.67500 MHz"),
    ("1 TX 0001 02D7592C", "Transmitting on 476.67500 MHz"),
    ("1 TX 0000 02D7592C", "Stopped transmitting on 476.67500 MHz"),
    ("1 HOLD 0006 02D7592C", "Received audio muted for data arriving and a squelch tail"),
    ("1 IRQ 0000 00002003", "Receiver chip: FSK sync word, packet complete, flags 0x0001"),
    ("1 TUNE 0001 0BB80000", "Tuned to 1966.08000 MHz, AM"),
])
def test_each_kind_of_event(line, text):
    _, (e,) = eventlog.parse(["EVLOG 2 1", line, "END"])
    assert e.summary() == text
    assert e.description()


def test_no_header_is_an_error():
    with pytest.raises(eventlog.EventLogError):
        eventlog.parse(["key 1", "END"])


class FakeRadio:
    """The firmware's shell as far as the event log needs it."""

    def __init__(self, version="1.22", answers=True):
        self.version, self.answers, self.out, self.line, self.cleared = version, answers, bytearray(), b"", False

    @property
    def in_waiting(self):
        return len(self.out)

    def read(self, n=1):
        data, self.out[:] = bytes(self.out[:n]), self.out[n:]
        return data

    def reset_input_buffer(self):
        self.out.clear()

    def close(self):
        pass

    def write(self, data):
        for b in data:
            if b != 13:
                self.line += bytes([b])
                continue
            cmd, self.line = self.line.decode(), b""
            if not self.answers:
                continue
            if cmd == "i":
                self.out += f"fw=TSF ver={self.version} board=HWVER02\r\n".encode()
            elif cmd == "L":
                self.out += "\r\n".join(DUMP).encode() + b"\r\n"
            elif cmd == "l":
                self.cleared = True
                self.out += b"ok\r\n"


def test_read_over_the_shell():
    fake = FakeRadio()
    report = eventlog.read("/dev/fake", opener=lambda *a, **k: fake)
    assert report.now == 0xE10 and len(report.events) == 10 and report.version == "1.22"
    assert abs(report.read_at - time.time()) < 60


@pytest.fixture
def brisbane(monkeypatch):
    monkeypatch.setenv("TZ", "Australia/Brisbane")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


def test_lines_have_local_timestamps(brisbane):
    now, events = eventlog.parse(DUMP)
    read_at = dt.datetime(2026, 11, 6, 8, 30, tzinfo=dt.timezone.utc).timestamp()     # 18:30 in Brisbane
    lines = eventlog.Report(read_at, now, "1.22", events).lines()
    assert lines[0][0] == "Read 2026-11-06 18:30:00 AEST from Talkpod Super Firmware 1.22: 10 events"
    # OPEN at 0x25F ms, read at 0xE10: 3.0 s earlier
    assert lines[6][0] == "2026-11-06 18:29:57  Squelch opened on 476.67500 MHz, -71 dBm"
    assert all(tip for _text, tip in lines)


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.setattr(eventlog.paths, "state_dir", lambda: tmp_path)
    return tmp_path


def test_reports_are_kept_across_runs(state):
    now, events = eventlog.parse(DUMP)
    first = eventlog.Report(1000.0, now, "1.22", events)
    assert eventlog.load() == []
    assert eventlog.keep(first) == [first]
    second = eventlog.Report(2000.0, 5, "1.22", [])
    assert eventlog.keep(second) == [first, second]
    assert eventlog.load() == [first, second]           # what a new run of the app reads
    assert second.lines()[1][0] == "(the log was empty)"


def test_only_the_newest_reports_are_kept(state, monkeypatch):
    monkeypatch.setattr(eventlog, "MAX_REPORTS", 3)
    for i in range(5):
        eventlog.keep(eventlog.Report(float(i), 0, "1.22", []))
    assert [r.read_at for r in eventlog.load()] == [2.0, 3.0, 4.0]


def test_a_damaged_file_is_ignored(state):
    eventlog.saved_path().write_text("{not json")
    assert eventlog.load() == []


def test_clear():
    fake = FakeRadio()
    eventlog.clear("/dev/fake", opener=lambda *a, **k: fake)
    assert fake.cleared


@pytest.mark.parametrize("fake, words", [
    (FakeRadio(version="1.21"), "1.21"),
    (FakeRadio(answers=False), "didn't answer"),
])
def test_old_firmware_or_no_answer_says_what_to_do(fake, words):
    with pytest.raises(eventlog.EventLogError, match=words) as e:
        eventlog.read("/dev/fake", opener=lambda *a, **k: fake)
    assert isinstance(e.value, radio.RadioError)       # shown to the user, not reported as a crash
