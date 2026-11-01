from gi.repository import Adw, GLib, Gtk

from ..controller import routable
from .statusbar import VolumeControl

SECTIONS = {"output": ("Playing", "No apps are playing"), "input": ("Recording", "No apps are recording")}
ICONS = {"output": ("audio-volume-high-symbolic", "audio-volume-muted-symbolic"),
         "input": ("microphone-sensitivity-high-symbolic", "microphone-sensitivity-muted-symbolic")}


class AppRow(Adw.ActionRow):
    def __init__(self, controller, pipeline, oid, props):
        super().__init__()
        self.controller = controller
        self.oid = oid
        self.pipeline = pipeline
        self.props_ = props
        self.icon = Gtk.Image(icon_name="application-x-executable-symbolic", pixel_size=32)
        self.add_prefix(self.icon)
        self.volume = VolumeControl(controller, lambda: oid, "", "Volume of this app", ICONS[pipeline.direction])
        self.add_suffix(self.volume)
        self.effects = Gtk.Switch(valign=Gtk.Align.CENTER, tooltip_text="Apply effects to this app")
        self.effects.connect("notify::active", self._on_effects)
        self.add_suffix(self.effects)
        self.update(props)

    def update(self, props):
        self.props_ = props
        self.set_title(GLib.markup_escape_text(props.get("application.name") or props.get("node.name", "")))
        # Games often switch to 5.1 or 7.1 once their audio starts, so this follows each update.
        details = [props.get("media.name", ""), self.controller.pw.layout(self.oid)]
        self.set_subtitle(GLib.markup_escape_text(" · ".join(d for d in details if d)))
        self.icon.set_from_icon_name(props.get("application.icon-name") or "application-x-executable-symbolic")
        on = not self.pipeline.blocked(props)
        if self.effects.get_active() != on:
            self.effects.set_active(on)
        self.effects.set_sensitive(self.pipeline.preset is not None)
        self.volume.sync()

    def _on_effects(self, switch, _pspec):
        if switch.get_active() == self.pipeline.blocked(self.props_):
            self.pipeline.set_blocked(self.props_, not switch.get_active())


class MixerPage(Adw.PreferencesPage):
    """Apps playing and recording, with their volume and whether effects apply to them."""

    def __init__(self, controller):
        super().__init__(title="Mixer", icon_name="audio-volume-high-symbolic")
        self.controller = controller
        self.groups = {}
        self.rows = {}
        self.empty = {}
        for pipeline in controller.pipelines:
            title, empty = SECTIONS[pipeline.direction]
            group = Adw.PreferencesGroup(title=title)
            self.empty[pipeline.direction] = Adw.ActionRow(title=empty, css_classes=["dim-label"])
            group.add(self.empty[pipeline.direction])
            self.groups[pipeline.direction] = group
            self.add(group)
            pipeline.connect("preset-changed", lambda *_: self.sync())
        self._handler = 0
        controller.connect("devices-changed", lambda *_: self.sync())
        self.sync()

    def sync(self):
        pw = self.controller.pw
        if pw is None:
            return
        if not self._handler:
            self._handler = pw.connect("changed", lambda *_: self.sync())
        for pipeline in self.controller.pipelines:
            direction = pipeline.direction
            streams = {oid: props for oid, props in pw.streams(pipeline.stream_class) if routable(props)}
            rows = self.rows.setdefault(direction, {})
            for oid in [oid for oid in rows if oid not in streams]:
                self.groups[direction].remove(rows.pop(oid))
            for oid, props in streams.items():
                if oid in rows:
                    rows[oid].update(props)
                else:
                    rows[oid] = AppRow(self.controller, pipeline, oid, props)
                    self.groups[direction].add(rows[oid])
            self.empty[direction].set_visible(not rows)
