from gi.repository import Adw, GLib, Gtk

from .. import names, presets
from ..controller import input_variants
from .rows import full_names
from .surround import SurroundGroup

KEEP = "Keep current preset"
POSITION_NAMES = {"FL": "left", "FR": "right", "MONO": "mono"}
# ALSA's input profiles by the part of their name after "input:".
INPUT_PROFILES = {"analog-stereo-input": "Both inputs (stereo)", "analog-stereo": "Both inputs (stereo)",
                  "analog-mono-left": "Input 1 only", "analog-mono-right": "Input 2 only",
                  "analog-mono": "Both inputs mixed to mono", "mono-fallback": "Mono"}
RATES = (44100, 48000, 88200, 96000, 176400, 192000)
TITLES = {"output": ("Output", "Outputs"), "input": ("Input", "Inputs")}


def rate_label(rate):
    return f"{rate / 1000:g} kHz"


def channel_label(i, position):
    return f"Channel {i + 1} ({POSITION_NAMES.get(position, position)})"


class DevicesPage(Adw.PreferencesPage):
    def __init__(self, controller):
        super().__init__(title="Devices", icon_name="audio-card-symbolic")
        self.controller = controller
        self.groups = []
        self.surround = SurroundGroup(controller)
        self._queued = 0
        controller.connect("devices-changed", lambda *_: self.queue_reload())
        for pipeline in controller.pipelines:
            pipeline.connect("preset-changed", lambda *_: self.queue_reload())
            pipeline.connect("state-changed", lambda *_: self.queue_reload())
        self.reload()

    def queue_reload(self):
        # Rows can trigger a reload from their own signal handlers, so rebuild afterwards.
        if not self._queued:
            self._queued = GLib.idle_add(self.reload)

    def reload(self):
        self._queued = 0
        for group in self.groups:
            self.remove(group)
        self.groups = [self._in_use(), self.surround] + [self._device_list(p) for p in self.controller.pipelines]
        for group in self.groups:
            self.add(group)
        return False

    def _in_use(self):
        group = Adw.PreferencesGroup(title="In Use",
                                     description="The same devices GNOME's sound settings show as selected")
        for pipeline in self.controller.pipelines:
            title = TITLES[pipeline.direction][0]
            devices = pipeline.devices()
            if not devices:
                group.add(Adw.ActionRow(title=title, subtitle="No devices found"))
                continue
            ids = [d.name for d in devices]
            row = full_names(Adw.ComboRow(title=title, model=Gtk.StringList.new(
                [pipeline.display_name(d) for d in devices])))
            # The device in use, which is a stand-in while the chosen one is unplugged.
            current = pipeline.device
            if current and current.name in ids:
                row.set_selected(ids.index(current.name))
            row.connect("notify::selected", lambda r, _, p=pipeline, i=ids: p.select_device(i[r.get_selected()]))
            settings = Gtk.Button(icon_name="document-properties-symbolic", tooltip_text="Device Settings",
                                  valign=Gtk.Align.CENTER, css_classes=["flat"])
            settings.connect("clicked", lambda _b, p=pipeline: p.device and self._open(p, p.device.name))
            row.add_suffix(settings)
            group.add(row)
        return group

    def _known(self, pipeline):
        """Connected devices and remembered ones, as {name: (description, connected)}."""
        state = pipeline.state
        known = {d.name: (pipeline.display_name(d), True) for d in pipeline.devices()}
        for name, description in state["device_names"].items():
            known.setdefault(name, (description, False))
        for name in state["device_presets"]:
            known.setdefault(name, (name, False))
        return known

    def _device_list(self, pipeline):
        group = Adw.PreferencesGroup(title=TITLES[pipeline.direction][1])
        known = self._known(pipeline)
        for name, (description, connected) in sorted(known.items(), key=lambda kv: kv[1][0].casefold()):
            row = Adw.ActionRow(title=description, subtitle=self._summary(pipeline, name, connected),
                                activatable=True)
            row.add_suffix(Gtk.Image(icon_name="go-next-symbolic"))
            row.connect("activated", lambda _r, n=name: self._open(pipeline, n))
            group.add(row)
        return group

    def _summary(self, pipeline, name, connected):
        parts = [] if connected else ["Not connected"]
        preset = pipeline.state["device_presets"].get(name)
        if preset:
            parts.append(f"{preset} preset")
        channel = pipeline.state["device_channels"].get(name)
        if channel:
            parts.append(f"{POSITION_NAMES.get(channel, channel).capitalize()} channel only")
        props = names.node_props(name)
        if props.get(names.RATE):
            parts.append(rate_label(props[names.RATE]))
        if props.get(names.AWAKE) == 0:
            parts.append("Never suspends")
        return " · ".join(parts) or "Default settings"

    def _open(self, pipeline, name):
        description = self._known(pipeline).get(name, (name, False))[0]
        DeviceSettings(self, pipeline, name, description).present(self.get_root())


