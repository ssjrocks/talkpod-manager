#!/usr/bin/env python3
"""Render the app's pages to PNGs for checking the UI (development tool).

Usage: tools/screenshot.py IMAGE.img OUT_DIR [PICTURE [ANIMATION [SUPER_VERSION]]]
       (PICTURE: shown on the Boot logo page; ANIMATION: on the Boot splash page; SUPER_VERSION: show
       the pages as they are for a radio running that Talkpod Super Firmware)
Run it on a virtual X display to keep windows off the desktop:
  GDK_BACKEND=x11 xvfb-run -s "-screen 0 1400x1000x24" tools/screenshot.py ...
State and backups go to a temporary folder; nothing touches a radio. tools/screenshots.sh runs it for the
README, with the pictures in tools/screenshot-data.
"""

import faulthandler
import os
import shutil
import sys
import tempfile
from pathlib import Path

IMAGE, OUT = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
PICTURE = Path(sys.argv[3]).resolve() if len(sys.argv) > 3 else None
ANIMATION = Path(sys.argv[4]).resolve() if len(sys.argv) > 4 else None
SUPER = sys.argv[5] if len(sys.argv) > 5 else None
OUT.mkdir(parents=True, exist_ok=True)
tmp = Path(tempfile.mkdtemp(prefix="tpm-shot-"))
os.environ["XDG_STATE_HOME"] = str(tmp / "state")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

faulthandler.dump_traceback_later(120, exit=True)  # a hung run ends by itself

from talkpod_manager import appreports, paths, radio as rio, updater  # noqa: E402

appreports.init = lambda *a, **k: None  # test runs must not send error reports
paths.backups_dir = lambda: (tmp / "backups").mkdir(exist_ok=True) or tmp / "backups"
updater.due = lambda: False

from talkpod_manager.app import App  # noqa: E402
from gi.repository import Gio, GLib, Graphene, Gtk  # noqa: E402


def capture(widget, name):
    """False when the window hasn't been drawn yet (the step is retried)."""
    w, h = widget.get_width(), widget.get_height()
    snap = Gtk.Snapshot()
    Gtk.WidgetPaintable.new(widget).snapshot(snap, w, h)
    node = snap.to_node()
    if not w or not h or node is None:
        return False
    tex = widget.get_native().get_renderer().render_texture(node, Graphene.Rect().init(0, 0, w, h))
    path = OUT / f"{name}.png"
    tex.save_to_png(str(path))
    print("saved", path, flush=True)


def as_super(win, version):
    fw = rio.Firmware(rio.CUSTOM_FIRMWARE_PREFIX + b"02", version)
    win.set_radio(win.radio, f"Read from the radio ({fw.name})", firmware=fw)


class ShotApp(App):
    def __init__(self):
        super().__init__()
        self.set_flags(self.get_flags() | Gio.ApplicationFlags.NON_UNIQUE)  # or it hands over to a running copy

    def do_activate(self):
        App.do_activate(self)
        win = self.get_active_window()
        win.set_default_size(1200, 820)
        steps = [
            lambda: capture(win, "0-empty"),
            lambda: win.open_image(str(IMAGE)),
            lambda: SUPER and as_super(win, SUPER),
            lambda: capture(win, "1-channels"),
            lambda: win.set_default_size(1200, 1180),
            lambda: win.edit_channel(101),
            lambda: win.get_visible_dialog().set_content_height(1100),
            lambda: capture(win, "2-edit-channel"),
            lambda: win.get_visible_dialog() and win.get_visible_dialog().close(),
            lambda: win.set_default_size(1200, 820),
            lambda: win.stack.set_visible_child_name("settings"),
            lambda: capture(win, "3-settings"),
            lambda: win.stack.set_visible_child_name("logo"),
            lambda: PICTURE and (setattr(win.logo_page, "path", str(PICTURE)), win.logo_page._render(), win._sync()) and None,
            lambda: capture(win, "4-logo"),
            lambda: win.stack.set_visible_child_name("splash"),
            lambda: ANIMATION and win.splash_page.load(str(ANIMATION)) and None,
            lambda: None if not ANIMATION else (win.splash_page.splash is not None or False),   # built on a thread
            lambda: capture(win, "4-splash"),
            lambda: win.set_default_size(1200, 1640),
            lambda: capture(win, "4-splash-full"),
            lambda: win.set_default_size(1200, 820),
            lambda: win.stack.set_visible_child_name("channels"),
            lambda: win.plan(),
            lambda: capture(win, "5-plan"),
            lambda: win.get_visible_dialog() and win.get_visible_dialog().close(),
            lambda: win.stack.set_visible_child_name("backups"),
            lambda: capture(win, "6-backups"),
            lambda: win.flash_firmware(),
            lambda: capture(win, "7-firmware"),
            lambda: win.get_visible_dialog() and win.get_visible_dialog().close(),
            lambda: self.quit(),
        ]

        tries = {"n": 0}

        def run_next():
            if not steps:
                return False
            try:
                ok = steps[0]()
            except Exception as e:
                print("step failed:", repr(e), flush=True)
                ok = None
            if ok is False and tries["n"] < 20:
                tries["n"] += 1
                return True
            tries["n"] = 0
            steps.pop(0)
            return True

        # give each action time to draw (dialogs animate in) before the next capture
        waited = []
        for step in steps:
            waited += [step, lambda: None, lambda: None]
        steps[:] = waited
        GLib.timeout_add(500, run_next)


code = ShotApp().run([sys.argv[0]])
shutil.rmtree(tmp, ignore_errors=True)
sys.exit(code)
