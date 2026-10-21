"""Updates from the project's GitHub releases.

Each release carries the wheel and talkpod-manager.json ({"version", "wheel", "sha256"}). The
wheel must come from github.com, match the checksum, and is installed with pip into the venv the
app runs from (the one scripts/install.sh made). Running from a source checkout, the app only
reports that an update exists.
"""

import hashlib
import json
import logging
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from . import REPO, __version__, paths

LOG = logging.getLogger(__name__)

API = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{REPO}/releases"
INFO_ASSET = "talkpod-manager.json"
CHECK_EVERY = 12 * 3600


class Update:
    def __init__(self, version, wheel_url, wheel_name, sha256, notes, published):
        self.version = version
        self.wheel_url = wheel_url
        self.wheel_name = wheel_name
        self.sha256 = sha256
        self.notes = notes
        self.published = published


def parse_version(v):
    parts = []
    for p in v.lstrip("v").split("."):
        digits = "".join(c for c in p if c.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def _get(url, timeout=20):
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json",
                                               "User-Agent": f"talkpod-manager/{__version__}"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _trusted(url):
    return url.startswith(f"https://github.com/{REPO}/releases/download/")


def check():
    """The latest release if it's newer than this version, else None."""
    rel = json.loads(_get(API))
    assets = {a["name"]: a for a in rel.get("assets", [])}
    info_asset = assets.get(INFO_ASSET)
    if not info_asset or not _trusted(info_asset["browser_download_url"]):
        return None
    info = json.loads(_get(info_asset["browser_download_url"]))
    if parse_version(info["version"]) <= parse_version(__version__):
        return None
    wheel = assets.get(info["wheel"])
    if not wheel or not _trusted(wheel["browser_download_url"]):
        return None
    return Update(info["version"], wheel["browser_download_url"], info["wheel"], info["sha256"].lower(),
                  rel.get("body") or "", rel.get("published_at") or "")


def _state_file():
    return paths.state_dir() / "update.json"


def due():
    try:
        last = json.loads(_state_file().read_text()).get("checked_at", 0)
    except (OSError, ValueError):
        last = 0
    return time.time() - last > CHECK_EVERY


def mark_checked():
    _state_file().write_text(json.dumps({"checked_at": time.time()}))


def installed_in_venv():
    """True when running from the venv scripts/install.sh made (so pip can update it)."""
    return sys.prefix != sys.base_prefix and (Path(sys.prefix) / "talkpod-manager-venv").exists()


def install(update, progress=None):
    """Download, verify and pip-install the update. Raises on any failure."""
    if not installed_in_venv():
        raise RuntimeError(f"This copy runs from source; update it with git, or get {update.version} from {RELEASES_PAGE}")
    folder = paths.state_dir() / "updates"
    folder.mkdir(exist_ok=True)
    path = folder / update.wheel_name
    req = urllib.request.Request(update.wheel_url, headers={"User-Agent": f"talkpod-manager/{__version__}"})
    h = hashlib.sha256()
    with urllib.request.urlopen(req, timeout=60) as r, open(path, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        while chunk := r.read(64 * 1024):
            f.write(chunk)
            h.update(chunk)
            done += len(chunk)
            if progress and total:
                progress(done / total)
    if h.hexdigest() != update.sha256:
        path.unlink(missing_ok=True)
        raise RuntimeError("The download didn't match its checksum; nothing was installed.")
    # Dependencies are resolved too, so a release that moves the CHIRP pin brings the new CHIRP along.
    out = subprocess.run([sys.executable, "-m", "pip", "install", str(path)], capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError(f"pip couldn't install the update:\n{out.stderr[-2000:]}")
    LOG.info("installed update %s", update.version)


def sync_desktop_files():
    """Refresh the desktop entry and icon install.sh copied, after an update changed them.

    Only touches files that already exist (installed copies), keeping their Exec line.
    """
    data = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share")
    pkg = Path(__file__).parent / "data"
    from . import APP_ID

    desktop = data / "applications" / f"{APP_ID}.desktop"
    if desktop.exists():
        current = desktop.read_text()
        exec_line = next((ln for ln in current.splitlines() if ln.startswith("Exec=")), None)
        new = (pkg / f"{APP_ID}.desktop").read_text()
        if exec_line:
            new = "\n".join(exec_line if ln.startswith("Exec=") else ln for ln in new.splitlines()) + "\n"
        if new != current:
            desktop.write_text(new)
            LOG.info("updated %s", desktop)
    icon = data / "icons/hicolor/scalable/apps" / f"{APP_ID}.svg"
    src = pkg / "icons/hicolor/scalable/apps" / f"{APP_ID}.svg"
    if icon.exists() and icon.read_bytes() != src.read_bytes():
        icon.write_bytes(src.read_bytes())
        LOG.info("updated %s", icon)


def restart():
    os.execv(sys.executable, [sys.executable, "-m", "talkpod_manager"] + sys.argv[1:])
