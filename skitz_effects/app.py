import subprocess
import sys
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402

from . import config, deps, migrate  # noqa: E402
from .controller import Controller, _die_with_parent  # noqa: E402

VERSION = "1.0.1"
ICONS = Path(__file__).parent.parent / "data" / "icons"
DEVELOPER = "SolarFlare Developments"


class SkitzEffectsApplication(Adw.Application):
    def __init__(self):
        super().__init__(application_id=config.APP_ID, flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        from .ui.wizard import autostart_command

        migrate.from_soundstage(autostart_command())
        self.settings = config.load()
        self.controller = Controller(self.settings)
        self._held = False
        self._tray = None
        self.add_main_option("background", 0, 0, 0, "Start without opening a window", None)
        self._add_action("quit", self._on_quit, ["<primary>q"])
        self._add_action("about", self._on_about)
        self._add_action("setup", lambda *_: self.window().run_setup())
        self._add_action("preferences", lambda *_: self.window().show_preferences(), ["<primary>comma"])
        # The tray icon's menu uses these two over D-Bus.
        self._add_action("show", lambda *_: self.activate())
        output = self.controller.output
        self.effects = Gio.SimpleAction.new_stateful("effects", None, GLib.Variant("b", output.state["enabled"]))
        self.effects.connect("change-state", lambda _a, value: output.set_enabled(value.get_boolean()))
        self.add_action(self.effects)
        output.connect("state-changed", self._on_output_changed)

    def _add_action(self, name, callback, accels=None):
        action = Gio.SimpleAction.new(name, None)
        action.connect("activate", callback)
        self.add_action(action)
        if accels:
            self.set_accels_for_action(f"app.{name}", accels)

    def do_command_line(self, command_line):
        background = command_line.get_options_dict().contains("background")
        if self.settings.setup_done:
            self.controller.start()
            self.hold_in_background()
            self.set_tray(self.settings.show_tray)
        if not background or not self.settings.setup_done or not self.settings.run_in_background:
            self.activate()
        return 0

    def do_startup(self):
        Adw.Application.do_startup(self)
        if ICONS.is_dir():
            Gtk.IconTheme.get_for_display(Gdk.Display.get_default()).add_search_path(str(ICONS))

    def do_activate(self):
        window = self.window()
        window.present()
        if not self.settings.setup_done:
            window.run_setup(first_run=True)

    def window(self):
        from .ui.window import SkitzEffectsWindow

        if self.props.active_window is None:
            SkitzEffectsWindow(application=self)
        return self.props.active_window

    def hold_in_background(self):
        if self.settings.run_in_background and not self._held:
            self.hold()
            self._held = True
        elif not self.settings.run_in_background and self._held:
            self.release()
            self._held = False

    def _on_output_changed(self, output):
        if self.effects.get_state().get_boolean() != output.state["enabled"]:
            self.effects.set_state(GLib.Variant("b", output.state["enabled"]))

    def set_tray(self, on):
        """Starts or stops the tray icon, which needs a StatusNotifier host such as GNOME's AppIndicator extension."""
        running = self._tray is not None and self._tray.poll() is None
        if on and not running and _has_tray_host():
            # From a checkout the icon is not installed, so the tray host is given its file.
            icon = ICONS / "hicolor" / "symbolic" / "apps" / f"{config.ICON_NAME}-symbolic.svg"
            argv = [sys.executable, "-m", "skitz_effects.tray", config.APP_ID] + ([str(icon)] if icon.exists() else [])
            self._tray = subprocess.Popen(argv,
                                          preexec_fn=_die_with_parent, stdin=subprocess.DEVNULL)
        elif not on and running:
            self._tray.terminate()
            self._tray.wait(timeout=2)
            self._tray = None

    def set_autostart(self, on):
        from .ui.wizard import autostart_command

        deps.set_autostart(on, autostart_command(), self.settings.start_minimised)

    def _on_quit(self, *_):
        self.controller.shutdown()
        self.quit()

    def do_shutdown(self):
        self.set_tray(False)
        self.controller.shutdown()
        Adw.Application.do_shutdown(self)

    def _on_about(self, *_):
        about = Adw.AboutDialog(
            application_name="Skitz Effects",
            application_icon=config.ICON_NAME,
            developer_name=DEVELOPER,
            version=VERSION,
            copyright=f"© 2026 {DEVELOPER}",
            license_type=Gtk.License.GPL_3_0,
            comments="Audio effects for PipeWire with surround sound and HRIR downmixing",
        )
        about.present(self.props.active_window)


def _has_tray_host():
    bus = Gio.bus_get_sync(Gio.BusType.SESSION)
    reply = bus.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", "NameHasOwner",
                          GLib.Variant("(s)", ("org.kde.StatusNotifierWatcher",)), None, Gio.DBusCallFlags.NONE,
                          -1, None)
    return reply.unpack()[0]


def main():
    return SkitzEffectsApplication().run(sys.argv)
