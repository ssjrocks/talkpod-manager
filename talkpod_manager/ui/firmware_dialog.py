"""Flash firmware: ready-to-flash builds (firmware_catalog) or any .kdhx file, plus links to
Talkpod's own firmware downloads."""

import logging
from urllib.parse import urlparse

from gi.repository import Adw, Gio, GLib, Gtk, Pango

from .. import appreports, firmware, firmware_catalog
from .. import radio as rio
from . import worker

LOG = logging.getLogger(__name__)

BEFORE = [
    ("Firmware can't be read back",
     "There's no copy of what the radio runs now. Channels and settings normally survive a firmware change; "
     "save a backup (Read, then Backups) anyway."),
    ("Keep the cable in and the radio on until it's done",
     "If flashing is interrupted, the bootloader itself is untouched: switch the radio on holding both side keys "
     "(white screen), turn on bootloader mode above and flash again."),
    ("A36plus 5 W / A36SE firmware only",
     "Files that aren't A36plus firmware, and 8 W / MAX firmware, are refused before anything is sent."),
]


def _open_uri(widget, uri):
    Gtk.UriLauncher(uri=uri).launch(widget.get_root(), None, None, None)


def _link_button(uri, tooltip):
    b = Gtk.Button(icon_name="adw-external-link-symbolic", valign=Gtk.Align.CENTER, tooltip_text=tooltip)
    b.add_css_class("flat")
    b.connect("clicked", lambda btn: _open_uri(btn, uri))
    return b


