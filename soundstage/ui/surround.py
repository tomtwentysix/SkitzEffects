from pathlib import Path

from gi.repository import Adw, Gio, GLib, Gtk

from .. import presets

LAYOUTS = (("stereo", "Stereo"), ("5.1", "5.1 Surround"), ("7.1", "7.1 Surround"))
DOWNMIX = (("auto", "When the device needs it"), ("always", "Always"), ("never", "Never"))
ROUTES = {
    "passthrough": "Every channel goes straight to the device",
    "hrir": "Downmixed to stereo through the HRIR",
    "stereo": "Mixed down to stereo without an HRIR",
}


def hrir_choices(current=""):
    """14-channel HeSuVi WAVs from the Easy Effects IR folders, plus the current pick."""
    found = {name: str(path) for name, path in presets.list_irs().items() if presets.wav_channels(path) == 14}
    if current and current not in found.values():
        found[Path(current).stem] = current
    return found


class SurroundPage(Adw.PreferencesPage):
    def __init__(self, controller):
        super().__init__(title="Surround", icon_name="audio-speakers-symbolic")
        self.controller = controller
        settings = controller.settings

        status = Adw.PreferencesGroup(title="Now Playing")
        self.device_row = Adw.ActionRow(title="Output device", subtitle_selectable=True)
        self.route_row = Adw.ActionRow(title="Route")
        status.add(self.device_row)
        status.add(self.route_row)
        self.add(status)

        source = Adw.PreferencesGroup(
            title="Input", description="Apps see Soundstage as a speaker with this many channels")
        self.layout_row = Adw.ComboRow(title="Channels", model=Gtk.StringList.new([t for _k, t in LAYOUTS]))
        self.layout_row.set_selected([k for k, _t in LAYOUTS].index(settings.layout))
        self.layout_row.connect("notify::selected", self._on_layout)
        source.add(self.layout_row)
        self.add(source)

        downmix = Adw.PreferencesGroup(
            title="Downmixing",
            description="An HRIR places each surround channel around you on headphones or stereo speakers. "
                        "Use a 14-channel HeSuVi WAV file.")
        self.mode_row = Adw.ComboRow(title="Use the HRIR", model=Gtk.StringList.new([t for _k, t in DOWNMIX]))
        self.mode_row.set_selected([k for k, _t in DOWNMIX].index(settings.downmix))
        self.mode_row.connect("notify::selected", self._on_mode)
        downmix.add(self.mode_row)
        self.hrir_row = Adw.ComboRow(title="HRIR")
        choose = Gtk.Button(icon_name="document-open-symbolic", tooltip_text="Choose File",
                            valign=Gtk.Align.CENTER, css_classes=["flat"])
        choose.connect("clicked", self._on_choose)
        self.hrir_row.add_suffix(choose)
        self._fill_hrirs()
        self.hrir_row.connect("notify::selected", self._on_hrir)
        downmix.add(self.hrir_row)
        self.add(downmix)

        controller.connect("state-changed", lambda *_: self.refresh())
        controller.connect("devices-changed", lambda *_: self.refresh())
        self.refresh()

    def _fill_hrirs(self):
        self._hrirs = hrir_choices(self.controller.settings.hrir)
        names = ["None", *self._hrirs]
        self._filling = True
        self.hrir_row.set_model(Gtk.StringList.new(names))
        paths = list(self._hrirs.values())
        if self.controller.settings.hrir in paths:
            self.hrir_row.set_selected(paths.index(self.controller.settings.hrir) + 1)
        self._filling = False

    def refresh(self):
        sink = self.controller.output
        if sink:
            self.device_row.set_subtitle(f"{sink.description} · {sink.channels} channels")
        else:
            self.device_row.set_subtitle("No output device")
        route = ROUTES.get(self.controller.route, "Not running")
        if self.controller.route == "stereo" and not self.controller.hrir_ok() and self.controller.settings.downmix != "never":
            route += " (choose an HRIR to place the surround channels)"
        self.route_row.set_subtitle(route)

    def _apply(self):
        self.controller.settings.save()
        self.controller.queue_rebuild()
        self.refresh()

    def _on_layout(self, row, _):
        self.controller.settings.layout = LAYOUTS[row.get_selected()][0]
        self._apply()

    def _on_mode(self, row, _):
        self.controller.settings.downmix = DOWNMIX[row.get_selected()][0]
        self._apply()

    def _on_hrir(self, row, _):
        if self._filling:
            return
        i = row.get_selected()
        self.controller.settings.hrir = "" if i == 0 else list(self._hrirs.values())[i - 1]
        self._apply()

    def _on_choose(self, _button):
        wavs = Gtk.FileFilter(name="WAV files")
        wavs.add_suffix("wav")
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(wavs)
        dialog = Gtk.FileDialog(title="Choose HRIR", filters=filters)
        dialog.open(self.get_root(), None, self._on_chosen)

    def _on_chosen(self, dialog, result):
        try:
            path = dialog.open_finish(result).get_path()
        except GLib.Error:
            return
        root = self.get_root()
        if presets.wav_channels(path) != 14:
            root.toast("That file is not a 14-channel HeSuVi HRIR")
            return
        self.controller.settings.hrir = path
        self._fill_hrirs()
        self._apply()
