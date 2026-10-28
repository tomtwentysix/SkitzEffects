from gi.repository import Adw, Gio, GLib, Gtk

from .. import plugins, presets
from .rows import param_row, set_path, spin_button

EQ_GAIN = plugins.Param("gain", "", label="Gain", lo=-36, hi=36, step=0.1, unit="dB")
EQ_BAND = (
    plugins.Param("type", "", "enum", plugins.EQ_TYPES, "Type"),
    plugins.Param("mode", "", "enum", plugins.EQ_MODES, "Mode"),
    plugins.Param("slope", "", "enum", plugins.EQ_SLOPES, "Slope"),
    plugins.Param("frequency", "", label="Frequency", lo=10, hi=24000, step=1, digits=0, unit="Hz"),
    plugins.Param("q", "", label="Quality", lo=0, hi=100, step=0.01, digits=2),
    plugins.Param("width", "", label="Width", lo=0, hi=12, step=0.1, unit="octaves"),
    plugins.Param("mute", "", "bool", label="Mute"),
    plugins.Param("solo", "", "bool", label="Solo"),
)
ADDABLE = [e for e in plugins.EFFECTS.values() if not e.missing]


def frequency_label(hz):
    return f"{hz / 1000:g} kHz" if hz >= 1000 else f"{hz:g} Hz"


