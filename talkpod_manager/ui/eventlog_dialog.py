"""Event log: every reading of Talkpod Super Firmware's receiver event log (eventlog.py), kept across runs,
in one text field with what each line means on hover."""

import logging

from gi.repository import Adw, GLib, Gtk, Pango

from .. import appreports, eventlog
from .. import radio as rio
from . import worker

LOG = logging.getLogger(__name__)

INTRO = ("Each reading of the radio's receiver event log, oldest first, with when it was read and when each event "
         "happened, in this computer's time zone. Read it right after something odd happens, without switching "
         "the radio off: that clears it. Hover over a line for what it means. Needs Talkpod Super Firmware 1.22 "
         "or later and the programming cable.")
EMPTY = "No event logs read yet. Plug in the cable with the radio still on, then press the read button (top left)."


class EventLogDialog(Adw.Dialog):
    def __init__(self, window, report=None):
        """report: a reading to add first (eventlog.Report), as if just read from the radio."""
        super().__init__(title="Event log", content_width=860, content_height=800)
        self.win = window
        self.busy = False
        self.tips = []                  # what each line of the text means, or None

        header = Adw.HeaderBar()
        self.read_btn = Gtk.Button(icon_name="view-refresh-symbolic", tooltip_text="Read the log from the radio")
        self.read_btn.connect("clicked", lambda _b: self._read())
        header.pack_start(self.read_btn)
        self.delete_btn = Gtk.Button(icon_name="user-trash-symbolic", tooltip_text="Delete the saved logs")
        self.delete_btn.connect("clicked", lambda _b: self._confirm_delete())
        header.pack_end(self.delete_btn)
        self.clear_btn = Gtk.Button(icon_name="edit-clear-all-symbolic", tooltip_text="Clear the log on the radio")
        self.clear_btn.connect("clicked", lambda _b: self._confirm_clear())
        header.pack_end(self.clear_btn)
        self.copy_btn = Gtk.Button(icon_name="edit-copy-symbolic", tooltip_text="Copy all the logs as text")
        self.copy_btn.connect("clicked", lambda _b: self._copy())
        header.pack_end(self.copy_btn)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_top=12, margin_bottom=12,
                      margin_start=12, margin_end=12)
        intro = Gtk.Label(label=INTRO, wrap=True, xalign=0)
        intro.add_css_class("dim-label")
        box.append(intro)
        self.view = Gtk.TextView(editable=False, cursor_visible=False, monospace=True, has_tooltip=True,
                                 wrap_mode=Gtk.WrapMode.WORD_CHAR, top_margin=8, bottom_margin=8, left_margin=8,
                                 right_margin=8)
        self.view.connect("query-tooltip", self._tooltip)
        self.bold = self.view.get_buffer().create_tag("header", weight=Pango.Weight.BOLD)
        scroll = Gtk.ScrolledWindow(vexpand=True, child=self.view)
        scroll.add_css_class("card")
        self.scroll = scroll
        box.append(scroll)

        view = Adw.ToolbarView()
        view.add_top_bar(header)
        view.set_content(box)
        self.set_child(view)
        self.reports = eventlog.keep(report) if report else eventlog.load()
        self._render()

    # --- showing ---------------------------------------------------------------------------------

    def _render(self):
        buf = self.view.get_buffer()
        buf.set_text("")
        self.tips = []
        if not self.reports:
            buf.set_text(EMPTY)
            self.tips = [None]
        for n, report in enumerate(self.reports):
            if n:
                buf.insert(buf.get_end_iter(), "\n")
                self.tips.append(None)
            for i, (text, tip) in enumerate(report.lines()):
                if n or i:
                    buf.insert(buf.get_end_iter(), "\n")
                if i == 0:
                    buf.insert_with_tags(buf.get_end_iter(), text, self.bold)
                else:
                    buf.insert(buf.get_end_iter(), text)
                self.tips.append(tip)
        GLib.idle_add(self._scroll_to_end)
        self._update()

    def _scroll_to_end(self):
        adj = self.scroll.get_vadjustment()
        adj.set_value(adj.get_upper() - adj.get_page_size())
        return False

    def _tooltip(self, view, x, y, keyboard, tooltip):
        if keyboard:
            return False
        bx, by = view.window_to_buffer_coords(Gtk.TextWindowType.WIDGET, x, y)
        found, it = view.get_iter_at_location(bx, by)
        line = it.get_line() if found else -1
        tip = self.tips[line] if 0 <= line < len(self.tips) else None
        if not tip:
            return False
        tooltip.set_text(tip)
        return True

    def _update(self):
        idle = not self.busy and not self.win.busy
        self.read_btn.set_sensitive(idle)
        self.clear_btn.set_sensitive(idle)
        self.copy_btn.set_sensitive(bool(self.reports))
        self.delete_btn.set_sensitive(bool(self.reports))

    def text(self):
        """All the saved logs as plain text."""
        return "\n\n".join("\n".join(text for text, _tip in r.lines()) for r in self.reports) + "\n"

    def _copy(self):
        self.get_clipboard().set(self.text())
        self.win.toast("Event logs copied")

    # --- the radio and the saved logs ------------------------------------------------------------

    def _alert(self, heading, body):
        d = Adw.AlertDialog(heading=heading, body=body)
        d.add_response("ok", "OK")
        d.present(self)

    def _confirm(self, heading, body, action, fn):
        d = Adw.AlertDialog(heading=heading, body=body)
        d.add_response("cancel", "Cancel")
        d.add_response("go", action)
        d.set_response_appearance("go", Adw.ResponseAppearance.DESTRUCTIVE)
        d.connect("response", lambda _d, r: fn() if r == "go" else None)
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
        def job(port):
            report = eventlog.read(port)
            return report, eventlog.keep(report)

        self._run(job, self._read_done, "Reading the event log")

    def _read_done(self, result):
        report, self.reports = result
        self._render()
        self.win.toast(f"Event log read: {len(report.events)} events")

    def _confirm_clear(self):
        self._confirm("Clear the radio's event log?",
                      "The radio starts a new log. The logs saved here stay.", "Clear",
                      lambda: self._run(eventlog.clear, lambda _r: self.win.toast("The radio's event log is cleared"),
                                        "Clearing the event log"))

    def _confirm_delete(self):
        def delete():
            eventlog.save([])
            self.reports = []
            self._render()

        self._confirm("Delete the saved event logs?",
                      f"All {len(self.reports)} logs read so far are deleted from this computer. The radio's own "
                      "log isn't touched.", "Delete", delete)

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
