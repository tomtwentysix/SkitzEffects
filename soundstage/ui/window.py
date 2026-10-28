from gi.repository import Adw, Gio, Gtk

from .. import deps, presets
from .devices import DevicesPage
from .effects import EffectsView
from .surround import SurroundPage


class SoundstageWindow(Adw.ApplicationWindow):
    def __init__(self, application):
        super().__init__(application=application, title="Soundstage", default_width=1000, default_height=700)
        self.controller = application.controller
        self.pipeline = self.controller.output
        self._binding = False
        self._banner_action = None

        self.stack = Adw.ViewStack()
        self.views = {"output": EffectsView(self.controller.output), "input": EffectsView(self.controller.input)}
        self.stack.add_titled_with_icon(self.views["output"], "output", "Output", "audio-speakers-symbolic")
        self.stack.add_titled_with_icon(self.views["input"], "input", "Input", "audio-input-microphone-symbolic")
        self.stack.add_titled_with_icon(SurroundPage(self.controller), "surround", "Surround",
                                        "audio-headphones-symbolic")
        self.stack.add_titled_with_icon(DevicesPage(self.controller), "devices", "Devices", "audio-card-symbolic")
        self.stack.connect("notify::visible-child-name", lambda *_: self._on_page_changed())

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
        self.enabled = Gtk.Switch(valign=Gtk.Align.CENTER, tooltip_text="Effects on or off")
        self.enabled.connect("notify::active", self._on_enabled)
        header.pack_end(self.enabled)

        self.banner = Adw.Banner()
        self.banner.connect("button-clicked", lambda _b: self._banner_action and self._banner_action())

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

        for pipeline in self.controller.pipelines:
            pipeline.connect("preset-changed", self._on_preset_changed)
            pipeline.connect("state-changed", lambda *_: self._update_banner())
        self.controller.connect("conflicts-changed", lambda *_: self._update_banner())
        self._on_page_changed()
        self._update_banner()

    def toast(self, text):
        self.toasts.add_toast(Adw.Toast(title=text))

    def _on_page_changed(self):
        page = self.stack.get_visible_child_name()
        effects_page = page in self.views
        self.presets_button.set_visible(effects_page)
        self.enabled.set_visible(effects_page)
        if not effects_page:
            return
        self.pipeline = getattr(self.controller, page)
        self._binding = True
        self.enabled.set_active(self.pipeline.state["enabled"])
        self._binding = False
        self._update_presets_label()

    def _on_enabled(self, switch, _pspec):
        if not self._binding:
            self.pipeline.set_enabled(switch.get_active())

    def _update_presets_label(self):
        preset = self.pipeline.preset
        self.presets_button.set_label(preset.name if preset else "Presets")

    def _on_preset_changed(self, pipeline):
        self.views[pipeline.direction].reload()
        if pipeline is self.pipeline:
            self._update_presets_label()

    def _show_banner(self, title, button="", action=None):
        self.banner.set_title(title)
        self.banner.set_button_label(button)
        self._banner_action = action
        self.banner.set_revealed(True)

    def _update_banner(self):
        missing = deps.missing()
        stopped = [p for p in self.controller.pipelines
                   if self.controller.running and p.device and not p.chain_running]
        conflicts = self.controller.conflicts
        if missing:
            self._show_banner(f"Missing: {', '.join(c.title for c in missing)}", "Set Up", self.run_setup)
        elif conflicts:
            names = " and ".join(c.title for c in conflicts)
            verb = "are" if len(conflicts) > 1 else "is"
            self._show_banner(f"{names} {verb} running and will fight Soundstage over your audio", "Turn Off",
                              lambda: self._turn_off(conflicts))
        elif stopped:
            self._show_banner("The effects stopped unexpectedly", "Restart", self.controller.restart_chains)
        else:
            self.banner.set_revealed(False)

    def _turn_off(self, conflicts):
        for conflict in conflicts:
            conflict.turn_off()
        self.toast(f"Turned off {' and '.join(c.title for c in conflicts)}")

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
        current = self.pipeline.preset.name if self.pipeline.preset else ""
        for name in presets.list_presets(self.pipeline.direction):
            row = Adw.ActionRow(title=name, activatable=True)
            row.preset = name
            if name == current:
                row.add_suffix(Gtk.Image(icon_name="object-select-symbolic"))
            self.preset_list.append(row)

    def _on_preset_activated(self, _list, row):
        self.presets_button.popdown()
        self.pipeline.load_preset(row.preset)

    def _on_new_preset(self, *_):
        name = self.new_name.get_text().strip()
        if not name or "/" in name:
            return
        if name in presets.list_presets(self.pipeline.direction):
            self.toast(f"A preset called {name} already exists")
            return
        self.new_name.set_text("")
        self.presets_button.popdown()
        self.pipeline.new_preset(name)

    def run_setup(self, first_run=False):
        from .wizard import SetupWizard

        SetupWizard(self.get_application(), first_run).present(self)
