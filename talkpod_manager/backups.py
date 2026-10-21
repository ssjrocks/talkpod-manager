"""Radio image backups: one is saved automatically before every write to the radio."""

import datetime as dt
import re
from pathlib import Path

from . import paths
from .channels import used_count
from .radio import load_image

NAME_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})_(\d{6})_(.+)\.img$")


class Backup:
    def __init__(self, path: Path):
        self.path = path
        m = NAME_RE.match(path.name)
        if m:
            self.when = dt.datetime.strptime(m.group(1) + m.group(2), "%Y-%m-%d%H%M%S")
            self.label = m.group(3).replace("-", " ")
        else:
            self.when = dt.datetime.fromtimestamp(path.stat().st_mtime)
            self.label = path.stem

    def channels(self):
        try:
            return used_count(load_image(self.path))
        except Exception:
            return None


def slug(text):
    return re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-").lower() or "backup"


def save(radio, label, folder=None):
    folder = Path(folder) if folder else paths.backups_dir()
    folder.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y-%m-%d_%H%M%S")
    path = folder / f"{stamp}_{slug(label)}.img"
    n = 1
    while path.exists():
        n += 1
        path = folder / f"{stamp}_{slug(label)}-{n}.img"
    radio.save_mmap(str(path))
    return path


def list_all(folder=None):
    folder = Path(folder) if folder else paths.backups_dir()
    items = [Backup(p) for p in folder.glob("*.img")]
    items.sort(key=lambda b: b.when, reverse=True)
    return items
