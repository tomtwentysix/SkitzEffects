import time

from gi.repository import Gio, GLib, Gtk

from .. import graph
from ..levels import METER_LAYOUTS
from .analyser import accent

LOW = -60.0
HOLD = 1.0
FALL = 20.0
METER_TITLES = {"mono": "Mono", "stereo": "Stereo", "5.1": "5.1 Surround", "7.1": "7.1 Surround"}


def bar_gap(channels):
    return 2 if channels <= 2 else 1


def bar_height(channels):
    return {1: 8, 2: 12}.get(channels, 4 * channels - 1)


class PeakMeter(Gtk.MenuButton):
    """A peak bar per channel with a held peak and a dBFS readout; clicking it picks the layout and tap point."""

    def __init__(self, meters, direction, icon, name):
        super().__init__(valign=Gtk.Align.CENTER, css_classes=["flat"])
        self.meters = meters
        self.direction = direction
        self.name = name
        self.held = []
        self.held_at = []
        box = Gtk.Box(spacing=6)
        box.append(Gtk.Image(icon_name=icon))
        self.area = Gtk.DrawingArea(content_width=90, valign=Gtk.Align.CENTER)
        self.area.set_draw_func(self._draw)
        box.append(self.area)
        self.label = Gtk.Label(width_chars=7, xalign=1, css_classes=["caption", "numeric", "dim-label"])
        box.append(self.label)
        self.set_child(box)
        group = Gio.SimpleActionGroup()
        self.actions = {}
        for key in ("layout", "tap"):
            action = Gio.SimpleAction.new_stateful(key, GLib.VariantType("s"), GLib.Variant("s", ""))
            action.connect("change-state", self._on_choice)
            group.add_action(action)
            self.actions[key] = action
        self.insert_action_group("meter", group)
        self.set_create_popup_func(self._build_menu)
        meters.connect("updated", self._on_updated)
        meters.connect("meter-changed", lambda _m, d: d == direction and self._on_meter_changed())
        for pipeline in meters.controller.pipelines:
            pipeline.connect("state-changed", lambda *_: self._on_meter_changed())
            pipeline.connect("preset-changed", lambda *_: self._on_meter_changed())
        self._on_meter_changed()

    def _on_choice(self, action, value):
        self.meters.set_meter(self.direction, **{action.get_name(): value.get_string()})

    def _build_menu(self, _button):
        menu = Gio.Menu()
        for title, key, choices in (
                ("Channels", "layout", METER_TITLES.items()),
                ("Measure At", "tap", self.meters.tap_points(self.direction))):
            section = Gio.Menu()
            for value, label in choices:
                item = Gio.MenuItem.new(label, None)
                item.set_action_and_target_value(f"meter.{key}", GLib.Variant("s", value))
                section.append_item(item)
            menu.append_section(title, section)
        self.set_menu_model(menu)

    def _on_meter_changed(self):
        layout, tap = self.meters.layout(self.direction), self.meters.tap(self.direction)
        self.actions["layout"].set_state(GLib.Variant("s", layout))
        self.actions["tap"].set_state(GLib.Variant("s", tap))
        channels = len(METER_LAYOUTS[layout])
        if len(self.held) != channels:
            self.held = [LOW] * channels
            self.held_at = [0.0] * channels
        self.area.set_content_height(bar_height(channels))
        title = dict(self.meters.tap_points(self.direction))[tap]
        self.set_tooltip_text(f"{self.name} peak: {title}, {METER_TITLES[layout]}")

    def _on_updated(self, _meters):
        now = time.monotonic()
        peaks = self.meters.peaks[self.direction]
        if len(peaks) != len(self.held):
            return
        for i, db in enumerate(peaks):
            if db >= self.held[i]:
                self.held[i], self.held_at[i] = float(db), now
            elif now - self.held_at[i] > HOLD:
                self.held[i] = max(float(db), self.held[i] - FALL / 30)
        top = max(self.held)
        self.label.set_label("−∞ dB" if top <= LOW else f"{top:.1f} dB".replace("-", "−"))
        self.area.queue_draw()

    def _draw(self, area, cr, width, height):
        fg = area.get_color()
        peaks = self.meters.peaks[self.direction]
        if len(peaks) != len(self.held):
            return
        gap = bar_gap(len(peaks))
        bar = (height - gap * (len(peaks) - 1)) / len(peaks)
        colour = accent()
        for i, db in enumerate(peaks):
            y = i * (bar + gap)
            cr.set_source_rgba(fg.red, fg.green, fg.blue, 0.1)
            cr.rectangle(0, y, width, bar)
            cr.fill()
            fraction = min(max((float(db) - LOW) / -LOW, 0), 1)
            hot = db > -1 and (0.88, 0.11, 0.14) or db > -6 and (0.96, 0.76, 0.07) or colour
            cr.set_source_rgb(*hot)
            cr.rectangle(0, y, width * fraction, bar)
            cr.fill()
            held = min(max((self.held[i] - LOW) / -LOW, 0), 1)
            if held > 0:
                cr.set_source_rgba(fg.red, fg.green, fg.blue, 0.7)
                cr.rectangle(max(width * held - 2, 0), y, 2, bar)
                cr.fill()


