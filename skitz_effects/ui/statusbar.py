import time

from gi.repository import GLib, Gtk

from .. import graph
from .analyser import accent

LOW = -60.0
HOLD = 1.0
FALL = 20.0


class PeakMeter(Gtk.Box):
    """Left and right peak bars with a held peak and a dBFS readout."""

    def __init__(self, meters, direction, icon, tooltip):
        super().__init__(spacing=6, tooltip_text=tooltip, valign=Gtk.Align.CENTER)
        self.meters = meters
        self.direction = direction
        self.held = [LOW, LOW]
        self.held_at = [0.0, 0.0]
        self.append(Gtk.Image(icon_name=icon))
        self.area = Gtk.DrawingArea(content_width=90, content_height=12, valign=Gtk.Align.CENTER)
        self.area.set_draw_func(self._draw)
        self.append(self.area)
        self.label = Gtk.Label(width_chars=7, xalign=1, css_classes=["caption", "numeric", "dim-label"])
        self.append(self.label)
        meters.connect("updated", self._on_updated)

    def _on_updated(self, _meters):
        now = time.monotonic()
        peaks = self.meters.peaks[self.direction]
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
        bar = (height - 2) / 2
        colour = accent()
        for i, db in enumerate(self.meters.peaks[self.direction]):
            y = i * (bar + 2)
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
    """A mute button and slider for one PipeWire node, kept in step with changes made elsewhere.

    Nodes in `linked` follow the slider and mute button but are not read back.
    """

    def __init__(self, controller, node, label, tooltip, icons, linked=()):
        super().__init__(spacing=4, tooltip_text=tooltip, valign=Gtk.Align.CENTER)
        self.controller = controller
        self.node = node
        self.linked = linked
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
            for node in (self.node(), *self.linked):
                self.controller.pw.set_volume(node, self._pending)
        self._pending = None
        return False

    def _on_mute(self, button):
        self._update_labels()
        if not self._syncing and self.node():
            for node in (self.node(), *self.linked):
                self.controller.pw.set_mute(node, button.get_active())


class StatusBar(Gtk.ActionBar):
    def __init__(self, controller, meters):
        super().__init__()
        self.controller = controller
        self.pack_start(PeakMeter(meters, "output", "audio-speakers-symbolic", "Output peak after effects"))
        self.pack_start(PeakMeter(meters, "input", "audio-input-microphone-symbolic",
                                  "Microphone peak after effects"))
        inputs = controller.input
        self.volumes = (
            VolumeControl(controller, lambda: graph.SINK, "Output Pre-Gain",
                          "Volume of everything apps play, before the output effects",
                          ("audio-volume-high-symbolic", "audio-volume-muted-symbolic"), (graph.STEREO_SINK,)),
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

