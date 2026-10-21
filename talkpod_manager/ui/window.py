"""The main window."""

import datetime as dt
import logging
from pathlib import Path

from gi.repository import Adw, Gio, GLib, Gtk, Pango

from .. import APP_NAME, appreports, backups, channels, logo, paths, updater
from .. import radio as rio
from . import worker
from .backups_page import BackupsPage
from .channel_dialog import ChannelDialog
from .channels_page import ChannelsPage
from .logo_page import LogoPage
from .plan_dialog import PlanDialog
from .settings_page import SettingsPage

from chirp import chirp_common

LOG = logging.getLogger(__name__)


def _file_dialog(title, pattern, name):
    d = Gtk.FileDialog(title=title)
    f = Gtk.FileFilter(name=name)
    f.add_pattern(pattern)
    store = Gio.ListStore(item_type=Gtk.FileFilter)
    store.append(f)
    d.set_filters(store)
    return d


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title=APP_NAME, default_width=1120, default_height=780)
        self.set_icon_name(app.get_application_id())
        self.radio = None
        self.dirty = False
        self.source = ""
        self.busy = False
        self.ports = []
        self.update = None

        self.stack = Adw.ViewStack()
        header = Adw.HeaderBar()
        self.read_btn = Gtk.Button(child=Adw.ButtonContent(icon_name="go-down-symbolic", label="Read"),
                                   tooltip_text="Read channels and settings from the radio (Ctrl+R)",
                                   action_name="win.read")
        self.write_btn = Gtk.Button(child=Adw.ButtonContent(icon_name="go-up-symbolic", label="Write"),
                                    tooltip_text="Write channels and settings to the radio",
                                    action_name="win.write")
        header.pack_start(self.read_btn)
        header.pack_start(self.write_btn)
        header.set_title_widget(Adw.ViewSwitcher(policy=Adw.ViewSwitcherPolicy.WIDE, stack=self.stack))
        menu_btn = Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=self._menu(), primary=True,
                                  tooltip_text="Main menu")
        header.pack_end(menu_btn)
        self.port_model = Gtk.StringList()
        self.port_dd = Gtk.DropDown(model=self.port_model, tooltip_text="Programming cable")
        header.pack_end(self.port_dd)

        self.banner = Adw.Banner(button_label="Update")
        self.banner.connect("button-clicked", lambda *_: self._offer_update())

        self.channels_page = ChannelsPage()
        self.channels_page.connect("edit-requested", lambda _p, n: self.edit_channel(n))
        self.channels_page.connect("add-requested", lambda *_: self.add_channel())
        self.channels_page.connect("clear-requested", lambda _p, n: self.clear_channel(n))
        self.channels_page.connect("plan-requested", lambda *_: self.activate_action("win.plan"))
        self.settings_page = SettingsPage()
        self.settings_page.connect("changed", lambda *_: self.mark_dirty())
        self.logo_page = LogoPage()
        self.logo_page.connect("send-requested", lambda *_: self.send_logo())
        self.logo_page.connect("use-logo-requested", lambda *_: self.use_logo_at_power_on())
        self.backups_page = BackupsPage()
        self.backups_page.connect("open-requested", lambda _p, path: self.confirm_discard(lambda: self.open_image(path)))
        self.backups_page.connect("save-requested", lambda *_: self.save_backup())

        self.channels_stack = self._with_empty(self.channels_page)
        self.settings_stack = self._with_empty(self.settings_page)
        self.stack.add_titled_with_icon(self.channels_stack, "channels", "Channels", "view-list-symbolic")
        self.stack.add_titled_with_icon(self.settings_stack, "settings", "Settings", "emblem-system-symbolic")
        self.stack.add_titled_with_icon(self.logo_page, "logo", "Boot logo", "image-x-generic-symbolic")
        self.stack.add_titled_with_icon(self.backups_page, "backups", "Backups", "document-open-recent-symbolic")

        self.status = Gtk.Label(xalign=0, hexpand=True, ellipsize=Pango.EllipsizeMode.END)
        self.status.add_css_class("dim-label")
        self.progress = Gtk.ProgressBar(show_text=True, valign=Gtk.Align.CENTER, width_request=320)
        self.progress_rev = Gtk.Revealer(child=self.progress, transition_type=Gtk.RevealerTransitionType.CROSSFADE)
        bottom = Gtk.Box(spacing=12, margin_start=12, margin_end=12, margin_top=6, margin_bottom=6)
        bottom.append(self.status)
        bottom.append(self.progress_rev)

        self.toasts = Adw.ToastOverlay(child=self.stack)
        view = Adw.ToolbarView(content=self.toasts)
        view.add_top_bar(header)
        view.add_top_bar(self.banner)
        view.add_bottom_bar(bottom)
        self.set_content(view)

        self._actions()
        self.connect("close-request", self._on_close)
        self._poll_ports()
        GLib.timeout_add_seconds(2, self._poll_ports)
        GLib.timeout_add_seconds(3, self._background_update_check)
        self._sync()

    # --- layout helpers ------------------------------------------------------------------------

    def _with_empty(self, content):
        status = Adw.StatusPage(
            icon_name=self.get_application().get_application_id(),
            title="No radio loaded",
            description="Plug in the programming cable, switch the radio on and read it, or open a saved image.")
        box = Gtk.Box(spacing=12, halign=Gtk.Align.CENTER)
        read = Gtk.Button(label="Read from radio", action_name="win.read")
        read.add_css_class("pill")
        read.add_css_class("suggested-action")
        open_ = Gtk.Button(label="Open image…", action_name="win.open")
        open_.add_css_class("pill")
        box.append(read)
        box.append(open_)
        status.set_child(box)
        stack = Gtk.Stack()
        stack.add_named(status, "empty")
        stack.add_named(content, "content")
        return stack

    def _menu(self):
        m = Gio.Menu()
        files = Gio.Menu()
        files.append("Open image…", "win.open")
        files.append("Save image as…", "win.save-as")
        files.append("Import CSV…", "win.import-csv")
        files.append("Export CSV…", "win.export-csv")
        m.append_section(None, files)
        tools = Gio.Menu()
        tools.append("Channel plan…", "win.plan")
        m.append_section(None, tools)
        help_ = Gio.Menu()
        help_.append("Check for updates", "win.check-updates")
        help_.append("Report a problem…", "win.report")
        help_.append(f"About {APP_NAME}", "app.about")
        m.append_section(None, help_)
        return m

    def _actions(self):
        self.acts = {}
        for name, fn in [
            ("read", self.read), ("write", self.write), ("open", self.open_dialog), ("save-as", self.save_as),
            ("import-csv", self.import_csv), ("export-csv", self.export_csv), ("plan", self.plan),
            ("check-updates", lambda: self.check_updates(manual=True)), ("report", self.report_problem),
        ]:
            a = Gio.SimpleAction(name=name)
            a.connect("activate", lambda _a, _p, fn=fn: fn())
            self.add_action(a)
            self.acts[name] = a
        app = self.get_application()
        app.set_accels_for_action("win.read", ["<Control>r"])
        app.set_accels_for_action("win.open", ["<Control>o"])
        app.set_accels_for_action("win.save-as", ["<Control>s"])

    # --- state ---------------------------------------------------------------------------------

    def port(self):
        i = self.port_dd.get_selected()
        return self.ports[i].device if 0 <= i < len(self.ports) else None

    def _poll_ports(self):
        try:
            ports = rio.find_ports()
        except Exception:
            LOG.exception("listing serial ports failed")
            return True
        if [p.device for p in ports] != [p.device for p in self.ports]:
            current = self.port()
            self.ports = ports
            labels = [p.label() for p in ports] or ["No cable found"]
            self.port_model.splice(0, self.port_model.get_n_items(), labels)
            devices = [p.device for p in ports]
            self.port_dd.set_selected(devices.index(current) if current in devices else 0)
            self._sync()
        return True

    def _sync(self):
        has_port = bool(self.ports)
        has_radio = self.radio is not None
        self.port_dd.set_sensitive(has_port and not self.busy)
        self.acts["read"].set_enabled(has_port and not self.busy)
        self.acts["write"].set_enabled(has_port and has_radio and not self.busy)
        for name in ("save-as", "export-csv", "import-csv", "plan"):
            self.acts[name].set_enabled(has_radio and not self.busy)
        self.acts["open"].set_enabled(not self.busy)
        if self.dirty:
            self.write_btn.add_css_class("suggested-action")
        else:
            self.write_btn.remove_css_class("suggested-action")
        self.logo_page.send.set_sensitive(has_port and not self.busy and self.logo_page.pixels is not None)
        for s in (self.channels_stack, self.settings_stack):
            s.set_visible_child_name("content" if has_radio else "empty")
        self.backups_page.can_save = has_radio
        text = self.source or "Nothing loaded"
        if self.dirty:
            text += " · changed, not written to the radio yet"
        if not has_port:
            text += " · no programming cable found"
        self.status.set_text(text)

    def mark_dirty(self):
        self.dirty = True
        self._sync()

    def set_radio(self, r, source, dirty=False):
        self.radio = r
        self.source = source
        self.dirty = dirty
        self.channels_page.load(r)
        self.settings_page.load(r)
        self.logo_page.set_power_on_message(self.settings_page.value("ponmsg"))
        self.backups_page.set_can_save(True)
        self._sync()

    def set_busy(self, busy, text=""):
        self.busy = busy
        self.progress.set_fraction(0)
        self.progress.set_text(text)
        self.progress_rev.set_reveal_child(busy)
        self._sync()

    def _progress(self, fraction, text):
        self.progress.set_fraction(fraction)
        if text:
            self.progress.set_text(text)

    def toast(self, text, timeout=4):
        self.toasts.add_toast(Adw.Toast(title=text, timeout=timeout))

    def alert(self, heading, body):
        d = Adw.AlertDialog(heading=heading, body=body)
        d.add_response("ok", "OK")
        d.present(self)

    def _io_error(self, e):
        self.set_busy(False)
        if isinstance(e, rio.RadioError):
            self.alert("Radio problem", str(e))
        else:
            LOG.exception("unexpected error", exc_info=e)
            appreports.report_error(e, "radio operation")
            self.alert("Something went wrong", f"{type(e).__name__}: {e}\n\nA report has been sent.")

    def confirm_discard(self, then):
        if not self.dirty:
            then()
            return
        d = Adw.AlertDialog(heading="Discard changes?",
                            body="The channels or settings were changed but not written to the radio or saved.")
        d.add_response("cancel", "Cancel")
        d.add_response("discard", "Discard")
        d.set_response_appearance("discard", Adw.ResponseAppearance.DESTRUCTIVE)
        d.connect("response", lambda _d, r: then() if r == "discard" else None)
        d.present(self)

    def _on_close(self, *_):
        if not self.dirty:
            return False

        def go():
            self.dirty = False
            self.close()

        self.confirm_discard(go)
        return True

    # --- radio ---------------------------------------------------------------------------------

    def read(self):
        self.confirm_discard(self._do_read)

    def _do_read(self):
        port = self.port()
        if not port:
            return
        self.set_busy(True, "Reading from radio")
        worker.run(lambda p: rio.download(port, p), self._read_done, self._io_error, self._progress)

    def _read_done(self, r):
        self.set_busy(False)
        self.set_radio(r, f"Read from the radio at {dt.datetime.now():%H:%M}")
        self.toast(f"Read {channels.used_count(r)} channels from the radio")

    def write(self):
        d = Adw.AlertDialog(
            heading="Write to the radio?",
            body="This replaces all channels and settings on the radio with what's in the editor. "
                 "The radio's current contents are backed up first, and the result is read back to check it.")
        d.add_response("cancel", "Cancel")
        d.add_response("write", "Write")
        d.set_response_appearance("write", Adw.ResponseAppearance.SUGGESTED)
        d.connect("response", lambda _d, r: self._do_write() if r == "write" else None)
        d.present(self)

    def _do_write(self):
        port = self.port()
        image = rio.copy_radio(self.radio)

        def job(progress):
            current = rio.download(port, lambda f, t: progress(f * 0.3, "Backing up the radio first"))
            before = backups.save(current, "before write")
            rio.upload(port, image, lambda f, t: progress(0.3 + f * 0.4, "Writing to the radio"))
            check = rio.download(port, lambda f, t: progress(0.7 + f * 0.3, "Reading back to check"))
            after = backups.save(check, "after write")
            return before, after, rio.compare(image, check)

        self.set_busy(True, "Backing up the radio first")
        worker.run(job, self._write_done, self._io_error, self._progress)

    def _write_done(self, result):
        before, after, diffs = result
        self.set_busy(False)
        self.backups_page.reload()
        if diffs:
            LOG.warning("read-back differs at %d bytes, first %s", len(diffs), [hex(a) for a in diffs[:10]])
            self.alert("Written, but the check found differences",
                       f"The radio holds different data at {len(diffs)} byte(s) than was written "
                       f"(first at {diffs[0]:#06x}). Try writing again. Backups: {before.name}, {after.name}")
            return
        self.dirty = False
        self.source = f"Written to the radio at {dt.datetime.now():%H:%M} and checked"
        self._sync()
        self.toast("Written and checked: the radio matches the editor")

    def send_logo(self):
        d = Adw.AlertDialog(
            heading="Replace the boot logo?",
            body="The radio can't send its current picture back, so the old logo can't be restored "
                 "unless you have a copy of it. Channels and settings aren't touched.")
        d.add_response("cancel", "Cancel")
        d.add_response("send", "Send picture")
        d.set_response_appearance("send", Adw.ResponseAppearance.DESTRUCTIVE)
        d.connect("response", lambda _d, r: self._do_send_logo() if r == "send" else None)
        d.present(self)

    def _do_send_logo(self):
        port, pixels = self.port(), self.logo_page.pixels
        self.set_busy(True, "Sending picture")
        worker.run(lambda p: logo.send(port, pixels, p), self._logo_done, self._io_error, self._progress)

    def _logo_done(self, _):
        self.set_busy(False)
        self.alert("Picture sent",
                   "Switch the radio off and on to see it. If it shows the battery voltage instead, set menu 49 "
                   "(Power On Message) to Logo, or use “Show logo” on this page and Write.")

    def use_logo_at_power_on(self):
        if not self.radio:
            return
        for group in self.settings_page.settings:
            for el in group:
                if getattr(el, "get_name", lambda: "")() == "ponmsg":
                    options = [str(o) for o in el.value.get_options()]
                    choice = next((o for o in options if o.lower() == "logo"), None)
                    if choice:
                        el.value.set_value(choice)
                        rio.apply_setting(self.radio, el)
                        self.settings_page.load(self.radio)
                        self.logo_page.set_power_on_message(choice)
                        self.mark_dirty()
                        self.toast("Power-on message set to Logo. Write to send it to the radio.")
                    return

    # --- channels ------------------------------------------------------------------------------

    def edit_channel(self, number):
        if self.radio is None:
            return
        mem = self.radio.get_memory(number)
        new = mem.empty
        if new:
            mem = self._blank(number)
        ChannelDialog(self.radio, mem, self._channel_saved, self.clear_channel, new=new).present(self)

    def _blank(self, number):
        m = chirp_common.Memory()
        m.number = number
        m.freq = 0
        m.mode = "NFM"
        m.power = self.radio.POWER_LEVELS[0]
        m.extra = self.radio.get_memory(number).extra
        return m

    def add_channel(self):
        n = self.channels_page.first_empty()
        if n is None:
            self.toast("Every channel is in use")
            return
        ChannelDialog(self.radio, self._blank(n), self._channel_saved, new=True).present(self)

    def _channel_saved(self, mem):
        self.radio.set_memory(mem)
        self.channels_page.refresh(self.radio, mem.number)
        self.mark_dirty()

    def clear_channel(self, number):
        channels.clear(self.radio, number)
        self.channels_page.refresh(self.radio, number)
        self.mark_dirty()
        self.toast(f"Channel {number} cleared")

    def plan(self):
        def applied(count):
            self.channels_page.load(self.radio)
            self.mark_dirty()
            self.toast(f"Plan applied: {count} channels. Write to send it to the radio.")

        PlanDialog(self.radio, applied).present(self)

    # --- files ---------------------------------------------------------------------------------

    def open_dialog(self):
        d = _file_dialog("Open radio image", "*.img", "CHIRP images (*.img)")
        d.set_initial_folder(Gio.File.new_for_path(str(paths.backups_dir())))

        def done(dlg, res):
            try:
                path = dlg.open_finish(res).get_path()
            except GLib.Error:
                return
            self.confirm_discard(lambda: self.open_image(path))

        d.open(self, None, done)

    def open_image(self, path):
        try:
            r = rio.load_image(path)
        except rio.RadioError as e:
            self.alert("Can't open image", str(e))
            return
        self.set_radio(r, f"Opened {Path(path).name}")
        self.stack.set_visible_child_name("channels")

    def save_as(self):
        d = _file_dialog("Save radio image", "*.img", "CHIRP images (*.img)")
        d.set_initial_folder(Gio.File.new_for_path(str(paths.backups_dir())))
        d.set_initial_name(f"talkpod-{dt.datetime.now():%Y-%m-%d}.img")

        def done(dlg, res):
            try:
                path = dlg.save_finish(res).get_path()
            except GLib.Error:
                return
            if not path.endswith(".img"):
                path += ".img"
            self.radio.save_mmap(path)
            self.source = f"Saved as {Path(path).name}"
            self.dirty = False
            self.backups_page.reload()
            self._sync()
            self.toast(f"Saved {Path(path).name}")

        d.save(self, None, done)

    def save_backup(self):
        if self.radio:
            p = backups.save(self.radio, "saved by hand")
            self.backups_page.reload()
            self.toast(f"Saved {p.name}")

    def import_csv(self):
        d = _file_dialog("Import channels from CSV", "*.csv", "CHIRP CSV files (*.csv)")

        def done(dlg, res):
            try:
                path = dlg.open_finish(res).get_path()
            except GLib.Error:
                return
            try:
                count, problems = channels.import_csv(self.radio, path)
            except Exception as e:
                LOG.exception("CSV import failed")
                self.alert("Can't import that file", str(e))
                return
            self.channels_page.load(self.radio)
            if count:
                self.mark_dirty()
            if problems:
                self.alert(f"Imported {count} channels, skipped {len(problems)}", "\n".join(problems[:30]))
            else:
                self.toast(f"Imported {count} channels. Other channels were cleared.")

        d.open(self, None, done)

    def export_csv(self):
        d = _file_dialog("Export channels to CSV", "*.csv", "CHIRP CSV files (*.csv)")
        d.set_initial_name(f"talkpod-channels-{dt.datetime.now():%Y-%m-%d}.csv")

        def done(dlg, res):
            try:
                path = dlg.save_finish(res).get_path()
            except GLib.Error:
                return
            if not path.endswith(".csv"):
                path += ".csv"
            n = channels.export_csv(self.radio, path)
            self.toast(f"Exported {n} channels to {Path(path).name}")

        d.save(self, None, done)

    # --- updates and reports -------------------------------------------------------------------

    def _background_update_check(self):
        if updater.due():
            self.check_updates(manual=False)
        return False

    def check_updates(self, manual):
        def done(u):
            updater.mark_checked()
            self.update = u
            if u:
                self.banner.set_title(f"{APP_NAME} {u.version} is available")
                self.banner.set_revealed(True)
            elif manual:
                self.toast("You have the latest version")

        def failed(e):
            LOG.info("update check failed: %s", e)
            if manual:
                self.toast("Couldn't check for updates")

        worker.run(lambda p: updater.check(), done, failed)

    def _offer_update(self):
        u = self.update
        if not u:
            return
        notes = u.notes.strip() or "No release notes."
        d = Adw.AlertDialog(heading=f"Update to {u.version}?", body=notes[:1500])
        d.add_response("cancel", "Not now")
        d.add_response("install", "Update")
        d.set_response_appearance("install", Adw.ResponseAppearance.SUGGESTED)
        d.connect("response", lambda _d, r: self._install_update(u) if r == "install" else None)
        d.present(self)

    def _install_update(self, u):
        self.set_busy(True, f"Downloading {u.version}")

        def done(_):
            self.set_busy(False)
            self.banner.set_revealed(False)
            d = Adw.AlertDialog(heading=f"Updated to {u.version}", body="Restart the app to use the new version.")
            d.add_response("later", "Later")
            d.add_response("restart", "Restart now")
            d.set_response_appearance("restart", Adw.ResponseAppearance.SUGGESTED)
            d.connect("response", lambda _d, r: self._restart() if r == "restart" else None)
            d.present(self)

        def failed(e):
            self.set_busy(False)
            self.alert("Update failed", str(e))

        worker.run(lambda p: updater.install(u, lambda f: p(f, f"Downloading {u.version}")), done, failed, self._progress)

    def _restart(self):
        self.confirm_discard(updater.restart)

    def report_problem(self):
        d = Adw.AlertDialog(
            heading="Report a problem",
            body="Sends this app's recent log, the app and radio versions and basic PC details "
                 "(no personal data) so the problem can be looked into.")
        text = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR, top_margin=8, bottom_margin=8, left_margin=8,
                            right_margin=8)
        text.set_size_request(-1, 120)
        frame = Gtk.Frame(child=Gtk.ScrolledWindow(child=text, min_content_height=120))
        d.set_extra_child(frame)
        d.add_response("cancel", "Cancel")
        d.add_response("send", "Send")
        d.set_response_appearance("send", Adw.ResponseAppearance.SUGGESTED)

        def response(_d, r):
            if r != "send":
                return
            buf = text.get_buffer()
            note = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False).strip() or None
            extra = {"port": self.port(), "loaded": self.source, "dirty": self.dirty,
                     "model": self.radio.MODEL if self.radio else None,
                     "channels": channels.used_count(self.radio) if self.radio else None}
            appreports.send_report(note, extra, on_done=lambda ok: GLib.idle_add(
                self.toast, "Report sent. Thanks!" if ok else "Couldn't send now; it will be sent automatically later."))

        d.connect("response", response)
        d.present(self)
