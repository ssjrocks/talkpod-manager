"""Fill the channels from a ready-made plan."""

from gi.repository import Adw, Gtk

from .. import plans
from .channel_dialog import power_label

REPEATER_CHOICES = [
    (100, "101–108 and 141–148 (channel + 100)"),
    (400, "401–408 and 441–448 (channel + 400)"),
    (None, "None"),
]


class PlanDialog(Adw.Dialog):
    def __init__(self, radio, on_apply):
        super().__init__(title="Channel plan", content_width=520, content_height=560)
        self.radio = radio
        self.on_apply = on_apply

        view = Adw.ToolbarView()
        header = Adw.HeaderBar(show_end_title_buttons=False, show_start_title_buttons=False)
        cancel = Gtk.Button(label="Cancel")
        cancel.connect("clicked", lambda *_: self.close())
        apply = Gtk.Button(label="Apply")
        apply.add_css_class("suggested-action")
        apply.connect("clicked", self._apply)
        header.pack_start(cancel)
        header.pack_end(apply)
        view.add_top_bar(header)
        page = Adw.PreferencesPage()
        view.set_content(page)
        self.set_child(view)

        g = Adw.PreferencesGroup(
            title="Australian UHF CB",
            description="Channels 1–80 (12.5 kHz). 22 and 23 are receive-only (data channels: no voice); "
                        "61–63 are reserved and left empty. Repeater channels receive on 1–8 / 41–48 "
                        "and transmit 750 kHz higher.")
        page.add(g)
        self.rpt = Adw.ComboRow(title="Repeater channels", model=Gtk.StringList.new([t for _, t in REPEATER_CHOICES]))
        g.add(self.rpt)
        self.inputs = Adw.SwitchRow(
            title="Allow transmitting on 31–38 and 71–78",
            subtitle="These are repeater inputs; ACMA asks for them not to be used for simplex.",
            active=True)
        g.add(self.inputs)
        levels = list(radio.POWER_LEVELS)
        self.power = Adw.ComboRow(title="Power", model=Gtk.StringList.new([power_label(p) for p in levels]))
        g.add(self.power)
        self.clear = Adw.SwitchRow(title="Clear all other channels", subtitle="So the arrow keys only step through the plan",
                                   active=True)
        g.add(self.clear)
        note = Adw.PreferencesGroup(description="This changes the image in the editor only. Use Write to send it to the radio.")
        page.add(note)

    def _apply(self, *_):
        base = REPEATER_CHOICES[self.rpt.get_selected()][0]
        mems = plans.au_uhf_cb(self.radio, repeater_base=base, tx_on_repeater_inputs=self.inputs.get_active(),
                               power_index=self.power.get_selected())
        plans.apply(self.radio, mems, clear_others=self.clear.get_active())
        self.on_apply(len(mems))
        self.close()
