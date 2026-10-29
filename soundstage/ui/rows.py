from gi.repository import Adw, Gtk

from .. import plugins

# Easy Effects' own wording for values that LSP labels differently.
DISPLAY = {new: old for old, new in plugins.ALIASES.items()}


def menu_row(label, checked):
    """A compact list row for popovers: the label and, for the current choice, a check mark."""
    box = Gtk.Box(spacing=12, margin_start=6, margin_end=6, margin_top=4, margin_bottom=4)
    box.append(Gtk.Label(label=label, xalign=0, hexpand=True))
    box.append(Gtk.Image(icon_name="object-select-symbolic", opacity=1 if checked else 0))
    return Gtk.ListBoxRow(child=box)


def full_names(row):
    """Shows a combo row's choices unshortened; the default list cuts long device names short."""
    bound = []

    def setup(_factory, item):
        box = Gtk.Box(spacing=12)
        box.append(Gtk.Label(xalign=0, hexpand=True))
        box.append(Gtk.Image(icon_name="object-select-symbolic"))
        item.set_child(box)

    def bind(_factory, item):
        label, check = item.get_child().get_first_child(), item.get_child().get_last_child()
        label.set_label(item.get_item().get_string())
        check.set_opacity(1 if item.get_position() == row.get_selected() else 0)
        bound.append(item)

    def unbind(_factory, item):
        if item in bound:
            bound.remove(item)

    def selected(*_):
        for item in bound:
            item.get_child().get_last_child().set_opacity(1 if item.get_position() == row.get_selected() else 0)

    factory = Gtk.SignalListItemFactory()
    factory.connect("setup", setup)
    factory.connect("bind", bind)
    factory.connect("unbind", unbind)
    row.set_list_factory(factory)
    row.connect("notify::selected", selected)
    return row


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
