from gi.repository import Adw, GLib, Gtk

from .. import names, presets

KEEP = "Keep current preset"
RATES = (44100, 48000, 88200, 96000, 176400, 192000)
TITLES = {
    "output": ("Output", "Play through", "Output Presets per Device"),
    "input": ("Input", "Record from", "Input Presets per Device"),
}


class DevicesPage(Adw.PreferencesPage):
    def __init__(self, controller):
        super().__init__(title="Devices", icon_name="audio-card-symbolic")
        self.controller = controller
        self.groups = []
        self._queued = 0
        controller.connect("devices-changed", lambda *_: self.queue_reload())
        for pipeline in controller.pipelines:
            pipeline.connect("preset-changed", lambda *_: self.queue_reload())
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
        for pipeline in self.controller.pipelines:
            self._add_pipeline(pipeline)
        return False

    def _add_pipeline(self, pipeline):
        title, choose, rules_title = TITLES[pipeline.direction]
        state = pipeline.state
        devices = pipeline.devices()

        group = Adw.PreferencesGroup(title=title)
        if devices:
            ids = [d.name for d in devices]
            row = Adw.ComboRow(title=choose, model=Gtk.StringList.new([d.description for d in devices]))
            if state["device"] in ids:
                row.set_selected(ids.index(state["device"]))
            row.connect("notify::selected", lambda r, _: pipeline.select_device(ids[r.get_selected()]))
            group.add(row)
        else:
            group.add(Adw.ActionRow(title="No devices found"))
        self._add(group)

        rules = Adw.PreferencesGroup(
            title=rules_title, description="Loaded automatically when Soundstage switches to the device")
        choices = [KEEP, *presets.list_presets(pipeline.direction)]
        known = {d.name: (d.description, d.description) for d in devices}
        for name, description in state["device_names"].items():
            known.setdefault(name, (f"{description} (not connected)", description))
        for name in state["device_presets"]:
            known.setdefault(name, (name, name))
        for name, (device_title, description) in sorted(known.items(), key=lambda kv: kv[1][0].casefold()):
            row = Adw.ComboRow(title=device_title, model=Gtk.StringList.new(choices), enable_search=True)
            current = state["device_presets"].get(name, KEEP)
            if current in choices:
                row.set_selected(choices.index(current))
            row.connect("notify::selected", self._on_rule, pipeline, name, choices)
            if names.renamable(name):
                edit = Gtk.Button(icon_name="document-edit-symbolic", tooltip_text="Device Settings",
                                  valign=Gtk.Align.CENTER, css_classes=["flat"])
                edit.connect("clicked", self._on_settings, pipeline, name, description)
                row.add_suffix(edit)
            rules.add(row)
        self._add(rules)

    def _add(self, group):
        self.add(group)
        self.groups.append(group)

    def _on_rule(self, row, _pspec, pipeline, name, choices):
        state = pipeline.state
        choice = choices[row.get_selected()]
        if choice == KEEP:
            state["device_presets"].pop(name, None)
        else:
            state["device_presets"][name] = choice
            if name == state["device"] and choice != state["preset"]:
                pipeline.load_preset(choice)
        self.controller.settings.save()

    def _on_settings(self, _button, pipeline, name, description):
        props = names.node_props(name)
        custom = props.get("node.description")
        dialog = Adw.AlertDialog(
            heading=f"{TITLES[pipeline.direction][0]} Device Settings",
            body=f"{description}\n\nThese apply everywhere, including GNOME's sound settings. "
                 "Audio pauses for a moment while they apply.")
        group = Adw.PreferencesGroup()
        entry = Adw.EntryRow(title="Name", text=custom or description, activates_default=True)
        awake = Adw.SwitchRow(title="Disable Suspend", subtitle="Keeps the device awake when nothing plays",
                              active=props.get(names.AWAKE) == 0)
        group.add(entry)
        group.add(awake)
        rate = None
        if name.startswith("alsa_"):
            rate = Adw.ComboRow(title="Sample Rate", model=Gtk.StringList.new(
                ["Automatic", *(f"{r / 1000:g} kHz" for r in RATES)]))
            if props.get(names.RATE) in RATES:
                rate.set_selected(RATES.index(props[names.RATE]) + 1)
            group.add(rate)
        dialog.set_extra_child(group)
        dialog.add_response("cancel", "Cancel")
        if custom:
            dialog.add_response("reset", "Reset Name")
        dialog.add_response("apply", "Apply")
        dialog.set_response_appearance("apply", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("apply")
        dialog.set_close_response("cancel")
        dialog.connect("response", self._on_settings_response, pipeline, name, description, entry, awake, rate)
        dialog.present(self.get_root())

    def _on_settings_response(self, _dialog, response, pipeline, name, description, entry, awake, rate):
        if response == "cancel":
            return
        old = names.node_props(name)
        new_name = "" if response == "reset" else entry.get_text().strip()
        if new_name == description and "node.description" not in old:
            new_name = ""
        changes = {
            "node.description": new_name or None,
            "node.nick": new_name or None,
            names.AWAKE: 0 if awake.get_active() else None,
            names.RATE: RATES[rate.get_selected() - 1] if rate and rate.get_selected() else None,
        }
        if all(old.get(key) == value for key, value in changes.items()):
            return
        try:
            names.update(name, changes)
        except OSError as e:
            self.get_root().toast(f"Could not change the device: {e.strerror}")
            return
        if new_name:
            pipeline.state["device_names"][name] = new_name
            self.controller.settings.save()
        # The chains lose their links when WirePlumber restarts, so start them afresh once it is back.
        names.restart_wireplumber(
            lambda: GLib.timeout_add_seconds(2, lambda: self.controller.restart_chains() or False))
        self.get_root().toast("Device settings applied")
