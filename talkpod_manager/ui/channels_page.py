"""The channel list."""

from gi.repository import Gio, GObject, Gtk, Pango

from .. import channels

COLUMNS = [
    ("Ch", "number_text", False),
    ("Name", "name", True),
    ("Receive (MHz)", "rx", False),
    ("Transmit", "tx", True),
    ("Tones", "tones", False),
    ("Power", "power", False),
    ("Width", "width", False),
    ("Scan", "scan", False),
]


class ChannelItem(GObject.Object):
    def __init__(self, mem):
        super().__init__()
        self.set_mem(mem)

    def set_mem(self, mem):
        self.mem = mem
        self.number = mem.number
        self.number_text = str(mem.number)
        if mem.empty:
            self.name = self.rx = self.tx = self.tones = self.power = self.width = self.scan = ""
            return
        self.name = mem.name.rstrip()
        self.rx = channels.mhz(mem.freq)
        self.tx = channels.tx_text(mem)
        self.tones = channels.tone_text(mem)
        self.power = channels.power_text(mem) if mem.duplex != "off" else ""
        self.width = "Narrow" if mem.mode == "NFM" else "Wide" if mem.mode == "FM" else mem.mode
        self.scan = "" if mem.skip == "S" else "Yes"


class ChannelsPage(Gtk.Box):
    """Emits edit-requested(number) and clear-requested(number); the window owns the image."""

    __gsignals__ = {
        "edit-requested": (GObject.SignalFlags.RUN_FIRST, None, (int,)),
        "add-requested": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "clear-requested": (GObject.SignalFlags.RUN_FIRST, None, (int,)),
        "plan-requested": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.store = Gio.ListStore(item_type=ChannelItem)
        self.items = {}

        bar = Gtk.Box(spacing=6, margin_top=6, margin_bottom=6, margin_start=12, margin_end=12)
        self.search = Gtk.SearchEntry(placeholder_text="Search name, frequency or number", hexpand=True)
        self.search.connect("search-changed", lambda *_: self.filter.changed(Gtk.FilterChange.DIFFERENT))
        bar.append(self.search)
        self.show_empty = Gtk.ToggleButton(label="Show empty")
        self.show_empty.set_tooltip_text("Also list unused channel numbers")
        self.show_empty.connect("toggled", lambda *_: self.filter.changed(Gtk.FilterChange.DIFFERENT))
        bar.append(self.show_empty)
        self.edit_btn = Gtk.Button(icon_name="document-edit-symbolic", tooltip_text="Edit channel")
        self.edit_btn.connect("clicked", lambda *_: self._emit_selected("edit-requested"))
        self.clear_btn = Gtk.Button(icon_name="edit-clear-symbolic", tooltip_text="Clear channel")
        self.clear_btn.connect("clicked", lambda *_: self._emit_selected("clear-requested"))
        add = Gtk.Button(icon_name="list-add-symbolic", tooltip_text="Add channel")
        add.connect("clicked", lambda *_: self.emit("add-requested"))
        plan = Gtk.Button(label="Channel plan…", tooltip_text="Fill the channels from a ready-made plan")
        plan.connect("clicked", lambda *_: self.emit("plan-requested"))
        for w in (self.edit_btn, self.clear_btn, add, plan):
            bar.append(w)
        self.append(bar)

        self.filter = Gtk.CustomFilter.new(self._match)
        filtered = Gtk.FilterListModel(model=self.store, filter=self.filter)
        self.selection = Gtk.SingleSelection(model=filtered, autoselect=False)
        self.selection.connect("notify::selected", lambda *_: self._sync_buttons())
        self.view = Gtk.ColumnView(model=self.selection, show_row_separators=True, reorderable=False)
        self.view.add_css_class("data-table")
        self.view.connect("activate", self._activate)
        for title, attr, expand in COLUMNS:
            factory = Gtk.SignalListItemFactory()
            factory.connect("setup", self._setup, attr)
            factory.connect("bind", self._bind, attr)
            col = Gtk.ColumnViewColumn(title=title, factory=factory, expand=expand, resizable=True)
            self.view.append_column(col)
        scroller = Gtk.ScrolledWindow(vexpand=True, child=self.view)
        self.append(scroller)

        self.summary = Gtk.Label(xalign=0, margin_start=12, margin_bottom=6, margin_top=4)
        self.summary.add_css_class("dim-label")
        self.append(self.summary)
        self._sync_buttons()

    @staticmethod
    def _setup(_f, li, attr):
        label = Gtk.Label(xalign=0)
        if attr in ("name", "tx"):
            label.set_ellipsize(Pango.EllipsizeMode.END)
        if attr in ("number_text", "rx"):
            label.add_css_class("numeric")
        li.set_child(label)

    @staticmethod
    def _bind(_f, li, attr):
        item = li.get_item()
        label = li.get_child()
        label.set_text(getattr(item, attr))
        if attr == "number_text":
            label.set_opacity(0.5 if item.mem.empty else 1.0)

    def _match(self, item):
        if item.mem.empty and not self.show_empty.get_active():
            return False
        q = self.search.get_text().strip().lower()
        if not q:
            return True
        return q == item.number_text or q in item.name.lower() or q in item.rx or q in item.tx.lower()

    def _selected_item(self):
        return self.selection.get_selected_item()

    def _emit_selected(self, signal):
        item = self._selected_item()
        if item is not None:
            self.emit(signal, item.number)

    def _activate(self, _view, position):
        item = self.selection.get_model().get_item(position)
        if item is not None:
            self.emit("edit-requested", item.number)

    def _sync_buttons(self):
        item = self._selected_item()
        self.edit_btn.set_sensitive(item is not None)
        self.clear_btn.set_sensitive(item is not None and not item.mem.empty)

    def load(self, radio):
        self.store.remove_all()
        self.items = {}
        items = []
        for mem in channels.all_memories(radio):
            it = ChannelItem(mem)
            self.items[mem.number] = it
            items.append(it)
        self.store.splice(0, 0, items)
        self._update_summary()
        self._sync_buttons()

    def refresh(self, radio, number):
        """Update one channel after an edit."""
        it = self.items.get(number)
        if it is None:
            return
        it.set_mem(radio.get_memory(number))
        pos = self.store.find(it)
        if pos[0]:
            self.store.splice(pos[1], 1, [it])
        self.filter.changed(Gtk.FilterChange.DIFFERENT)
        self._update_summary()
        self._sync_buttons()

    def _update_summary(self):
        used = sum(1 for it in self.items.values() if not it.mem.empty)
        self.summary.set_text(f"{used} of {len(self.items)} channels programmed · double-click a channel to edit it")

    def first_empty(self):
        for n, it in self.items.items():
            if it.mem.empty:
                return n
        return None
