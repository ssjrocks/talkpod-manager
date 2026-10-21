"""Talking to the radio, using CHIRP's Talkpod A36plus driver for the memory format and protocol.

The A36SE is the 5 W A36plus sold under another name (same firmware line), so CHIRP's
"Talkpod A36plus" driver handles it. Everything here is blocking: the UI calls it from a
worker thread.
"""

import logging
import os
import time

# CHIRP redirects stdout/stderr into its own debug.log when it isn't run from a terminal;
# this keeps the app's own logging and error reports intact.
os.environ.setdefault("CHIRP_TESTENV", "1")

import serial  # noqa: E402
from serial.tools import list_ports  # noqa: E402

from chirp import directory, errors  # noqa: E402
from chirp.drivers import mml_jc8810  # noqa: E402

LOG = logging.getLogger(__name__)

MAGIC = mml_jc8810.A36plusRadio._magic
ACK = b"\x06"

# Most specific first: the 8 W fingerprints are also listed under the 5 W model in CHIRP.
MODELS = [mml_jc8810.A36plus8wRadio, mml_jc8810.A36plusRadio]

# USB-serial chips used by K-plug programming cables.
KNOWN_CABLES = {
    (0x1A86, 0x7523): "CH340 cable",
    (0x067B, 0x2303): "Prolific PL2303 cable",
    (0x0403, 0x6001): "FTDI cable",
    (0x10C4, 0xEA60): "CP210x cable",
}


class RadioError(Exception):
    """Something the user can act on (cable, power, wrong model)."""


class Port:
    def __init__(self, device, description, known):
        self.device = device
        self.description = description
        self.known = known

    def label(self):
        return f"{self.device} — {self.description}"


def find_ports():
    """USB serial ports, programming cables first."""
    ports = []
    for p in list_ports.comports():
        if not (p.device.startswith("/dev/ttyUSB") or p.device.startswith("/dev/ttyACM")):
            continue
        known = KNOWN_CABLES.get((p.vid, p.pid)) if p.vid is not None else None
        ports.append(Port(p.device, known or p.description or "USB serial", known is not None))
    ports.sort(key=lambda p: (not p.known, p.device))
    return ports


def _open(port, baud=57600, timeout=0.5):
    try:
        return serial.Serial(port, baud, timeout=timeout)
    except serial.SerialException as e:
        if "Permission denied" in str(e):
            raise RadioError(
                f"No permission to open {port}. Add yourself to the 'dialout' group "
                "(sudo usermod -aG dialout $USER) and log out and back in."
            ) from e
        raise RadioError(f"Couldn't open {port}: {e}") from e


def identify(port):
    """Handshake only. Returns (CHIRP radio class, 8-byte ident). Leaves programming mode."""
    with _open(port, timeout=1.0) as s:
        s.reset_input_buffer()
        ack = b""
        for _ in range(5):
            s.write(MAGIC)
            ack = s.read(1)
            if ack == ACK:
                break
        if ack != ACK:
            raise RadioError(
                "The radio didn't answer. Check that it's switched on, the cable is pushed fully "
                "into the radio's side jack, and the volume isn't at zero."
            )
        s.write(b"F")
        ident = s.read(8)
        s.write(b"E")
        time.sleep(0.2)
    for cls in MODELS:
        if ident in cls._fingerprint:
            return cls, ident
    raise RadioError(
        "The radio answered but reported an unknown firmware "
        f"(identification {ident.hex(' ')}). This app supports Talkpod A36plus / A36SE "
        "firmware that CHIRP supports."
    )


def describe_model(cls):
    return "A36plus 8 W" if cls is mml_jc8810.A36plus8wRadio else "A36SE / A36plus 5 W"


def _status_cb(progress, msg):
    def fn(status):
        if progress and status.max:
            progress(min(status.cur / status.max, 1.0), msg)
    return fn


def download(port, progress=None):
    """Read the whole radio. Returns a CHIRP radio object holding the memory image."""
    cls, ident = identify(port)
    LOG.info("downloading from %s (%s, ident %s)", port, cls.MODEL, ident.hex())
    with _open(port, cls.BAUD_RATE) as pipe:
        radio = cls(pipe)
        radio.status_fn = _status_cb(progress, "Reading from radio")
        try:
            radio.sync_in()
        except errors.RadioError as e:
            raise RadioError(f"Reading the radio failed: {e}") from e
    radio.pipe = None
    return radio


def upload(port, radio, progress=None):
    """Write an image to the radio. Refuses if the radio is a different model."""
    cls, ident = identify(port)
    if cls is not model_class(radio):
        raise RadioError(
            f"This image is for a {describe_model(model_class(radio))}, but the radio is a "
            f"{describe_model(cls)}. Nothing was written."
        )
    LOG.info("uploading to %s (%s)", port, cls.MODEL)
    with _open(port, cls.BAUD_RATE) as pipe:
        radio.pipe = pipe
        radio.status_fn = _status_cb(progress, "Writing to radio")
        try:
            radio.sync_out()
        except errors.RadioError as e:
            raise RadioError(f"Writing to the radio failed part-way: {e}. Write again to finish.") from e
        finally:
            radio.pipe = None


def written_bytes(radio):
    """The parts of the image an upload sends, as {start: bytes}."""
    data = radio.get_mmap().get_packed()
    return {start: bytes(data[start:end]) for start, end in radio._ranges}


def compare(written, read_back):
    """Address ranges whose bytes differ between what was written and what the radio holds."""
    a, b = written_bytes(written), written_bytes(read_back)
    diffs = []
    for start, data in a.items():
        other = b[start]
        for i, (x, y) in enumerate(zip(data, other)):
            if x != y:
                diffs.append(start + i)
    return diffs


# Settings CHIRP shows for every A36plus but that only the 8 W firmware has: on other radios the
# byte reads 0xFF and the radio ignores writes to it.
OPTIONAL_SETTINGS = ("single_mode", "dis_s_table")


def missing_settings(radio):
    """Names of settings this particular radio image doesn't have."""
    out = set()
    for name in OPTIONAL_SETTINGS:
        try:
            if int(getattr(radio._memobj.settings, name)) == 0xFF:
                out.add(name)
        except AttributeError:
            out.add(name)
    return out


def apply_setting(radio, setting):
    """Write one changed setting into the image.

    CHIRP's set_settings() rewrites every setting it's given, which pads blank names with spaces
    and sets bytes the radio doesn't have; giving it just the one setting avoids that.
    """
    from chirp.settings import RadioSettingGroup, RadioSettings

    radio.set_settings(RadioSettings(RadioSettingGroup("changed", "changed", setting)))


def model_class(radio):
    """The driver class from MODELS for a radio object (CHIRP wraps loaded images in aliases)."""
    for cls in MODELS:
        if radio.VENDOR == cls.VENDOR and radio.MODEL == cls.MODEL:
            return cls
    return None


def load_image(path):
    """Open a CHIRP .img saved from an A36plus / A36SE."""
    name = os.path.basename(str(path))
    try:
        loaded = directory.get_radio_by_image(str(path))
    except Exception as e:
        raise RadioError(f"Couldn't open {name}: {e}") from e
    if model_class(loaded) is None:
        raise RadioError(f"{name} is a {loaded.get_name()} image, not a Talkpod A36plus / A36SE.")
    return copy_radio(loaded)


def copy_radio(radio):
    """An independent copy of an image (channels and settings)."""
    from chirp import memmap

    return model_class(radio)(memmap.MemoryMapBytes(bytes(radio.get_mmap().get_packed())))