class EffectsView(Adw.Bin):
    def __init__(self, pipeline):
        super().__init__()
        self.pipeline = pipeline
        self.selected = None

        self.list = Gtk.ListBox(css_classes=["navigation-sidebar"])
        self.list.connect("row-selected", self._on_row_selected)
        add = Gtk.MenuButton(css_classes=["flat"], halign=Gtk.Align.CENTER, popover=self._add_popover())
        add.set_child(Adw.ButtonContent(icon_name="list-add-symbolic", label="Add Effect"))
        sidebar = Adw.ToolbarView(content=Gtk.ScrolledWindow(child=self.list, vexpand=True))
        bottom = Gtk.ActionBar()
        bottom.set_center_widget(add)
        sidebar.add_bottom_bar(bottom)

        self.content = Adw.ToolbarView()
        self.split = Adw.NavigationSplitView(
            sidebar=Adw.NavigationPage(title="Effects", child=sidebar),
            content=Adw.NavigationPage(title="Effect", child=self.content),
            min_sidebar_width=240,
        )
        self.set_child(self.split)
        self.reload()

    @property
    def preset(self):
        return self.pipeline.preset

    def _add_popover(self):
        menu = Gio.Menu()
        for e in sorted(ADDABLE, key=lambda e: e.title):
            menu.append(e.title, f"effects.add('{e.kind}')")
        action = Gio.SimpleAction.new("add", GLib.VariantType.new("s"))
        action.connect("activate", lambda _a, kind: self._add(kind.get_string()))
        group = Gio.SimpleActionGroup()
        group.add_action(action)
        self.insert_action_group("effects", group)
        return Gtk.PopoverMenu(menu_model=menu)

    def _add(self, kind):
        if self.preset is None:
            return
        effect_id = self.preset.add(kind)
        self.pipeline.changed(effect_id, structural=True)
        self.reload(select=effect_id)

    def reload(self, select=None):
        self.list.remove_all()
        if self.preset is None:
            output = self.pipeline.direction == "output"
            icon = "audio-speakers-symbolic" if output else "audio-input-microphone-symbolic"
            self.content.set_content(Adw.StatusPage(
                icon_name=icon, title="No Preset Loaded",
                description="Choose a preset from the menu above, or create a new one"))
            return
        target = None
        for effect_id in self.preset.order:
            row = self._row(effect_id)
            self.list.append(row)
            if effect_id == (select or self.selected):
                target = row
        target = target or self.list.get_row_at_index(0)
        if target:
            self.list.select_row(target)
        else:
            self.content.set_content(Adw.StatusPage(
                icon_name="list-add-symbolic", title="No Effects",
                description="Add an effect to start shaping the sound"))

    def _row(self, effect_id):
        effect = plugins.effect(presets.kind_of(effect_id))
        row = Adw.ActionRow(title=effect.title)
        row.effect_id = effect_id
        if not effect.available():
            row.set_subtitle("Unavailable")
        switch = Gtk.Switch(active=self.preset.enabled(effect_id), valign=Gtk.Align.CENTER,
                            tooltip_text="Enabled")
        switch.connect("notify::active", lambda s, _: self._toggle(effect_id, s.get_active()))
        row.add_suffix(switch)
        return row

    def _toggle(self, effect_id, on):
        if self.preset.enabled(effect_id) != on:
            self.preset.set_enabled(effect_id, on)
            self.pipeline.changed(effect_id, structural=True)

    def _on_row_selected(self, _list, row):
        if row is None:
            return
        self.selected = row.effect_id
        self._show(row.effect_id)
        self.split.set_show_content(True)

    def _show(self, effect_id):
        effect = plugins.effect(presets.kind_of(effect_id))
        header = Adw.HeaderBar(show_start_title_buttons=False, show_end_title_buttons=False)
        header.set_title_widget(Adw.WindowTitle(title=effect.title))
        remove = Gtk.Button(icon_name="user-trash-symbolic", tooltip_text="Remove Effect")
        remove.connect("clicked", lambda _b: self._remove(effect_id))
        up = Gtk.Button(icon_name="go-up-symbolic", tooltip_text="Move Up")
        up.connect("clicked", lambda _b: self._move(effect_id, -1))
        down = Gtk.Button(icon_name="go-down-symbolic", tooltip_text="Move Down")
        down.connect("clicked", lambda _b: self._move(effect_id, 1))
        for button in (remove, down, up):
            header.pack_end(button)
        self.content = Adw.ToolbarView()
        self.content.add_top_bar(header)
        self.content.set_content(self._page(effect_id, effect))
        self.split.get_content().set_child(self.content)
        self.split.get_content().set_title(effect.title)

    def _remove(self, effect_id):
        self.preset.remove(effect_id)
        self.selected = None
        self.pipeline.changed(effect_id, structural=True)
        self.reload()

    def _move(self, effect_id, offset):
        self.preset.move(effect_id, offset)
        self.pipeline.changed(effect_id, structural=True)
        self.reload(select=effect_id)

    def _page(self, effect_id, effect):
        if effect.missing or not effect.available():
            reason = effect.missing or f"Install {effect.package} to use this effect"
            return Adw.StatusPage(icon_name="dialog-warning-symbolic", title="Effect Unavailable",
                                  description=f"{reason}. Its settings are kept in the preset.")
        settings = self.preset.settings(effect_id)
        page = Adw.PreferencesPage()

        def on_change(structural=False):
            self.pipeline.changed(effect_id, structural)

        if effect.kind == "convolver":
            page.add(self._convolver_group(settings, on_change))
        group = Adw.PreferencesGroup()
        for param in effect.shown():
            group.add(param_row(param, settings, (lambda: on_change(True)) if effect.kind == "convolver"
                                else on_change))
        page.add(group)
        if effect.kind == "equalizer":
            self._equalizer_groups(page, settings, on_change)
        return page

    def _convolver_group(self, settings, on_change):
        group = Adw.PreferencesGroup(title="Impulse Response")
        irs = presets.list_irs()
        names = ["None", *irs]
        current = settings.get("kernel-name", "")
        row = Adw.ComboRow(title="Impulse response", model=Gtk.StringList.new(names),
                           enable_search=True)
        if current in irs:
            row.set_selected(names.index(current))

        def picked(r, _):
            settings["kernel-name"] = "" if r.get_selected() == 0 else names[r.get_selected()]
            settings.pop("kernel-path", None)
            on_change(True)

        row.connect("notify::selected", picked)
        group.add(row)
        return group

    def _equalizer_groups(self, page, settings, on_change):
        bands = Adw.PreferencesGroup(title="Bands")
        count = plugins.Param("num-bands", "", label="Number of bands", lo=1, hi=plugins.EQ_BANDS, step=1,
                              digits=0)
        bands.add(param_row(count, settings, lambda: (on_change(), self._show(self.selected))))
        split = plugins.Param("split-channels", "", "bool", label="Separate left and right")
        bands.add(param_row(split, settings, lambda: (on_change(), self._show(self.selected))))
        page.add(bands)
        sides = ("left", "right") if settings.get("split-channels") else ("left",)
        for side in sides:
            group = Adw.PreferencesGroup(title={"left": "Left", "right": "Right"}[side] if len(sides) > 1 else "")
            for i in range(int(settings.get("num-bands", 10))):
                group.add(self._band_row(settings, side, i, on_change))
            page.add(group)

    def _band_row(self, settings, side, i, on_change):
        band = settings.setdefault(side, {}).setdefault(f"band{i}", dict(presets.DEFAULTS["equalizer"]["left"].get(
            f"band{i}", {"frequency": 1000.0, "gain": 0.0, "type": "Bell", "q": 1.5})))
        row = Adw.ExpanderRow(title=frequency_label(band.get("frequency", 1000)),
                              subtitle=band.get("type", "Bell"))

        def gain_changed(value):
            set_path(band, "gain", value)
            on_change()

        row.add_suffix(spin_button(EQ_GAIN, band.get("gain", 0.0), gain_changed))

        def band_changed():
            row.set_title(frequency_label(band.get("frequency", 1000)))
            row.set_subtitle(band.get("type", "Bell"))
            on_change()

        for param in EQ_BAND:
            row.add_row(param_row(param, band, band_changed))
        return row
