from gi.repository import Adw, Gio, Gtk

from .. import deps
from ..levels import Meters
from .analyser import Spectrum
from .devices import DevicesPage
from .effects import EffectsView
from .mixer import MixerPage
from .rows import menu_row
from .statusbar import StatusBar


class SkitzEffectsWindow(Adw.ApplicationWindow):
    def __init__(self, application):
        super().__init__(application=application, title="Skitz Effects", default_width=1000, default_height=700)
        self.controller = application.controller
        self.pipeline = self.controller.output
        self._binding = False
        self._banner_action = None

        self.meters = Meters(self.controller)
        self.stack = Adw.ViewStack()
        self.views = {d: EffectsView(getattr(self.controller, d), self.meters) for d in ("output", "input")}
        self.stack.add_titled_with_icon(self.views["output"], "output", "Output", "audio-speakers-symbolic")
        self.stack.add_titled_with_icon(self.views["input"], "input", "Input", "audio-input-microphone-symbolic")
        self.stack.add_titled_with_icon(MixerPage(self.controller), "mixer", "Mixer", "audio-volume-high-symbolic")
        self.stack.add_titled_with_icon(DevicesPage(self.controller), "devices", "Devices", "audio-card-symbolic")
        self.stack.connect("notify::visible-child-name", lambda *_: self._on_page_changed())

        header = Adw.HeaderBar()
        header.set_title_widget(Adw.ViewSwitcher(stack=self.stack, policy=Adw.ViewSwitcherPolicy.WIDE))
        self.devices_button = Gtk.MenuButton(always_show_arrow=True, tooltip_text="Device")
        self.devices_button.set_popover(self._devices_popover())
        header.pack_start(self.devices_button)

        menu = Gio.Menu()
        menu.append("Preferences", "app.preferences")
        menu.append("About Skitz Effects", "app.about")
        menu.append("Quit", "app.quit")
        header.pack_end(Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu, primary=True,
                                       tooltip_text="Main Menu"))
        self.enabled = Gtk.Switch(valign=Gtk.Align.CENTER, tooltip_text="Effects on or off")
        self.enabled.connect("notify::active", self._on_enabled)
        header.pack_end(self.enabled)

        self.banner = Adw.Banner()
        self.banner.connect("button-clicked", lambda _b: self._banner_action and self._banner_action())

        self.spectrum = Gtk.Revealer(child=Spectrum(self.meters, self.controller.settings))

        view = Adw.ToolbarView(content=self.stack)
        view.add_top_bar(header)
        view.add_top_bar(self.banner)
        view.add_top_bar(self.spectrum)
        view.add_bottom_bar(StatusBar(self.controller, self.meters))
        bar = Adw.ViewSwitcherBar(stack=self.stack)
        view.add_bottom_bar(bar)
        self.toasts = Adw.ToastOverlay(child=view)
        self.set_content(self.toasts)

        breakpoint = Adw.Breakpoint.new(Adw.BreakpointCondition.parse("max-width: 600sp"))
        breakpoint.add_setter(bar, "reveal", True)
        breakpoint.add_setter(header, "title-widget", Adw.WindowTitle(title="Skitz Effects"))
        self.add_breakpoint(breakpoint)

        for pipeline in self.controller.pipelines:
            pipeline.connect("preset-changed", self._on_preset_changed)
            pipeline.connect("state-changed", self._on_state_changed)
        self.controller.connect("conflicts-changed", lambda *_: self._update_banner())
        self.controller.connect("devices-changed", lambda *_: self._update_device_label())
        # Metering only runs while the window is on screen.
        self.connect("map", lambda *_: self.meters.start())
        self.connect("unmap", lambda *_: self.meters.stop())
        self._on_page_changed()
        self._update_banner()

    def toast(self, text):
        self.toasts.add_toast(Adw.Toast(title=text))

    def _on_page_changed(self):
        page = self.stack.get_visible_child_name()
        effects_page = page in self.views
        self.devices_button.set_visible(effects_page)
        self.enabled.set_visible(effects_page)
        self.spectrum.set_reveal_child(effects_page)
        self.meters.show(page if effects_page else "output")
        if not effects_page:
            return
        self.pipeline = getattr(self.controller, page)
        self._binding = True
        self.enabled.set_active(self.pipeline.state["enabled"])
        self._binding = False
        self._update_device_label()

    def _on_enabled(self, switch, _pspec):
        if not self._binding:
            self.pipeline.set_enabled(switch.get_active())

    def _update_device_label(self):
        device = self.pipeline.device
        icon = "audio-speakers-symbolic" if self.pipeline.direction == "output" else "audio-input-microphone-symbolic"
        label = self.pipeline.display_name(device) if device else "No Device"
        content = Adw.ButtonContent(icon_name=icon, label=label, can_shrink=True)
        self.devices_button.set_child(content)

    def _on_preset_changed(self, pipeline):
        self.views[pipeline.direction].reload()

    def _on_state_changed(self, pipeline):
        self._update_banner()
        if pipeline is self.pipeline:
            self._update_device_label()
            if self.enabled.get_active() != pipeline.state["enabled"]:
                self._binding = True
                self.enabled.set_active(pipeline.state["enabled"])
                self._binding = False

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
            self._show_banner(f"{names} {verb} running and will fight Skitz Effects over your audio", "Turn Off",
                              lambda: self._turn_off(conflicts))
        elif stopped:
            self._show_banner("The effects stopped unexpectedly", "Restart", self.controller.restart_chains)
        else:
            self.banner.set_revealed(False)

    def _turn_off(self, conflicts):
        for conflict in conflicts:
            conflict.turn_off()
        self.toast(f"Turned off {' and '.join(c.title for c in conflicts)}")

    def _devices_popover(self):
        self.device_list = Gtk.ListBox(css_classes=["navigation-sidebar"], selection_mode=Gtk.SelectionMode.NONE)
        self.device_list.connect("row-activated", self._on_device_activated)
        scroller = Gtk.ScrolledWindow(child=self.device_list, propagate_natural_height=True, max_content_height=400,
                                      propagate_natural_width=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        popover = Gtk.Popover(child=scroller)
        popover.connect("show", lambda _p: self._fill_devices())
        return popover

    def _fill_devices(self):
        self.device_list.remove_all()
        for device in self.pipeline.devices():
            row = menu_row(self.pipeline.display_name(device), device.name == self.pipeline.state["device"])
            row.device = device.name
            self.device_list.append(row)

    def _on_device_activated(self, _list, row):
        self.devices_button.popdown()
        self.pipeline.select_device(row.device)

    def show_preferences(self):
        from .preferences import PreferencesDialog

        PreferencesDialog(self.get_application()).present(self)

    def run_setup(self, first_run=False):
        from .wizard import SetupWizard

        SetupWizard(self.get_application(), first_run).present(self)
