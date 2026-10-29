from gi.repository import Adw, Gio, GLib, Gtk

from .. import plugins, presets
from .eq import EqualizerEditor
from .rows import full_names, menu_row, param_row

ADDABLE = [e for e in plugins.EFFECTS.values() if not e.missing]


class EffectsView(Adw.Bin):
    def __init__(self, pipeline, meters=None):
        super().__init__()
        self.pipeline = pipeline
        self.meters = meters
        self.selected = None

        self.list = Gtk.ListBox(css_classes=["navigation-sidebar"])
        self.list.connect("row-selected", self._on_row_selected)
        add = Gtk.MenuButton(css_classes=["flat"], halign=Gtk.Align.CENTER, popover=self._add_popover())
        add.set_child(Adw.ButtonContent(icon_name="list-add-symbolic", label="Add Effect"))
        sidebar = Adw.ToolbarView(content=Gtk.ScrolledWindow(child=self.list, vexpand=True))
        self.preset_button = Gtk.MenuButton(always_show_arrow=True, hexpand=True, tooltip_text="Preset",
                                            popover=self._presets_popover())
        top = Gtk.Box(margin_start=6, margin_end=6, margin_top=6, margin_bottom=6)
        top.append(self.preset_button)
        sidebar.add_top_bar(top)
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

    def _presets_popover(self):
        self.preset_list = Gtk.ListBox(css_classes=["navigation-sidebar"], selection_mode=Gtk.SelectionMode.NONE)
        self.preset_list.connect("row-activated", self._on_preset_activated)
        scroller = Gtk.ScrolledWindow(child=self.preset_list, propagate_natural_height=True, max_content_height=360,
                                      propagate_natural_width=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        self.new_name = Gtk.Entry(placeholder_text="New preset name", hexpand=True)
        self.new_name.connect("activate", self._on_new_preset)
        create = Gtk.Button(icon_name="list-add-symbolic", tooltip_text="Create Preset")
        create.connect("clicked", self._on_new_preset)
        new_box = Gtk.Box(spacing=6, css_classes=["linked"])
        new_box.append(self.new_name)
        new_box.append(create)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, width_request=280)
        box.append(scroller)
        box.append(new_box)
        popover = Gtk.Popover(child=box)
        popover.connect("show", lambda _p: self._fill_presets())
        return popover

    def _fill_presets(self):
        self.preset_list.remove_all()
        current = self.preset.name if self.preset else ""
        for name in presets.list_presets(self.pipeline.direction):
            row = menu_row(name, name == current)
            row.preset = name
            self.preset_list.append(row)

    def _on_preset_activated(self, _list, row):
        self.preset_button.popdown()
        self.pipeline.load_preset(row.preset)

    def _on_new_preset(self, *_):
        name = self.new_name.get_text().strip()
        if not name or "/" in name:
            return
        if name in presets.list_presets(self.pipeline.direction):
            self.get_root().toast(f"A preset called {name} already exists")
            return
        self.new_name.set_text("")
        self.preset_button.popdown()
        self.pipeline.new_preset(name)

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
        self.preset_button.set_label(self.preset.name if self.preset else "Choose a Preset")
        if self.preset is None:
            output = self.pipeline.direction == "output"
            icon = "audio-speakers-symbolic" if output else "audio-input-microphone-symbolic"
            self.content.set_content(Adw.StatusPage(
                icon_name=icon, title="No Preset Loaded",
                description="Choose a preset or create one with the button above the effects list"))
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
        if effect.kind == "equalizer":
            response = Adw.PreferencesGroup()
            response.add(EqualizerEditor(settings, on_change, self.meters))
            page.add(response)
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
        row = full_names(Adw.ComboRow(title="Impulse response", model=Gtk.StringList.new(names),
                                      enable_search=True))
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
