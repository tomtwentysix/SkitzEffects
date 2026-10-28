from gi.repository import Adw, GLib, Gtk

from .. import presets

KEEP = "Keep current preset"


class DevicesPage(Adw.PreferencesPage):
    def __init__(self, controller):
        super().__init__(title="Devices", icon_name="audio-card-symbolic")
        self.controller = controller
        self.groups = []
        self._queued = 0
        controller.connect("devices-changed", lambda *_: self.queue_reload())
        controller.connect("preset-changed", lambda *_: self.queue_reload())
        self.reload()

    def queue_reload(self):
        # Rows can trigger a reload from their own signal handlers, so rebuild afterwards.
        if not self._queued:
            self._queued = GLib.idle_add(self.reload)

    def reload(self):
        self._queued = 0
        for group in self.groups:
            self.remove(group)
        self.groups = []
        settings = self.controller.settings
        sinks = self.controller.pw.sinks() if self.controller.pw else []

        output = Adw.PreferencesGroup(title="Output")
        if sinks:
            row = Adw.ComboRow(title="Play through", model=Gtk.StringList.new([s.description for s in sinks]))
            names = [s.name for s in sinks]
            if settings.output_device in names:
                row.set_selected(names.index(settings.output_device))
            row.connect("notify::selected", lambda r, _: self.controller.select_output(names[r.get_selected()]))
            output.add(row)
        else:
            output.add(Adw.ActionRow(title="No output devices found"))
        self._add(output)

        rules = Adw.PreferencesGroup(
            title="Presets per Device",
            description="Loaded automatically when Soundstage switches to the device")
        choices = [KEEP, *presets.list_presets()]
        known = {s.name: f"{s.description}" for s in sinks}
        for name, description in settings.device_names.items():
            known.setdefault(name, f"{description} (not connected)")
        for name in settings.device_presets:
            known.setdefault(name, name)
        for name, title in sorted(known.items(), key=lambda kv: kv[1].casefold()):
            row = Adw.ComboRow(title=title, model=Gtk.StringList.new(choices), enable_search=True)
            current = settings.device_presets.get(name, KEEP)
            if current in choices:
                row.set_selected(choices.index(current))
            row.connect("notify::selected", self._on_rule, name, choices)
            rules.add(row)
        self._add(rules)
        return False

    def _add(self, group):
        self.add(group)
        self.groups.append(group)

    def _on_rule(self, row, _pspec, name, choices):
        settings = self.controller.settings
        choice = choices[row.get_selected()]
        if choice == KEEP:
            settings.device_presets.pop(name, None)
        else:
            settings.device_presets[name] = choice
            if name == settings.output_device and choice != settings.preset:
                self.controller.load_preset(choice)
        settings.save()
