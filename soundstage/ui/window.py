from gi.repository import Adw, Gio, Gtk

from .. import deps, presets
from .devices import DevicesPage
from .effects import EffectsView
from .surround import SurroundPage


class SoundstageWindow(Adw.ApplicationWindow):
    def __init__(self, application):
        super().__init__(application=application, title="Soundstage", default_width=1000, default_height=700)
        self.controller = application.controller

        self.stack = Adw.ViewStack()
        self.effects = EffectsView(self.controller)
        self.stack.add_titled_with_icon(self.effects, "output", "Output", "audio-speakers-symbolic")
        self.stack.add_titled_with_icon(SurroundPage(self.controller), "surround", "Surround",
                                        "audio-headphones-symbolic")
        self.stack.add_titled_with_icon(DevicesPage(self.controller), "devices", "Devices", "audio-card-symbolic")

        header = Adw.HeaderBar()
        header.set_title_widget(Adw.ViewSwitcher(stack=self.stack, policy=Adw.ViewSwitcherPolicy.WIDE))
        self.presets_button = Gtk.MenuButton(always_show_arrow=True, tooltip_text="Presets")
        self.presets_button.set_popover(self._presets_popover())
        header.pack_start(self.presets_button)

        menu = Gio.Menu()
        menu.append("Run Setup Again", "app.setup")
        menu.append("About Soundstage", "app.about")
        menu.append("Quit", "app.quit")
        header.pack_end(Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu, primary=True,
                                       tooltip_text="Main Menu"))
        self.enabled = Gtk.Switch(active=self.controller.settings.enabled, valign=Gtk.Align.CENTER,
                                  tooltip_text="Effects on or off")
        self.enabled.connect("notify::active", lambda s, _: self.controller.set_enabled(s.get_active()))
        header.pack_end(self.enabled)

        self.banner = Adw.Banner(button_label="Set Up")
        self.banner.connect("button-clicked", lambda _b: self.run_setup())

        view = Adw.ToolbarView(content=self.stack)
        view.add_top_bar(header)
        view.add_top_bar(self.banner)
        bar = Adw.ViewSwitcherBar(stack=self.stack)
        view.add_bottom_bar(bar)
        self.toasts = Adw.ToastOverlay(child=view)
        self.set_content(self.toasts)

        breakpoint = Adw.Breakpoint.new(Adw.BreakpointCondition.parse("max-width: 600sp"))
        breakpoint.add_setter(bar, "reveal", True)
        breakpoint.add_setter(header, "title-widget", Adw.WindowTitle(title="Soundstage"))
        self.add_breakpoint(breakpoint)

        self.controller.connect("preset-changed", lambda *_: self._on_preset_changed())
        self.controller.connect("state-changed", lambda *_: self._update_banner())
        self._on_preset_changed()
        self._update_banner()

    def toast(self, text):
        self.toasts.add_toast(Adw.Toast(title=text))

    def _update_banner(self):
        missing = deps.missing()
        if missing:
            self.banner.set_title(f"Missing: {', '.join(c.title for c in missing)}")
            self.banner.set_button_label("Set Up")
            self.banner.set_revealed(True)
        elif self.controller.running and self.controller.output and not self.controller.chain_running:
            self.banner.set_title("The effects stopped unexpectedly")
            self.banner.set_button_label("")
            self.banner.set_revealed(True)
        else:
            self.banner.set_revealed(False)

    def _on_preset_changed(self):
        preset = self.controller.preset
        self.presets_button.set_label(preset.name if preset else "Presets")
        self.effects.reload()

    def _presets_popover(self):
        self.preset_list = Gtk.ListBox(css_classes=["navigation-sidebar"], selection_mode=Gtk.SelectionMode.NONE)
        self.preset_list.connect("row-activated", self._on_preset_activated)
        scroller = Gtk.ScrolledWindow(child=self.preset_list, propagate_natural_height=True, max_content_height=360,
                                      hscrollbar_policy=Gtk.PolicyType.NEVER)
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
        current = self.controller.preset.name if self.controller.preset else ""
        for name in presets.list_presets():
            row = Adw.ActionRow(title=name, activatable=True)
            row.preset = name
            if name == current:
                row.add_suffix(Gtk.Image(icon_name="object-select-symbolic"))
            self.preset_list.append(row)

    def _on_preset_activated(self, _list, row):
        self.presets_button.popdown()
        self.controller.load_preset(row.preset)

    def _on_new_preset(self, *_):
        name = self.new_name.get_text().strip()
        if not name or "/" in name:
            return
        if name in presets.list_presets():
            self.toast(f"A preset called {name} already exists")
            return
        self.new_name.set_text("")
        self.presets_button.popdown()
        self.controller.new_preset(name)

    def run_setup(self, first_run=False):
        from .wizard import SetupWizard

        SetupWizard(self.get_application(), first_run).present(self)
