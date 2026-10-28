from gi.repository import Adw, Gtk

from .. import plugins

# Easy Effects' own wording for values that LSP labels differently.
DISPLAY = {new: old for old, new in plugins.ALIASES.items()}


def set_path(settings, key, value):
    *parents, last = key.split("/")
    for part in parents:
        settings = settings.setdefault(part, {})
    settings[last] = value


def param_row(param, settings, on_change, title=None):
    value = plugins.lookup(settings, param.key)
    title = title or param.label

    def changed(new):
        set_path(settings, param.key, new)
        on_change()

    if param.kind == "bool":
        row = Adw.SwitchRow(title=title, active=bool(value))
        row.connect("notify::active", lambda r, _: changed(r.get_active()))
        return row
    if param.kind == "enum":
        labels = [DISPLAY.get(o, o) for o in param.options]
        row = Adw.ComboRow(title=title, model=Gtk.StringList.new(labels))
        current = DISPLAY.get(plugins.ALIASES.get(value, value), value)
        if current in labels:
            row.set_selected(labels.index(current))
        row.connect("notify::selected", lambda r, _: changed(labels[r.get_selected()]))
        return row
    return spin_row(title, param, value, changed)


def spin_row(title, param, value, changed):
    value = param.lo if value is None else min(max(float(value), param.lo), param.hi)
    adjustment = Gtk.Adjustment(lower=param.lo, upper=param.hi, step_increment=param.step,
                                page_increment=param.step * 10, value=value)
    row = Adw.SpinRow(title=title, adjustment=adjustment, digits=param.digits, subtitle=param.unit)
    row.connect("notify::value", lambda r, _: changed(round(r.get_value(), max(param.digits, 2))))
    return row


def spin_button(param, value, changed):
    value = param.lo if value is None else min(max(float(value), param.lo), param.hi)
    adjustment = Gtk.Adjustment(lower=param.lo, upper=param.hi, step_increment=param.step,
                                page_increment=param.step * 10, value=value)
    button = Gtk.SpinButton(adjustment=adjustment, digits=param.digits, valign=Gtk.Align.CENTER)
    button.connect("value-changed", lambda b: changed(round(b.get_value(), max(param.digits, 2))))
    return button
