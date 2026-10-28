from gi.repository import Adw, GLib, Gtk

from .. import names, presets

KEEP = "Keep current preset"
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
                edit = Gtk.Button(icon_name="document-edit-symbolic", tooltip_text="Rename Device",
                                  valign=Gtk.Align.CENTER, css_classes=["flat"])
                edit.connect("clicked", self._on_rename, pipeline, name, description)
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

    def _on_rename(self, _button, pipeline, name, description):
        dialog = Adw.AlertDialog(
            heading="Rename Device",
            body="The new name shows everywhere, including GNOME's sound settings. "
                 "Audio pauses for a moment while it applies.")
        entry = Gtk.Entry(text=description, activates_default=True)
        dialog.set_extra_child(entry)
        dialog.add_response("cancel", "Cancel")
        if ("node", name) in names.custom():
            dialog.add_response("reset", "Reset Name")
        dialog.add_response("rename", "Rename")
        dialog.set_response_appearance("rename", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("rename")
        dialog.set_close_response("cancel")
        dialog.connect("response", self._on_rename_response, entry, pipeline, name)
        dialog.present(self.get_root())

    def _on_rename_response(self, _dialog, response, entry, pipeline, name):
        new = entry.get_text().strip() if response == "rename" else ""
        if response == "cancel" or (response == "rename" and not new):
            return
        try:
            names.rename(name, new)
        except OSError as e:
            self.get_root().toast(f"Could not rename the device: {e.strerror}")
            return
        if new:
            pipeline.state["device_names"][name] = new
            self.controller.settings.save()
        # The chains lose their links when WirePlumber restarts, so start them afresh once it is back.
        names.restart_wireplumber(
            lambda: GLib.timeout_add_seconds(2, lambda: self.controller.restart_chains() or False))
        self.get_root().toast("Renamed" if new else "Name reset")
