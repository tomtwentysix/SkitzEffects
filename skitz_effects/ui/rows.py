from gi.repository import Adw, GObject, Gtk

from .. import plugins, sliders

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


def param_row(param, settings, on_change, title=None, tooltip=""):
    row = _param_row(param, settings, on_change, title)
    if tooltip:
        row.set_tooltip_text(tooltip)
    return row


def _param_row(param, settings, on_change, title=None):
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
    return slider_row(title, param, value, changed)


class SliderRow(Adw.ActionRow):
    __gsignals__ = {"value-changed": (GObject.SignalFlags.RUN_FIRST, None, ())}

    def __init__(self, title, param, value):
        super().__init__(title=title, subtitle=param.unit)
        self.param = param
        self._value = param.lo
        self._syncing = False
        self.scale = Gtk.Scale(adjustment=Gtk.Adjustment(lower=0, upper=1, step_increment=0.005, page_increment=0.05),
                               draw_value=False, hexpand=True, width_request=220, valign=Gtk.Align.CENTER)
        self.scale.connect("value-changed", self._on_scale)
        self.entry = Gtk.Entry(width_chars=7, max_width_chars=9, xalign=1, valign=Gtk.Align.CENTER,
                               input_purpose=Gtk.InputPurpose.NUMBER)
        self.entry.connect("activate", lambda _e: self._on_entry())
        focus = Gtk.EventControllerFocus()
        focus.connect("leave", lambda _c: self._on_entry())
        self.entry.add_controller(focus)
        self.add_suffix(self.scale)
        self.add_suffix(self.entry)
        self.set_value(param.lo if value is None else value)

    def get_value(self):
        return self._value

    def set_value(self, value):
        self._value = min(max(float(value), self.param.lo), self.param.hi)
        self._syncing = True
        self.scale.set_value(sliders.position(self.param, self._value))
        self.entry.set_text(f"{self._value:.{self.param.digits}f}")
        self._syncing = False

    def _changed(self, value):
        if value != self._value:
            self.set_value(value)
            self.emit("value-changed")
        else:
            self.set_value(value)

    def _on_scale(self, scale):
        if not self._syncing:
            self._changed(sliders.value_at(self.param, scale.get_value()))

    def _on_entry(self):
        try:
            value = float(self.entry.get_text().replace(",", "."))
        except ValueError:
            self.set_value(self._value)
            return
        self._changed(min(max(value, self.param.lo), self.param.hi))


def slider_row(title, param, value, changed):
    row = SliderRow(title, param, value)
    row.connect("value-changed", lambda r: changed(round(r.get_value(), max(param.digits, 2))))
    return row
