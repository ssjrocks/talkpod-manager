"""Event log: Talkpod Super Firmware's receiver events (eventlog.py), newest first, each explained on hover."""

import datetime as dt
import logging

from gi.repository import Adw, Gtk

from .. import appreports, eventlog
from .. import radio as rio
from . import worker

LOG = logging.getLogger(__name__)

INTRO = ("The radio's last 128 receiver events, newest first. Read it right after something odd happens, without "
         "switching the radio off: that clears it. Hover over an event for what it means. Needs Talkpod Super "
         "Firmware 1.22 or later and the programming cable.")


def _icon(event):
    """An icon for the events that explain a silence, none for the rest."""
    if event.name == "HOLD":
        return "audio-volume-muted-symbolic" if event.a else "audio-volume-high-symbolic"
    if event.name in ("PKT_LOST", "CARRIER") and (event.name == "PKT_LOST" or event.a):
        return "dialog-warning-symbolic"
    if event.name == "TX":
        return "microphone-sensitivity-high-symbolic"
    return None


def _ago(ms):
    s = ms / 1000
    if s < 60:
        return f"{s:.1f} s before reading"
    return f"{int(s // 60)} min {int(s % 60)} s before reading"


class EventLogDialog(Adw.Dialog):
    def __init__(self, window, log=None):
        """log: (radio ms, PC time, events) to show, as eventlog.read() returns it; None to read it."""
        super().__init__(title="Event log", content_width=720, content_height=780)
        self.win = window
        self.log = None
        self.busy = False

        header = Adw.HeaderBar()
        self.read_btn = Gtk.Button(icon_name="view-refresh-symbolic", tooltip_text="Read the log from the radio")
        self.read_btn.connect("clicked", lambda _b: self._read())
        header.pack_start(self.read_btn)
        self.clear_btn = Gtk.Button(icon_name="edit-clear-all-symbolic", tooltip_text="Clear the log on the radio")
        self.clear_btn.connect("clicked", lambda _b: self._confirm_clear())
        header.pack_end(self.clear_btn)
        self.copy_btn = Gtk.Button(icon_name="edit-copy-symbolic", tooltip_text="Copy the log as text")
        self.copy_btn.connect("clicked", lambda _b: self._copy())
        header.pack_end(self.copy_btn)

        view = Adw.ToolbarView()
        view.add_top_bar(header)
        self.page = Adw.PreferencesPage()
        view.set_content(self.page)
        self.set_child(view)
        self.page.add(Adw.PreferencesGroup(description=INTRO))
        self.group = None
        self._show(log)

    # --- showing ---------------------------------------------------------------------------------

    def _show(self, log):
        self.log = log
        if self.group is not None:
            self.page.remove(self.group)
        self.group = Adw.PreferencesGroup()
        if log is None:
            row = Adw.ActionRow(title="Not read yet", subtitle="Plug in the cable with the radio still on, then Read.")
            read = Gtk.Button(label="Read", valign=Gtk.Align.CENTER)
            read.add_css_class("suggested-action")
            read.connect("clicked", lambda _b: self._read())
            row.add_suffix(read)
            self.group.add(row)
        else:
            now, read_at, events = log
            if not events:
                self.group.set_title("The log is empty")
            else:
                first = dt.datetime.fromtimestamp(read_at - (now - events[0].ms) / 1000)
                self.group.set_title(f"{len(events)} events since {first:%H:%M:%S}, read at "
                                     f"{dt.datetime.fromtimestamp(read_at):%H:%M:%S}")
            for e in reversed(events):
                at = dt.datetime.fromtimestamp(read_at - (now - e.ms) / 1000)
                row = Adw.ActionRow(title=e.summary(), subtitle=f"{at:%H:%M:%S}, {_ago(now - e.ms)}",
                                    tooltip_text=e.description(), activatable=False)
                icon = _icon(e)
                if icon:
                    row.add_prefix(Gtk.Image(icon_name=icon))
                self.group.add(row)
        self.page.add(self.group)
        self._update()

    def _update(self):
        idle = not self.busy and not self.win.busy
        self.read_btn.set_sensitive(idle)
        self.clear_btn.set_sensitive(idle and bool(self.log and self.log[2]))
        self.copy_btn.set_sensitive(bool(self.log and self.log[2]))

    def text(self):
        """The log as plain text, newest last, as the radio sent it."""
        now, read_at, events = self.log
        out = []
        for e in events:
            at = dt.datetime.fromtimestamp(read_at - (now - e.ms) / 1000)
            out.append(f"{at:%H:%M:%S.%f}"[:12] + f"  {e.summary()}")
        return "\n".join(out) + "\n"

    def _copy(self):
        self.get_clipboard().set(self.text())
        self.win.toast("Event log copied")

    # --- the radio -------------------------------------------------------------------------------

    def _alert(self, heading, body):
        d = Adw.AlertDialog(heading=heading, body=body)
        d.add_response("ok", "OK")
        d.present(self)

    def _run(self, job, done, what):
        port = self.win.port()
        if not port:
            self._alert("No cable", "Plug the programming cable into the PC and the radio. Keep the radio switched "
                                    "on: switching it off clears the log.")
            return
        self.busy = True
        self.win.set_busy(True, what)
        self._update()
        worker.run(lambda p: job(port), lambda r: self._finish(done, r), self._failed)

    def _finish(self, done, result):
        self.busy = False
        self.win.set_busy(False)
        done(result)
        self._update()

    def _read(self):
        self._run(eventlog.read, self._show, "Reading the event log")

    def _confirm_clear(self):
        d = Adw.AlertDialog(heading="Clear the radio's event log?",
                            body="The radio starts a new log. What it has now is gone, unless you copied it.")
        d.add_response("cancel", "Cancel")
        d.add_response("clear", "Clear")
        d.set_response_appearance("clear", Adw.ResponseAppearance.DESTRUCTIVE)
        d.connect("response", lambda _d, r: self._run(eventlog.clear, lambda _r: self._show(None), "Clearing the "
                                                      "event log") if r == "clear" else None)
        d.present(self)

    def _failed(self, e):
        self.busy = False
        self.win.set_busy(False)
        self._update()
        if isinstance(e, rio.RadioError):
            self._alert("No event log", str(e))
        else:
            LOG.exception("event log failed", exc_info=e)
            appreports.report_error(e, "event log")
            self._alert("Something went wrong", f"{type(e).__name__}: {e}\n\nA report has been sent.")
