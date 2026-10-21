"""Run blocking work (serial I/O, downloads) off the GTK main thread."""

import logging
import threading

from gi.repository import GLib

LOG = logging.getLogger(__name__)


def run(fn, on_done, on_error, on_progress=None):
    """fn(progress) runs on a thread; progress(fraction, text) and the callbacks run on the main loop."""

    def progress(fraction, text=""):
        if on_progress:
            GLib.idle_add(on_progress, fraction, text)

    def target():
        try:
            result = fn(progress)
        except Exception as e:  # handed to the UI, which reports unexpected ones
            LOG.info("background task failed: %r", e)
            GLib.idle_add(on_error, e)
        else:
            GLib.idle_add(on_done, result)

    threading.Thread(target=target, name="radio-io", daemon=True).start()