class VolumeControl(Gtk.Box):
    """A mute button and slider for one PipeWire node, kept in step with changes made elsewhere."""

    def __init__(self, controller, node, label, tooltip, icons):
        super().__init__(spacing=4, tooltip_text=tooltip, valign=Gtk.Align.CENTER)
        self.controller = controller
        self.node = node
        self.icons = icons
        self._pending = None
        self._send_id = 0
        self._syncing = False
        self.mute = Gtk.ToggleButton(icon_name=icons[0], css_classes=["flat", "circular"],
                                     tooltip_text="Mute")
        self.mute.connect("toggled", self._on_mute)
        self.append(self.mute)
        if label:
            self.append(Gtk.Label(label=label, css_classes=["caption"]))
        self.scale = Gtk.Scale(adjustment=Gtk.Adjustment(lower=0, upper=1, step_increment=0.02, page_increment=0.1),
                               width_request=100, draw_value=False)
        self.scale.connect("value-changed", self._on_scale)
        self.append(self.scale)
        self.percent = Gtk.Label(width_chars=4, xalign=1, css_classes=["caption", "numeric", "dim-label"])
        self.append(self.percent)

    def sync(self):
        pw = self.controller.pw
        name = self.node()
        volume, muted = pw.volume(name) if pw and name else (None, False)
        self.set_sensitive(volume is not None)
        if volume is None or self._send_id:
            return
        self._syncing = True
        if abs(self.scale.get_value() - volume) > 0.005:
            self.scale.set_value(volume)
        self.mute.set_active(muted)
        self._syncing = False
        self._update_labels()

    def _update_labels(self):
        muted = self.mute.get_active()
        self.mute.set_icon_name(self.icons[1] if muted else self.icons[0])
        self.percent.set_label(f"{round(self.scale.get_value() * 100)}%")

    def _on_scale(self, scale):
        self._update_labels()
        if self._syncing:
            return
        self._pending = scale.get_value()
        if not self._send_id:
            self._send_id = GLib.timeout_add(40, self._send)

    def _send(self):
        self._send_id = 0
        if self._pending is not None and self.node():
            self.controller.pw.set_volume(self.node(), self._pending)
        self._pending = None
        return False

    def _on_mute(self, button):
        self._update_labels()
        if not self._syncing and self.node():
            self.controller.pw.set_mute(self.node(), button.get_active())


class StatusBar(Gtk.ActionBar):
    def __init__(self, controller, meters):
        super().__init__()
        self.controller = controller
        self.pack_start(PeakMeter(meters, "output", "audio-speakers-symbolic", "Output"))
        self.pack_start(PeakMeter(meters, "input", "audio-input-microphone-symbolic", "Microphone"))
        inputs = controller.input
        self.volumes = (
            VolumeControl(controller, lambda: graph.SINK, "Output Pre-Gain",
                          "Volume of everything apps play, before the output effects",
                          ("audio-volume-high-symbolic", "audio-volume-muted-symbolic")),
            VolumeControl(controller, lambda: inputs.device and inputs.device.name, "Mic Pre-Gain",
                          "Microphone volume, before the input effects",
                          ("microphone-sensitivity-high-symbolic", "microphone-sensitivity-muted-symbolic")),
        )
        for control in reversed(self.volumes):
            self.pack_end(control)
        controller.connect("devices-changed", lambda *_: self.sync())
        inputs.connect("state-changed", lambda *_: self.sync())
        self._pw_handler = 0
        self.sync()

    def sync(self):
        pw = self.controller.pw
        if pw and not self._pw_handler:
            self._pw_handler = pw.connect("changed", lambda *_: self.sync())
        for control in self.volumes:
            control.sync()

