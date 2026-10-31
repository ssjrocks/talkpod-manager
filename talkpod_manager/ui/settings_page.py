"""Radio settings (the menu items), generated from CHIRP's settings for the A36plus driver."""

import logging

from gi.repository import Adw, GObject, Gtk

from .. import features
from .. import radio as rio
from .. import tsf_settings
from . import settingrows

LOG = logging.getLogger(__name__)


class SettingsPage(Gtk.Box):
    __gsignals__ = {"changed": (GObject.SignalFlags.RUN_FIRST, None, ())}

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.radio = None
        self.firmware = None
        self.settings = None
        self.page = None

    def load(self, radio, firmware=None):
        """firmware: what the radio runs (radio.Firmware), None when unknown (an opened file)"""
        self.radio = radio
        self.firmware = firmware
        if self.page is not None:
            self.remove(self.page)
        self.page = Adw.PreferencesPage(vexpand=True)
        intro = Adw.PreferencesGroup(
            description="Hover over a setting to see what it does and when you'd change it. "
                        "“Radio menu” numbers match the menu on the radio. Changes here go into the "
                        "editor; use Write to send them to the radio.")
        self.page.add(intro)
        note = features.settings_note(firmware)
        if note:
            g = Adw.PreferencesGroup()
            row = Adw.ActionRow(title="This radio's firmware", subtitle=note, activatable=False)
            row.add_prefix(Gtk.Image(icon_name="dialog-information-symbolic"))
            g.add(row)
            self.page.add(g)
        if features.own_settings(firmware) or (firmware is None and tsf_settings.present(radio)):
            settingrows.add_group(self.page, tsf_settings.group(radio, firmware), self._changed)
        self.settings = radio.get_settings()
        hidden = rio.missing_settings(radio)
        for i, group in enumerate(self.settings):
            # Basic settings stay open; the long code/name lists start collapsed.
            settingrows.add_group(self.page, group, self._changed, collapse_over=None if i == 0 else 8,
                                  skip=hidden, sensitive=features.stock_settings_usable(firmware),
                                  unused=lambda name: features.unused_stock_setting(firmware, name))
        self.append(self.page)

    def _changed(self, setting):
        warning = setting.get_warning(setting.value) if hasattr(setting, "get_warning") else None
        if warning:
            LOG.info("setting %s warning: %s", setting.get_name(), warning)
        if tsf_settings.owns(setting):
            tsf_settings.apply(self.radio, setting, self.firmware)
        else:
            rio.apply_setting(self.radio, setting)
        self.emit("changed")

    def value(self, name):
        """Current value of a basic setting by CHIRP name (e.g. 'ponmsg')."""
        if not self.settings:
            return None
        for group in self.settings:
            for el in group:
                if getattr(el, "get_name", lambda: None)() == name:
                    return el.value
        return None