class DeviceSettings(Adw.Dialog):
    """Everything Skitz Effects keeps for one device; hardware changes apply after WirePlumber restarts."""

    def __init__(self, page, pipeline, name, description):
        super().__init__(title=description, content_width=520)
        self.page = page
        self.controller = page.controller
        self.pipeline = pipeline
        self.name = name
        self.description = description
        self.props = names.node_props(name)

        header = Adw.HeaderBar(show_start_title_buttons=False, show_end_title_buttons=False)
        cancel = Gtk.Button(label="Cancel")
        cancel.connect("clicked", lambda _b: self.close())
        apply = Gtk.Button(label="Apply", css_classes=["suggested-action"])
        apply.connect("clicked", lambda _b: self._apply())
        header.pack_start(cancel)
        header.pack_end(apply)
        content = Adw.PreferencesPage()
        view = Adw.ToolbarView(content=content)
        view.add_top_bar(header)
        self.set_child(view)

        general = Adw.PreferencesGroup(title="General")
        self.entry = None
        if names.renamable(name):
            self.entry = Adw.EntryRow(title="Name", text=description)
            reset = Gtk.Button(icon_name="edit-undo-symbolic", tooltip_text="Use the Device's Own Name",
                               valign=Gtk.Align.CENTER, css_classes=["flat"],
                               sensitive="node.description" in self.props)
            reset.connect("clicked", lambda _b: (self.entry.set_text(""), reset.set_sensitive(False)))
            self.entry.add_suffix(reset)
            general.add(self.entry)
        self.choices = [KEEP, *presets.list_presets(pipeline.direction)]
        self.preset = Adw.ComboRow(title="Preset", subtitle="Loaded when Skitz Effects switches to this device",
                                   model=Gtk.StringList.new(self.choices), enable_search=True)
        current = pipeline.state["device_presets"].get(name, KEEP)
        if current in self.choices:
            self.preset.set_selected(self.choices.index(current))
        general.add(self.preset)
        content.add(general)

        self.channel = None
        if pipeline.direction == "input":
            recording = Adw.PreferencesGroup(title="Recording")
            self.channel = self._channel_row()
            recording.add(self.channel)
            content.add(recording)

        self.awake = self.rate = None
        if names.renamable(name):
            hardware = Adw.PreferencesGroup(
                title="Hardware", description="Applying changes here restarts the sound system, so audio pauses "
                                              "for a moment")
            self.awake = Adw.SwitchRow(title="Disable Suspend",
                                       subtitle="Keeps the device awake when nothing plays",
                                       active=self.props.get(names.AWAKE) == 0)
            hardware.add(self.awake)
            if name.startswith("alsa_"):
                self.rate = Adw.ComboRow(title="Sample Rate", model=Gtk.StringList.new(
                    ["Automatic", *(rate_label(r) for r in RATES)]))
                if self.props.get(names.RATE) in RATES:
                    self.rate.set_selected(RATES.index(self.props[names.RATE]) + 1)
                hardware.add(self.rate)
            content.add(hardware)

    def _channel_row(self):
        device = next((d for d in self.pipeline.devices() if d.name == self.name), None)
        self.device = device
        profiles, current = self.controller.pw.profiles(device.card_id) if device and device.card_id else ([], "")
        variants = input_variants(profiles, current)
        if len(variants) > 1:
            # The card itself chooses what is recorded, through its input profile.
            row = full_names(Adw.ComboRow(title="Channel", subtitle="What this device records",
                                          model=Gtk.StringList.new([INPUT_PROFILES.get(part, part)
                                                                    for _i, part in variants])))
            row.variants = variants
            active = current.split("input:")[-1] if "input:" in current else ""
            parts = [part for _i, part in variants]
            if active in parts:
                row.set_selected(parts.index(active))
            row.active = active
            return row
        positions = device.positions if device else ()
        row = full_names(Adw.ComboRow(title="Channel", model=Gtk.StringList.new(
            ["All channels", *(channel_label(i, p) for i, p in enumerate(positions))])))
        row.positions = positions
        current = self.pipeline.state["device_channels"].get(self.name)
        if current in positions:
            row.set_selected(positions.index(current) + 1)
        row.variants = None
        row.set_sensitive(len(positions) > 1)
        row.set_subtitle("What this device records" if len(positions) > 1 else "This input has one channel")
        return row

    def _apply(self):
        state = self.pipeline.state
        choice = self.choices[self.preset.get_selected()]
        if choice == KEEP:
            state["device_presets"].pop(self.name, None)
        else:
            state["device_presets"][self.name] = choice
            if self.name == state["device"] and choice != state["preset"]:
                self.pipeline.load_preset(choice)
        if self.channel and self.channel.variants:
            index, part = self.channel.variants[self.channel.get_selected()]
            if part != self.channel.active:
                self.pipeline.switch_profile(self.device, index)
        elif self.channel:
            chosen = self.channel.positions[self.channel.get_selected() - 1] if self.channel.get_selected() else ""
            if chosen != state["device_channels"].get(self.name, ""):
                if chosen:
                    state["device_channels"][self.name] = chosen
                else:
                    state["device_channels"].pop(self.name, None)
                self.pipeline.queue_rebuild()
        self.controller.settings.save()
        self._apply_hardware()
        self.page.queue_reload()
        self.close()

    def _apply_hardware(self):
        if self.awake is None:
            return
        new_name = self.entry.get_text().strip()
        if new_name == self.description and "node.description" not in self.props:
            new_name = ""
        changes = {
            "node.description": new_name or None,
            "node.nick": new_name or None,
            names.AWAKE: 0 if self.awake.get_active() else None,
            names.RATE: RATES[self.rate.get_selected() - 1] if self.rate and self.rate.get_selected() else None,
        }
        if all(self.props.get(key) == value for key, value in changes.items()):
            return
        window = self.page.get_root()
        try:
            names.update(self.name, changes)
        except OSError as e:
            window.toast(f"Could not change the device: {e.strerror}")
            return
        if new_name:
            self.pipeline.state["device_names"][self.name] = new_name
            self.controller.settings.save()
        # The chains lose their links when WirePlumber restarts, so start them afresh once it is back.
        names.restart_wireplumber(
            lambda: GLib.timeout_add_seconds(2, lambda: self.controller.restart_chains() or False))
        window.toast("Device settings applied")
