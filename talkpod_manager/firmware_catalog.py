"""Firmware the app offers ready to flash, and where each build comes from.

No third-party firmware is copied into this app. A build is downloaded from its author's GitHub
when it's chosen, and it must match a SHA-256 before it goes anywhere near a radio:
- Talkpod Super Firmware: the newest release of ssjrocks/talkpod-super-firmware, checked against
  the digest GitHub publishes with the release asset. A copy of 1.23 ships with the app for when
  there is no internet (and is offered whenever GitHub only has older releases).
- VR2TE's "Super" builds of Talkpod's firmware: files from a pinned commit of
  VR2TE/Talkpod-A36plus-Firmware, checked against checksums pinned here. Talkpod's own firmware
  page links that repository.
Stock firmware comes as .zip / .rar archives from Talkpod's page (STOCK_PAGE): unpack one and flash
the .kdhx inside as a file.
"""

import hashlib
import json
import logging
import urllib.request
from dataclasses import dataclass, replace
from importlib import resources

from . import __version__, paths
from .updater import parse_version
from .firmware import Image
from .radio import RadioError

LOG = logging.getLogger(__name__)

TSF_REPO = "ssjrocks/talkpod-super-firmware"
TSF_PAGE = f"https://github.com/{TSF_REPO}"
VR2TE_REPO = "VR2TE/Talkpod-A36plus-Firmware"
VR2TE_COMMIT = "ff69e78e2a2ce8ac11638bd68855b2f4e5778f91"
VR2TE_PAGE = f"https://github.com/{VR2TE_REPO}/tree/main/A36plus"
STOCK_PAGE = "https://talkpodonline.com/pages/firmware-software"
STOCK_PAGE_ALT = "https://talkpod.com/pages/firmware_driver"
MAX_BYTES = 128 * 1024


class CatalogError(RadioError):
    """A download that failed or didn't match: something the user can act on."""


@dataclass(frozen=True)
class Build:
    key: str
    title: str
    version: str
    page: str                       # where to read about it
    summary: str
    warning: str                    # shown before flashing
    after: str                      # shown after flashing
    url: str                        # where the file comes from
    sha256: str
    filename: str
    bundled: str = ""               # a copy in talkpod_manager/data/firmware


TSF = Build(
    key="tsf",
    title="Talkpod Super Firmware",
    version="1.23",
    page=TSF_PAGE,
    summary="New firmware with the stock settings: dual-watch interface, FM/AM and SSB receive, a frequency "
            "scanner, wide transmit range (108–138 and 406.0–406.1 MHz blocked), CTCSS/DCS, "
            "UV-K5-compatible text messages, APRS, POCSAG pager, a keyed rolling voice scrambler and an animated "
            "boot splash. Read and Write keep working.",
    warning="It transmits across the chip's whole range except the blocked bands, so stay within your licence. "
            "The stock settings already on the radio take effect, so check Roger, the side keys, Menu exit and Battery "
            "save afterwards. In this version the FM radio plays no sound, and the frequency scanner, SSB and most "
            "stock settings aren't tested on air yet.",
    after="The radio restarts with Talkpod Super Firmware. Read works as before, and the Splash page can now "
          "give it a boot animation.",
    url=f"https://github.com/{TSF_REPO}/releases/download/v1.23/talkpod-super-firmware-v1.23.kdhx",
    sha256="609b7177822ac864919a56fc7329356295a54a7f7d5aa701734c7241415ef0d5",
    filename="talkpod-super-firmware-v1.23.kdhx",
    bundled="talkpod-super-firmware-v1.23.kdhx",
)

_VR2TE_SUMMARY = ("VR2TE's research build of Talkpod's own firmware, with wider ranges: transmit 18–108, 136–350 and "
                  "390–630 MHz, receive 18–660 and 840–999 MHz. Switch the radio on holding PTT and 8 for the "
                  "full-frequency mode. Read and Write keep working.")
_VR2TE_WARNING = ("This is untested research firmware. Its author warns that transmitting below 108 MHz for more "
                  "than 3 seconds destroys the power amplifier, and that it's for use with a dummy load. "
                  "Transmitting outside your licence is illegal.")
_VR2TE_AFTER = ("The radio restarts with VR2TE's Super firmware. For the full frequency range, switch it on while "
                "holding PTT and 8.")


