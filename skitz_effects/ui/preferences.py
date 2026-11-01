from gi.repository import Adw

from .. import deps


class PreferencesDialog(Adw.PreferencesDialog):
    def __init__(self, application):
        super().__init__(title="Preferences")
        self.app = application
        self.settings = application.settings

        page = Adw.PreferencesPage()
        self.add(page)

        startup = Adw.PreferencesGroup(title="Startup")
        self.autostart_row = Adw.SwitchRow(title="Start at login", active=deps.autostart_enabled())
        self.minimised_row = Adw.SwitchRow(title="Start minimised", subtitle="Run at login without opening the window",
                                           active=self.settings.start_minimised)
        startup.add(self.autostart_row)
        startup.add(self.minimised_row)
        page.add(startup)

        running = Adw.PreferencesGroup(title="Running")
        self.background_row = Adw.SwitchRow(
            title="Keep running when the window is closed",
            subtitle="Effects only apply while Skitz Effects is running", active=self.settings.run_in_background)
        self.tray_row = Adw.SwitchRow(title="Show in system tray",
                                      subtitle="Needs the AppIndicator extension on GNOME",
                                      active=self.settings.show_tray)
        running.add(self.background_row)
        running.add(self.tray_row)
        page.add(running)

        setup = Adw.PreferencesGroup(
            title="Setup", description="Check the required software and choose your surround and HRIR settings again.")
        button = Adw.ButtonRow(title="Run Setup Again", end_icon_name="go-next-symbolic")
        button.connect("activated", self._on_setup)
        setup.add(button)
        page.add(setup)

        self.autostart_row.connect("notify::active", self._on_autostart)
        self.minimised_row.connect("notify::active", self._on_minimised)
        self.background_row.connect("notify::active", self._on_background)
        self.tray_row.connect("notify::active", self._on_tray)
        self._sync()

    def _sync(self):
        # Starting minimised needs a launch at login and an app that stays up with no window.
        self.minimised_row.set_sensitive(self.autostart_row.get_active() and self.background_row.get_active())

    def _on_autostart(self, row, _):
        self.app.set_autostart(row.get_active())
        self._sync()

    def _on_minimised(self, row, _):
        self.settings.start_minimised = row.get_active()
        self.settings.save()
        if deps.autostart_enabled():
            self.app.set_autostart(True)

    def _on_background(self, row, _):
        self.settings.run_in_background = row.get_active()
        self.settings.save()
        self.app.hold_in_background()
        self._sync()

    def _on_tray(self, row, _):
        self.settings.show_tray = row.get_active()
        self.settings.save()
        self.app.set_tray(row.get_active())

    def _on_setup(self, _row):
        self.close()
        self.app.activate_action("setup")
