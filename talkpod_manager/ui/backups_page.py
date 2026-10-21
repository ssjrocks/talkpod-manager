"""Saved radio images."""

from gi.repository import Adw, Gio, GObject, Gtk

from .. import backups, paths


class BackupsPage(Gtk.Box):
    __gsignals__ = {
        "open-requested": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        "save-requested": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.page = None
        self.can_save = False
        self.reload()

    def set_can_save(self, can):
        self.can_save = can
        self.reload()

    def reload(self):
        if self.page is not None:
            self.remove(self.page)
        self.page = Adw.PreferencesPage(vexpand=True)
        folder = paths.backups_dir()
        g = Adw.PreferencesGroup(
            title="Backups",
            description="A backup of the radio is saved here automatically before and after every write. "
                        "Opening one loads it into the editor; nothing goes to the radio until you Write.")
        actions = Gtk.Box(spacing=6)
        save = Gtk.Button(label="Save current image", sensitive=self.can_save)
        save.connect("clicked", lambda *_: self.emit("save-requested"))
        show = Gtk.Button(icon_name="folder-open-symbolic", tooltip_text=str(folder))
        show.connect("clicked", lambda *_: Gtk.FileLauncher(file=Gio.File.new_for_path(str(folder))).launch(self.get_root(), None, None))
        actions.append(save)
        actions.append(show)
        g.set_header_suffix(actions)
        self.page.add(g)
        items = backups.list_all()
        if not items:
            g.add(Adw.ActionRow(title="No backups yet", subtitle=str(folder)))
        for b in items:
            n = b.channels()
            row = Adw.ActionRow(
                title=b.when.strftime("%a %d %b %Y, %H:%M:%S"),
                subtitle=f"{b.label} · {n} channels" if n is not None else f"{b.label} · unreadable")
            open_btn = Gtk.Button(label="Open", valign=Gtk.Align.CENTER, sensitive=n is not None)
            open_btn.connect("clicked", lambda _b, p=str(b.path): self.emit("open-requested", p))
            row.add_suffix(open_btn)
            g.add(row)
        self.append(self.page)
