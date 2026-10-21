"""Application entry point."""

import logging
import logging.handlers
import sys
from pathlib import Path

from . import ui  # noqa: F401  (gi version requirements)
from gi.repository import Adw, Gdk, Gio, Gtk

from . import APP_ID, APP_NAME, REPO, __version__, appreports, paths, updater
from .ui.window import MainWindow

LOG = logging.getLogger("talkpod_manager")


def version_code(version):
    parts = [int(p) for p in version.split(".")[:3]] + [0, 0, 0]
    return parts[0] * 10000 + parts[1] * 100 + parts[2]


def setup_logging():
    handler = logging.handlers.RotatingFileHandler(paths.log_file(), maxBytes=512 * 1024, backupCount=1,
                                                   encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    if sys.stderr and sys.stderr.isatty():
        root.addHandler(logging.StreamHandler())
    logging.getLogger("chirp").setLevel(logging.WARNING)


class App(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.HANDLES_OPEN)

    def do_startup(self):
        Adw.Application.do_startup(self)
        setup_logging()
        LOG.info("%s %s starting", APP_NAME, __version__)
        # The icon ships inside the package, so it shows even when running from a checkout.
        theme = Gtk.IconTheme.get_for_display(Gdk.Display.get_default())
        theme.add_search_path(str(Path(__file__).parent / "data" / "icons"))
        appreports.init(APP_ID, APP_NAME, __version__, paths.state_dir(), log_file=paths.log_file(),
                        version_code=version_code(__version__))
        if updater.installed_in_venv():
            try:
                updater.sync_desktop_files()
            except OSError:
                LOG.exception("couldn't refresh the desktop entry")
        for name, fn, accels in [
            ("about", self.about, []),
            ("quit", lambda: self.get_active_window() and self.get_active_window().close(), ["<Control>q"]),
        ]:
            a = Gio.SimpleAction(name=name)
            a.connect("activate", lambda _a, _p, fn=fn: fn())
            self.add_action(a)
            if accels:
                self.set_accels_for_action(f"app.{name}", accels)

    def do_activate(self):
        win = self.get_active_window() or MainWindow(self)
        win.present()

    def do_open(self, files, _n, _hint):
        self.do_activate()
        win = self.get_active_window()
        for f in files:
            if f.get_path() and f.get_path().endswith(".img"):
                win.confirm_discard(lambda p=f.get_path(): win.open_image(p))
                break

    def about(self):
        d = Adw.AboutDialog(
            application_name=APP_NAME,
            application_icon=APP_ID,
            version=__version__,
            developer_name="ssjrocks",
            comments="Program, configure and back up Talkpod A36SE and A36plus radios.",
            website=f"https://github.com/{REPO}",
            issue_url=f"https://github.com/{REPO}/issues",
            license_type=Gtk.License.GPL_3_0,
        )
        d.add_credit_section("Radio driver", ["CHIRP https://chirpmyradio.com"])
        d.present(self.get_active_window())


def main():
    return App().run(sys.argv)