def _vr2te(key, title, version, name, sha256, summary=_VR2TE_SUMMARY):
    return Build(key, title, version, VR2TE_PAGE, summary, _VR2TE_WARNING, _VR2TE_AFTER,
                 f"https://raw.githubusercontent.com/{VR2TE_REPO}/{VR2TE_COMMIT}/A36plus/{name}", sha256, name)


VR2TE = [
    _vr2te("vr2te-en", "VR2TE Super, international (English)", "1.22S", "A36Plus-EN-V1.22-Super.bin",
           "c91f3fb5724c154747a7df26cc1b71f0b97a69a776c901e5586002550d2fe0ed"),
    _vr2te("vr2te-gmrs", "VR2TE Super, GMRS (English)", "1.20S", "A36plus-GMRS-V1.20-Super.bin",
           "646a30c0035bcc1bdcaf7007398debb4b04a8335b3a1d5c55fca06b9e1930cb4",
           summary="The same research build, from Talkpod's US GMRS firmware."),
]


def _trusted(url):
    return (url.startswith(f"https://github.com/{TSF_REPO}/releases/download/")
            or url.startswith(f"https://raw.githubusercontent.com/{VR2TE_REPO}/{VR2TE_COMMIT}/"))


def _get(url, timeout=20, limit=MAX_BYTES, accept=None, progress=None):
    headers = {"User-Agent": f"talkpod-manager/{__version__}"}
    if accept:
        headers["Accept"] = accept
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=timeout) as r:
        total = int(r.headers.get("Content-Length") or 0)
        data = b""
        while chunk := r.read(16 * 1024):
            data += chunk
            if len(data) > limit:
                raise CatalogError(f"{url} is bigger than any firmware for this radio; not using it.")
            if progress and total:
                progress(len(data) / total)
    return data


def latest_tsf(timeout=10):
    """The newest Talkpod Super Firmware release, or the copy that ships with the app when GitHub
    can't be reached, only has older releases, or the release has no usable firmware file."""
    try:
        rel = json.loads(_get(f"https://api.github.com/repos/{TSF_REPO}/releases/latest", timeout,
                              limit=1024 * 1024, accept="application/vnd.github+json"))
        if parse_version(rel["tag_name"]) < parse_version(TSF.version):
            return TSF                          # GitHub has only older releases
        for a in rel.get("assets", []):
            digest = a.get("digest") or ""
            if a["name"].endswith(".kdhx") and digest.startswith("sha256:") and _trusted(a["browser_download_url"]):
                return replace(TSF, version=rel["tag_name"].lstrip("v"), url=a["browser_download_url"],
                               sha256=digest.split(":", 1)[1].lower(), filename=a["name"],
                               bundled=TSF.bundled if digest.endswith(TSF.sha256) else "")
        LOG.info("latest Talkpod Super Firmware release has no checked .kdhx; offering %s", TSF.version)
    except (OSError, ValueError, KeyError, CatalogError) as e:
        LOG.info("couldn't check for Talkpod Super Firmware releases: %s", e)
    return TSF


def builds():
    """What the app offers, without going online (latest_tsf() can replace the first entry)."""
    return [TSF] + VR2TE


def _cache():
    d = paths.state_dir() / "firmware"
    d.mkdir(exist_ok=True)
    return d


def fetch(build, progress=None):
    """The build's file as an Image: from the app, the download cache or its author's GitHub. Raises
    CatalogError unless it matches the build's SHA-256."""
    def good(data):
        return hashlib.sha256(data).hexdigest() == build.sha256

    if build.bundled:
        data = resources.files("talkpod_manager").joinpath("data", "firmware", build.bundled).read_bytes()
        if good(data):
            return Image(data, build.filename)
    cached = _cache() / build.filename
    if cached.exists() and good(cached.read_bytes()):
        return Image(cached.read_bytes(), build.filename)
    if not _trusted(build.url):
        raise CatalogError(f"Not downloading firmware from {build.url}.")
    try:
        data = _get(build.url, progress=progress)
    except OSError as e:
        raise CatalogError(f"Couldn't download {build.title} {build.version}: {e}. Check the internet "
                           "connection, or download it from its page and flash it as a file.") from e
    if not good(data):
        raise CatalogError(f"The download of {build.title} {build.version} isn't the file this app knows "
                           f"(its checksum differs), so it won't be flashed. See {build.page}.")
    cached.write_bytes(data)
    LOG.info("downloaded %s (%d bytes)", build.filename, len(data))
    return Image(data, build.filename)
