"""Where the app keeps its files (XDG locations)."""

import os
from pathlib import Path


def _xdg(var, default):
    value = os.environ.get(var)
    return Path(value) if value else Path.home() / default


def state_dir() -> Path:
    """Logs, pending error reports, update-check state."""
    d = _xdg("XDG_STATE_HOME", ".local/state") / "talkpod-manager"
    d.mkdir(parents=True, exist_ok=True)
    return d


def documents_dir() -> Path:
    try:
        from gi.repository import GLib

        d = GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_DOCUMENTS)
        if d:
            return Path(d)
    except Exception:
        pass
    return Path.home() / "Documents"


def backups_dir() -> Path:
    """Radio images: automatic ones taken before every write, plus manual saves."""
    d = documents_dir() / "Talkpod Manager" / "Backups"
    d.mkdir(parents=True, exist_ok=True)
    return d


def log_file() -> Path:
    return state_dir() / "talkpod-manager.log"