class FirmwareDialog(Adw.Dialog):
    def __init__(self, window):
        super().__init__(title="Flash firmware", content_width=680, content_height=780)
        self.win = window
        self.builds = firmware_catalog.builds()
        self.file_image = None
        self.flashing = False

        view = Adw.ToolbarView()
        view.add_top_bar(Adw.HeaderBar())
        page = Adw.PreferencesPage()
        view.set_content(page)
        self.set_child(view)

        g = Adw.PreferencesGroup(
            title="Firmware",
            description="Ready to flash. Each one is downloaded from its author's GitHub and checked against its "
                        "checksum before it's sent to the radio.")
        page.add(g)
        self.choices, group = [], None
        for build in self.builds:
            row, check = self._choice(build.title + " " + build.version, build.summary, group)
            row.add_suffix(_link_button(build.page, f"Open {urlparse(build.page).netloc + urlparse(build.page).path}"))
            group = group or check
            g.add(row)
            self.choices.append((row, check))
        self.file_row, self.file_check = self._choice(
            "A firmware file", "A .kdhx file, e.g. stock firmware unpacked from Talkpod's download", group)
        self.file_label = Gtk.Label(ellipsize=Pango.EllipsizeMode.MIDDLE, max_width_chars=18)
        self.file_label.add_css_class("dim-label")
        choose = Gtk.Button(label="Choose…", valign=Gtk.Align.CENTER)
        choose.connect("clicked", self._choose)
        self.file_row.add_suffix(self.file_label)
        self.file_row.add_suffix(choose)
        g.add(self.file_row)

        g = Adw.PreferencesGroup(title="Stock firmware")
        page.add(g)
        row = Adw.ActionRow(
            title="Talkpod's firmware downloads",
            subtitle="Official A36plus 5 W / A36SE builds (international, GMRS, PMR) as .zip or .rar files: unpack "
                     "one and flash the .kdhx inside as a file. The page also has the Windows tools and a guide for "
                     "a radio that won't start.")
        row.add_suffix(_link_button(firmware_catalog.STOCK_PAGE, "Open talkpodonline.com"))
        g.add(row)
        row = Adw.ActionRow(title="Talkpod's support page", subtitle="talkpod.com's firmware and software list")
        row.add_suffix(_link_button(firmware_catalog.STOCK_PAGE_ALT, "Open talkpod.com"))
        g.add(row)
        row = Adw.ActionRow(
            title="Australian UHF CB radios",
            subtitle="These run a build Talkpod doesn't publish. Once it's replaced, the CB-only version can't be "
                     "put back.", activatable=False)
        row.add_prefix(Gtk.Image(icon_name="dialog-warning-symbolic"))
        g.add(row)

        g = Adw.PreferencesGroup(title="Flash")
        page.add(g)
        self.selected_row = Adw.ActionRow(title="Selected", subtitle_lines=3)
        g.add(self.selected_row)
        self.manual_row = Adw.SwitchRow(
            title="The radio shows the white bootloader screen",
            subtitle="Only if a normal flash didn't work: switch the radio on while holding both side keys first")
        g.add(self.manual_row)
        self.progress = Gtk.ProgressBar(show_text=True, valign=Gtk.Align.CENTER, hexpand=True)
        self.progress_row = Adw.ActionRow(visible=False, activatable=False)
        self.progress_row.add_suffix(self.progress)
        g.add(self.progress_row)
        self.flash_btn = Adw.ButtonRow(title="Flash to radio")
        self.flash_btn.add_css_class("destructive-action")
        self.flash_btn.connect("activated", lambda *_: self._confirm())
        g.add(self.flash_btn)

        g = Adw.PreferencesGroup(title="Before flashing")
        page.add(g)
        for title, text in BEFORE:
            row = Adw.ActionRow(title=title, subtitle=text, activatable=False)
            row.add_prefix(Gtk.Image(icon_name="dialog-information-symbolic"))
            g.add(row)

        self._update()
        worker.run(lambda p: firmware_catalog.latest_tsf(), self._latest, lambda e: None)

    # --- choosing ------------------------------------------------------------------------------

    def _choice(self, title, subtitle, group):
        row = Adw.ActionRow(title=title, subtitle=subtitle, subtitle_lines=4)
        check = Gtk.CheckButton(valign=Gtk.Align.CENTER, group=group, active=group is None)
        check.connect("toggled", lambda *_: self._update())
        row.add_prefix(check)
        row.set_activatable_widget(check)
        return row, check

    def _latest(self, build):
        """the newest Talkpod Super Firmware release, found on a thread"""
        if build.version == self.builds[0].version and build.sha256 == self.builds[0].sha256:
            return
        self.builds[0] = build
        self.choices[0][0].set_title(f"{build.title} {build.version}")
        self._update()

    def selection(self):
        for build, (_, check) in zip(self.builds, self.choices):
            if check.get_active():
                return build
        return None

    def _choose(self, *_):
        d = Gtk.FileDialog(title="Choose a firmware file")
        f = Gtk.FileFilter(name="Talkpod firmware (*.kdhx, *.bin)")
        f.add_pattern("*.kdhx")
        f.add_pattern("*.bin")
        filters = Gio.ListStore(item_type=Gtk.FileFilter)
        filters.append(f)
        d.set_filters(filters)

        def done(dlg, res):
            try:
                path = dlg.open_finish(res).get_path()
            except GLib.Error:
                return
            try:
                with open(path, "rb") as fh:
                    data = fh.read(firmware_catalog.MAX_BYTES + 1)
            except OSError as e:
                self._alert("Can't read that file", str(e))
                return
            self.file_image = firmware.Image(data, GLib.path_get_basename(path))
            self.file_label.set_text(self.file_image.name)
            self.file_check.set_active(True)
            self._update()

        d.open(self.get_root(), None, done)

    def _update(self):
        build = self.selection()
        ready = True
        if build:
            source = urlparse(build.url).netloc
            extra = "a copy comes with this app" if build.bundled else f"downloaded from {source} when you flash"
            self.selected_row.set_subtitle(f"{build.title} {build.version} · {build.filename} · {extra}, checked "
                                           "against its SHA-256")
        elif self.file_image:
            self.selected_row.set_subtitle(self.file_image.describe())
            ready = not self.file_image.problems
        else:
            self.selected_row.set_subtitle("Choose a firmware file")
            ready = False
        port = self.win.port()
        if not port:
            self.flash_btn.set_title("No programming cable found")
        else:
            self.flash_btn.set_title("Flash to radio")
        self.flash_btn.set_sensitive(ready and bool(port) and not self.flashing and not self.win.busy)

    # --- flashing ------------------------------------------------------------------------------

    def _alert(self, heading, body):
        d = Adw.AlertDialog(heading=heading, body=body)
        d.add_response("ok", "OK")
        d.present(self)

    def _confirm(self):
        build = self.selection()
        name = f"{build.title} {build.version}" if build else self.file_image.name
        body = (build.warning + "\n\n" if build else "") + (
            "Don't unplug the cable or switch the radio off until it's done (about 30 seconds).")
        d = Adw.AlertDialog(heading=f"Flash {name}?", body=body)
        d.add_response("cancel", "Cancel")
        d.add_response("flash", "Flash")
        d.set_response_appearance("flash", Adw.ResponseAppearance.DESTRUCTIVE)
        d.connect("response", lambda _d, r: self._flash(build) if r == "flash" else None)
        d.present(self)

    def _flash(self, build):
        port, manual, image = self.win.port(), self.manual_row.get_active(), self.file_image

        def job(progress):
            img = firmware_catalog.fetch(build, lambda f: progress(0.08 * f, "Downloading")) if build else image
            if img.problems:
                raise firmware.FirmwareError("Not flashing this file: " + "; ".join(img.problems))
            if manual:
                firmware.check_for_radio(img, rio.mml_jc8810.A36plusRadio)
            else:
                progress(0.08, "Checking the radio")
                cls, _ident = rio.identify(port, allow_custom=True)
                firmware.check_for_radio(img, cls)
            firmware.flash(port, img, lambda f, t: progress(0.1 + 0.9 * f, t), manual=manual)
            return img

        self.flashing = True
        self.set_can_close(False)
        self.progress_row.set_visible(True)
        self.progress.set_fraction(0)
        self.progress.set_text("Starting")
        self.win.set_busy(True, "Flashing firmware")
        self._update()
        worker.run(job, lambda img: self._done(build, img), self._failed, self._progress)

    def _progress(self, fraction, text):
        self.progress.set_fraction(fraction)
        if text:
            self.progress.set_text(text)
        self.win._progress(fraction, text)

    def _finish(self):
        self.flashing = False
        self.set_can_close(True)
        self.progress_row.set_visible(False)
        self.win.set_busy(False)
        self._update()

    def _done(self, build, image):
        self._finish()
        after = build.after if build else f"The radio restarts with {image.name} (version {image.version or '?'})."
        self._alert("Firmware flashed", after)

    def _failed(self, e):
        self._finish()
        if isinstance(e, rio.RadioError):
            self._alert("Firmware not flashed", str(e))
        else:
            LOG.exception("flashing failed", exc_info=e)
            appreports.report_error(e, "firmware flash")
            self._alert("Something went wrong", f"{type(e).__name__}: {e}\n\nA report has been sent.")
