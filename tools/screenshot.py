#!/usr/bin/env python3
"""Render the app's pages to PNGs for checking the UI (development tool).

Usage: tools/screenshot.py IMAGE.img OUT_DIR [PICTURE]   (PICTURE: shown on the Boot logo page)
Run it on a virtual X display to keep windows off the desktop:
  GDK_BACKEND=x11 xvfb-run -s "-screen 0 1400x1000x24" tools/screenshot.py ...
State and backups go to a temporary folder; nothing touches a radio.
"""

import os
import sys
import tempfile
from pathlib import Path

IMAGE, OUT = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
PICTURE = Path(sys.argv[3]).resolve() if len(sys.argv) > 3 else None
OUT.mkdir(parents=True, exist_ok=True)
tmp = Path(tempfile.mkdtemp(prefix="tpm-shot-"))
os.environ["XDG_STATE_HOME"] = str(tmp / "state")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from talkpod_manager import appreports, paths, updater  # noqa: E402

appreports.init = lambda *a, **k: None  # test runs must not send error reports
paths.backups_dir = lambda: (tmp / "backups").mkdir(exist_ok=True) or tmp / "backups"
updater.due = lambda: False

from talkpod_manager.app import App  # noqa: E402
from gi.repository import GLib, Graphene, Gtk  # noqa: E402


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


class ShotApp(App):
    def do_activate(self):
        App.do_activate(self)
        win = self.get_active_window()
        win.set_default_size(1200, 820)
        steps = [
            lambda: capture(win, "0-empty"),
            lambda: win.open_image(str(IMAGE)),
            lambda: capture(win, "1-channels"),
            lambda: win.edit_channel(101),
            lambda: capture(win, "2-edit-channel"),
            lambda: win.get_visible_dialog() and win.get_visible_dialog().close(),
            lambda: win.stack.set_visible_child_name("settings"),
            lambda: capture(win, "3-settings"),
            lambda: win.stack.set_visible_child_name("logo"),
            lambda: PICTURE and (setattr(win.logo_page, "path", str(PICTURE)), win.logo_page._render(), win._sync()) and None,
            lambda: capture(win, "4-logo"),
            lambda: win.plan(),
            lambda: capture(win, "5-plan"),
            lambda: win.get_visible_dialog() and win.get_visible_dialog().close(),
            lambda: win.stack.set_visible_child_name("backups"),
            lambda: capture(win, "6-backups"),
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


sys.exit(ShotApp().run([sys.argv[0]]))
