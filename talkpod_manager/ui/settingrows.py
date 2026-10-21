"""Adwaita rows for CHIRP RadioSetting objects (radio settings and per-channel extras)."""

import logging

from gi.repository import Adw, Gtk

from .. import radio as _radio  # noqa: F401  (sets CHIRP_TESTENV before chirp is imported)
from chirp import settings as cs

LOG = logging.getLogger(__name__)


def _apply(setting, value, row, on_change):
    try:
        setting.value.set_value(value)
    except (cs.InvalidValueError, ValueError) as e:
        row.add_css_class("error")
        row.set_tooltip_text(str(e))
        return
    row.remove_css_class("error")
    row.set_tooltip_text(setting.__doc__ or None)
    if on_change:
        on_change(setting)


def row_for(setting, on_change=None):
    """An editable row for one setting, or a read-only row for kinds it can't edit."""
    title = setting.get_shortname()
    if len(setting) != 1:
        return Adw.ActionRow(title=title, subtitle=", ".join(str(v) for v in setting.value))
    v = setting.value

    if isinstance(v, cs.RadioSettingValueBoolean):
        row = Adw.SwitchRow(title=title, active=bool(v.get_value()))
        row.connect("notify::active", lambda r, _p: _apply(setting, r.get_active(), r, on_change))
    elif isinstance(v, cs.RadioSettingValueList):  # also RadioSettingValueMap
        options = [str(o) for o in v.get_options()]
        row = Adw.ComboRow(title=title, model=Gtk.StringList.new(options))
        current = str(v.get_value())
        if current in options:
            row.set_selected(options.index(current))
        row.connect("notify::selected", lambda r, _p: _apply(setting, options[r.get_selected()], r, on_change))
    elif isinstance(v, cs.RadioSettingValueInteger):
        adj = Gtk.Adjustment(lower=v.get_min(), upper=v.get_max(), step_increment=v.get_step(),
                             page_increment=v.get_step() * 10, value=int(v.get_value()))
        row = Adw.SpinRow(title=title, adjustment=adj, digits=0)
        row.connect("notify::value", lambda r, _p: _apply(setting, int(r.get_value()), r, on_change))
    elif isinstance(v, cs.RadioSettingValueFloat):
        adj = Gtk.Adjustment(lower=v.get_min(), upper=v.get_max(), step_increment=0.1,
                             page_increment=1.0, value=float(v.get_value()))
        row = Adw.SpinRow(title=title, adjustment=adj, digits=3)
        row.connect("notify::value", lambda r, _p: _apply(setting, r.get_value(), r, on_change))
    elif isinstance(v, cs.RadioSettingValueString):
        row = Adw.EntryRow(title=f"{title} (max {v.maxlength})", text=str(v.get_value()).rstrip())
        row.set_show_apply_button(True)
        row.connect("apply", lambda r: _apply(setting, r.get_text(), r, on_change))
    else:
        row = Adw.ActionRow(title=title, subtitle=str(v))

    row.set_sensitive(v.get_mutable())
    if setting.__doc__:
        row.set_tooltip_text(setting.__doc__)
    return row


def add_group(page, group, on_change, collapse_over=None, title=None, skip=()):
    """Add a RadioSettingGroup to an Adw.PreferencesPage. Groups longer than collapse_over go in
    an expander so the page stays scannable."""
    items = [el for el in group if el.get_name() not in skip]
    pg = Adw.PreferencesGroup(title=title or group.get_shortname())
    page.add(pg)
    target = pg
    if collapse_over is not None and len(items) > collapse_over:
        exp = Adw.ExpanderRow(title=f"{len(items)} settings", subtitle="Expand to edit")
        pg.add(exp)
        target = exp
    for el in items:
        if isinstance(el, cs.RadioSetting):
            row = row_for(el, on_change)
            if isinstance(target, Adw.ExpanderRow):
                target.add_row(row)
            else:
                target.add(row)
        else:  # nested group
            add_group(page, el, on_change, collapse_over, title=f"{pg.get_title()}: {el.get_shortname()}", skip=skip)
    return pg
