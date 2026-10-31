import sys
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gdk, Gio, Gtk  # noqa: E402

from . import config, migrate  # noqa: E402
from .controller import Controller  # noqa: E402

VERSION = "1.0.1"
DEVELOPER = "SolarFlare Developments"


class SkitzEffectsApplication(Adw.Application):
    def __init__(self):
        super().__init__(application_id=config.APP_ID, flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        from .ui.wizard import autostart_command

        migrate.from_soundstage(autostart_command())
        self.settings = config.load()
        self.controller = Controller(self.settings)
        self._held = False
        self.add_main_option("background", 0, 0, 0, "Start without opening a window", None)
        self._add_action("quit", self._on_quit, ["<primary>q"])
        self._add_action("about", self._on_about)
        self._add_action("setup", lambda *_: self.window().run_setup())

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
        if not background or not self.settings.setup_done:
            self.activate()
        return 0

    def do_startup(self):
        Adw.Application.do_startup(self)
        icons = Path(__file__).parent.parent / "data" / "icons"
        if icons.is_dir():
            Gtk.IconTheme.get_for_display(Gdk.Display.get_default()).add_search_path(str(icons))

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

    def _on_quit(self, *_):
        self.controller.shutdown()
        self.quit()

    def do_shutdown(self):
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


def main():
    return SkitzEffectsApplication().run(sys.argv)
