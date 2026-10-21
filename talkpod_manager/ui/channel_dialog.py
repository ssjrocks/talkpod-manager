"""Edit (or add) one channel."""

from gi.repository import Adw, Gtk

from .. import channels
from .. import radio as _radio  # noqa: F401
from chirp import chirp_common

from . import settingrows

DUPLEX_ORDER = ["", "+", "-", "split", "off"]
TONE_MODES = [("", "None"), ("Tone", "CTCSS on transmit"), ("TSQL", "CTCSS both ways"), ("DTCS", "DCS")]
WIDTHS = [("NFM", "Narrow (12.5 kHz)"), ("FM", "Wide (25 kHz)")]
POLARITIES = ["NN", "NR", "RN", "RR"]


def power_label(p):
    watts = 10 ** ((float(p) - 30) / 10)
    name = {"H": "High", "M": "Medium", "L": "Low"}.get(str(p), str(p))
    return f"{name} ({watts:.0f} W)" if watts >= 1 else f"{name} ({watts:.1f} W)"


def _combo(title, labels, selected=0):
    row = Adw.ComboRow(title=title, model=Gtk.StringList.new(labels))
    row.set_selected(max(0, selected))
    return row


class ChannelDialog(Adw.Dialog):
    def __init__(self, radio, mem, on_save, on_clear=None, new=False):
        super().__init__(title="New channel" if new else f"Channel {mem.number}", content_width=480,
                         content_height=720)
        self.radio = radio
        self.orig = mem
        self.mem = mem.dupe()
        self.on_save = on_save
        self.new = new
        rf = radio.get_features()
        self.rf = rf

        view = Adw.ToolbarView()
        header = Adw.HeaderBar(show_end_title_buttons=False, show_start_title_buttons=False)
        cancel = Gtk.Button(label="Cancel")
        cancel.connect("clicked", lambda *_: self.close())
        self.save_btn = Gtk.Button(label="Save")
        self.save_btn.add_css_class("suggested-action")
        self.save_btn.connect("clicked", self._save)
        header.pack_start(cancel)
        header.pack_end(self.save_btn)
        view.add_top_bar(header)
        page = Adw.PreferencesPage()
        view.set_content(page)
        self.set_child(view)
        self.set_default_widget(self.save_btn)

        m = self.mem
        g = Adw.PreferencesGroup()
        page.add(g)
        if new:
            lo, hi = rf.memory_bounds
            adj = Gtk.Adjustment(lower=lo, upper=hi, step_increment=1, page_increment=10, value=m.number)
            self.number = Adw.SpinRow(title="Channel number", adjustment=adj)
            g.add(self.number)
        self.name = Adw.EntryRow(title=f"Name (up to {rf.valid_name_length} characters)", text=m.name.rstrip())
        g.add(self.name)
        self.rx = Adw.EntryRow(title="Receive frequency (MHz)",
                               text=channels.mhz(m.freq) if m.freq else "")
        self.rx.set_input_purpose(Gtk.InputPurpose.NUMBER)
        g.add(self.rx)

        g = Adw.PreferencesGroup(title="Transmit")
        page.add(g)
        self.duplexes = [d for d in DUPLEX_ORDER if d in rf.valid_duplexes]
        self.duplex = _combo("Transmit", [channels.DUPLEX_LABELS[d] for d in self.duplexes],
                             self.duplexes.index(m.duplex) if m.duplex in self.duplexes else 0)
        g.add(self.duplex)
        self.offset = Adw.EntryRow(title="Offset (MHz)")
        self.offset.set_input_purpose(Gtk.InputPurpose.NUMBER)
        if m.duplex == "split":
            self.offset.set_text(channels.mhz(m.offset))
        elif m.duplex in ("+", "-"):
            self.offset.set_text(f"{m.offset / 1e6:g}")
        g.add(self.offset)
        self.duplex.connect("notify::selected", lambda *_: self._sync())
        levels = list(radio.POWER_LEVELS)
        self.power = _combo("Power", [power_label(p) for p in levels],
                            levels.index(m.power) if m.power in levels else 0)
        self.levels = levels
        g.add(self.power)

        g = Adw.PreferencesGroup(title="Tones")
        page.add(g)
        modes = list(TONE_MODES)
        if m.tmode == "Cross":
            modes.append(("Cross", f"Cross ({m.cross_mode}), kept as is"))
        self.modes = modes
        keys = [k for k, _ in modes]
        self.tmode = _combo("Tone squelch", [label for _, label in modes],
                            keys.index(m.tmode) if m.tmode in keys else 0)
        self.tmode.connect("notify::selected", lambda *_: self._sync())
        g.add(self.tmode)
        tones = list(chirp_common.TONES)
        self.tones = tones
        cur_tone = m.ctone if m.tmode == "TSQL" else m.rtone
        self.tone = _combo("CTCSS tone (Hz)", [f"{t:.1f}" for t in tones],
                           tones.index(cur_tone) if cur_tone in tones else tones.index(88.5))
        g.add(self.tone)
        codes = list(rf.valid_dtcs_codes or chirp_common.DTCS_CODES)
        self.codes = codes
        self.dcs = _combo("DCS code", [f"{c:03d}" for c in codes], codes.index(m.dtcs) if m.dtcs in codes else 0)
        g.add(self.dcs)
        self.pol = _combo("DCS polarity (transmit/receive)", ["Normal / normal", "Normal / inverted",
                                                               "Inverted / normal", "Inverted / inverted"],
                          POLARITIES.index(m.dtcs_polarity) if m.dtcs_polarity in POLARITIES else 0)
        g.add(self.pol)

        g = Adw.PreferencesGroup(title="Options")
        page.add(g)
        widths = [w for w in WIDTHS if w[0] in rf.valid_modes]
        self.widths = widths
        wkeys = [k for k, _ in widths]
        self.width = _combo("Bandwidth", [label for _, label in widths], wkeys.index(m.mode) if m.mode in wkeys else 0)
        g.add(self.width)
        self.scan = Adw.SwitchRow(title="Include in scan", active=m.skip != "S")
        g.add(self.scan)
        if m.extra:
            for s in m.extra:
                g.add(settingrows.row_for(s))

        self.error = Gtk.Label(wrap=True, xalign=0, visible=False)
        self.error.add_css_class("error")
        eg = Adw.PreferencesGroup()
        eg.add(self.error)
        page.add(eg)

        if on_clear and not new and not mem.empty:
            cg = Adw.PreferencesGroup()
            clear = Adw.ButtonRow(title="Clear this channel")
            clear.add_css_class("destructive-action")
            clear.connect("activated", lambda *_: (on_clear(mem.number), self.close()))
            cg.add(clear)
            page.add(cg)
        self._sync()

    def _sync(self):
        d = self.duplexes[self.duplex.get_selected()]
        self.offset.set_visible(d in ("+", "-", "split"))
        self.offset.set_title("Transmit frequency (MHz)" if d == "split" else "Offset (MHz)")
        self.power.set_sensitive(d != "off")
        t = self.modes[self.tmode.get_selected()][0]
        self.tone.set_visible(t in ("Tone", "TSQL"))
        self.dcs.set_visible(t == "DTCS")
        self.pol.set_visible(t == "DTCS")

    def _fail(self, msg):
        self.error.set_text(msg)
        self.error.set_visible(True)

    def build(self):
        m = self.mem
        m.empty = False
        if self.new:
            m.number = int(self.number.get_value())
        m.name = self.name.get_text().strip()
        m.freq = chirp_common.parse_freq(self.rx.get_text().strip())
        m.duplex = self.duplexes[self.duplex.get_selected()]
        if m.duplex in ("+", "-", "split"):
            text = self.offset.get_text().strip()
            if not text:
                raise ValueError("Enter the offset (or transmit frequency for split).")
            m.offset = chirp_common.parse_freq(text)
        else:
            m.offset = 0
        m.power = self.levels[self.power.get_selected()]
        t = self.modes[self.tmode.get_selected()][0]
        if t != "Cross":
            m.tmode = t
            tone = self.tones[self.tone.get_selected()]
            if t == "Tone":
                m.rtone = tone
            elif t == "TSQL":
                m.ctone = m.rtone = tone
            elif t == "DTCS":
                m.dtcs = m.rx_dtcs = self.codes[self.dcs.get_selected()]
                m.dtcs_polarity = POLARITIES[self.pol.get_selected()]
        m.mode = self.widths[self.width.get_selected()][0]
        m.skip = "" if self.scan.get_active() else "S"
        return m

    def _save(self, *_):
        try:
            m = self.build()
        except ValueError as e:
            return self._fail(str(e) or "Check the frequency: use MHz, e.g. 476.425")
        if not m.freq:
            return self._fail("Enter a receive frequency in MHz, e.g. 476.425")
        if self.new and not self.radio.get_memory(m.number).empty:
            return self._fail(f"Channel {m.number} is already in use. Pick an empty number, or edit that channel.")
        problems = channels.errors_for(self.radio, m)
        if problems:
            return self._fail("\n".join(problems))
        self.on_save(m)
        self.close()
