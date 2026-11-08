"""Graphical parametric equalizer: the summed response with a draggable handle per band."""

import math

import numpy as np
from gi.repository import Adw, Gtk

from .. import levels, plugins, presets
from .analyser import accent, draw_grid, x_of
from .rows import param_row, set_path

RATE = 48000
RANGE = 24.0
FREQS = np.geomspace(20, 20000, 400)
GAIN_TYPES = {"Bell", "Hi-shelf", "Lo-shelf", "Resonance"}
HANDLE = 7
GRAB = 14

BAND_PARAMS = (
    plugins.Param("type", "", "enum", plugins.EQ_TYPES, "Type"),
    plugins.Param("frequency", "", label="Frequency", lo=10, hi=24000, step=1, digits=0, unit="Hz"),
    plugins.Param("gain", "", label="Gain", lo=-36, hi=36, step=0.1, unit="dB"),
    plugins.Param("q", "", label="Quality", lo=0.1, hi=100, step=0.01, digits=2),
    plugins.Param("slope", "", "enum", plugins.EQ_SLOPES, "Slope"),
    plugins.Param("mode", "", "enum", plugins.EQ_MODES, "Filter mode"),
    plugins.Param("mute", "", "bool", label="Mute"),
    plugins.Param("solo", "", "bool", label="Solo"),
)


def biquad(kind, freq, gain, q):
    """RBJ cookbook coefficients (b, a) for one band, or None for a band that leaves the sound alone."""
    w = 2 * math.pi * min(freq, RATE * 0.49) / RATE
    cos, alpha = math.cos(w), math.sin(w) / (2 * max(q, 0.05))
    a_ = 10 ** (gain / 40)
    if kind in ("Bell", "Resonance"):
        return (1 + alpha * a_, -2 * cos, 1 - alpha * a_), (1 + alpha / a_, -2 * cos, 1 - alpha / a_)
    if kind in ("Lo-shelf", "Hi-shelf"):
        sign = 1 if kind == "Lo-shelf" else -1
        root = 2 * math.sqrt(a_) * alpha
        b = (a_ * ((a_ + 1) - sign * (a_ - 1) * cos + root), sign * 2 * a_ * ((a_ - 1) - sign * (a_ + 1) * cos),
             a_ * ((a_ + 1) - sign * (a_ - 1) * cos - root))
        a = ((a_ + 1) + sign * (a_ - 1) * cos + root, -sign * 2 * ((a_ - 1) + sign * (a_ + 1) * cos),
             (a_ + 1) + sign * (a_ - 1) * cos - root)
        return b, a
    if kind == "Hi-pass":
        return ((1 + cos) / 2, -(1 + cos), (1 + cos) / 2), (1 + alpha, -2 * cos, 1 - alpha)
    if kind == "Lo-pass":
        return ((1 - cos) / 2, 1 - cos, (1 - cos) / 2), (1 + alpha, -2 * cos, 1 - alpha)
    if kind in ("Notch", "Ladder-rej"):
        return (1, -2 * cos, 1), (1 + alpha, -2 * cos, 1 - alpha)
    if kind in ("Bandpass", "Ladder-pass"):
        return (alpha, 0, -alpha), (1 + alpha, -2 * cos, 1 - alpha)
    return None


def band_response(band):
    """The band's effect in dB at FREQS; zero for an off or muted band."""
    kind = band.get("type", "Bell")
    if kind == "Off" or band.get("mute"):
        return np.zeros(len(FREQS))
    coefficients = biquad(kind, float(band.get("frequency", 1000)), float(band.get("gain", 0)),
                          float(band.get("q", 1.5)))
    if coefficients is None:
        return np.zeros(len(FREQS))
    (b0, b1, b2), (a0, a1, a2) = coefficients
    z = np.exp(-1j * 2 * np.pi * FREQS / RATE)
    h = (b0 + b1 * z + b2 * z * z) / (a0 + a1 * z + a2 * z * z)
    # LSP's slope stacks the same filter, x1 to x4.
    order = plugins.EQ_SLOPES.index(band.get("slope", "x1")) + 1 if band.get("slope") in plugins.EQ_SLOPES else 1
    return order * 20 * np.log10(np.maximum(np.abs(h), 1e-9))


class EqualizerEditor(Gtk.Box):
    """The response graph over a live spectrum, and the selected band's settings below it."""

    def __init__(self, settings, on_change, meters=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.settings = settings
        self.on_change = on_change
        self.meters = meters
        self.side = "left"
        self.selected = 0
        self._drag = None

        self.sides = Adw.ToggleGroup(halign=Gtk.Align.CENTER, visible=bool(settings.get("split-channels")))
        self.sides.add(Adw.Toggle(name="left", label="Left"))
        self.sides.add(Adw.Toggle(name="right", label="Right"))
        self.sides.connect("notify::active-name", self._on_side)
        self.append(self.sides)

        self.area = Gtk.DrawingArea(content_height=260, hexpand=True, css_classes=["card"],
                                    overflow=Gtk.Overflow.HIDDEN)
        self.area.set_draw_func(self._draw)
        drag = Gtk.GestureDrag()
        drag.connect("drag-begin", self._on_drag_begin)
        drag.connect("drag-update", self._on_drag_update)
        drag.connect("drag-end", lambda *_: setattr(self, "_drag", None))
        self.area.add_controller(drag)
        self._pointer = (-100, -100)
        motion = Gtk.EventControllerMotion()
        motion.connect("motion", lambda _c, x, y: setattr(self, "_pointer", (x, y)))
        self.area.add_controller(motion)
        scroll = Gtk.EventControllerScroll(flags=Gtk.EventControllerScrollFlags.VERTICAL)
        scroll.connect("scroll", self._on_scroll)
        self.area.add_controller(scroll)
        self.append(self.area)
        self.append(Gtk.Label(label="Drag a handle to set its frequency and gain; scroll over it to change its width",
                              css_classes=["caption", "dim-label"], wrap=True))

        self.band_group = Adw.PreferencesGroup()
        self.append(self.band_group)
        self._band_rows = []
        if meters:
            meters.connect("updated", lambda *_: self.area.queue_draw())
        self._fill_band()

    def count(self):
        return int(self.settings.get("num-bands", 10))

    def band(self, i, side=None):
        bands = self.settings.setdefault(side or self.side, {})
        default = presets.DEFAULTS["equalizer"]["left"].get(f"band{i}") or {
            "frequency": 1000.0, "gain": 0.0, "type": "Bell", "q": 1.504760237537245, "mode": "RLC (BT)",
            "slope": "x1", "mute": False, "solo": False, "width": 4.0}
        return bands.setdefault(f"band{i}", dict(default))

    def changed(self):
        self.on_change()
        self.area.queue_draw()

    def _on_side(self, group, _pspec):
        self.side = group.get_active_name()
        self._fill_band()
        self.area.queue_draw()

    def _fill_band(self):
        for row in self._band_rows:
            self.band_group.remove(row)
        self._band_rows = []
        self.selected = min(self.selected, self.count() - 1)
        band = self.band(self.selected)
        self.band_group.set_title(f"Band {self.selected + 1}")
        nav = Gtk.Box(css_classes=["linked"], valign=Gtk.Align.CENTER)
        for icon, step, tip in (("go-previous-symbolic", -1, "Previous Band"), ("go-next-symbolic", 1, "Next Band")):
            button = Gtk.Button(icon_name=icon, tooltip_text=tip)
            button.connect("clicked", lambda _b, s=step: self.select((self.selected + s) % self.count()))
            nav.append(button)
        self.band_group.set_header_suffix(nav)
        for param in BAND_PARAMS:
            row = param_row(param, band, self.changed)
            self._band_rows.append(row)
            self.band_group.add(row)

    def select(self, i):
        self.selected = i
        self._fill_band()
        self.area.queue_draw()

    def _y_of(self, db, height):
        return height / 2 - db / RANGE * (height / 2 - 12)

    def _db_of(self, y, height):
        return (height / 2 - y) / (height / 2 - 12) * RANGE

    def _handle(self, i, width, height):
        band = self.band(i)
        gain = float(band.get("gain", 0)) if band.get("type") in GAIN_TYPES else 0.0
        return x_of(float(band.get("frequency", 1000)), width), self._y_of(max(min(gain, RANGE), -RANGE), height)

    def _draw(self, area, cr, width, height):
        draw_grid(cr, area, width, height, lambda db: self._y_of(db, height), (-12, 0, 12))
        fg = area.get_color()
        colour = accent()
        if self.meters:
            # The live output spectrum, scaled into the graph's range for context.
            cr.move_to(0, height)
            for hz, db in zip(levels.POINTS, self.meters.spectra["after"]):
                cr.line_to(x_of(hz, width), height - (db - levels.FLOOR) / -levels.FLOOR * height * 0.6)
            cr.line_to(width, height)
            cr.close_path()
            cr.set_source_rgba(fg.red, fg.green, fg.blue, 0.06)
            cr.fill()

        bands = [self.band(i) for i in range(self.count())]
        responses = [band_response(b) for b in bands]
        total = np.sum(responses, axis=0) if responses else np.zeros(len(FREQS))
        xs = [x_of(hz, width) for hz in FREQS]

        if responses:
            cr.move_to(xs[0], self._y_of(responses[self.selected][0], height))
            for x, db in zip(xs[1:], responses[self.selected][1:]):
                cr.line_to(x, self._y_of(max(min(db, RANGE), -RANGE), height))
            cr.line_to(xs[-1], height / 2)
            cr.line_to(xs[0], height / 2)
            cr.close_path()
            cr.set_source_rgba(*colour, 0.15)
            cr.fill()

        cr.move_to(xs[0], self._y_of(total[0], height))
        for x, db in zip(xs[1:], total[1:]):
            cr.line_to(x, self._y_of(max(min(db, RANGE + 6), -RANGE - 6), height))
        cr.set_line_width(2.5)
        cr.set_source_rgba(*colour, 1)
        cr.stroke()

        cr.set_font_size(9)
        for i, band in enumerate(bands):
            x, y = self._handle(i, width, height)
            off = band.get("type") == "Off" or band.get("mute")
            cr.arc(x, y, HANDLE + (2 if i == self.selected else 0), 0, 2 * math.pi)
            if i == self.selected:
                cr.set_source_rgba(*colour, 1)
            else:
                cr.set_source_rgba(fg.red, fg.green, fg.blue, 0.25 if off else 0.6)
            cr.fill()
            label = str(i + 1)
            extents = cr.text_extents(label)
            cr.move_to(x - extents.width / 2 - extents.x_bearing, y + extents.height / 2)
            if i == self.selected:
                cr.set_source_rgb(1, 1, 1)
            else:
                cr.set_source_rgba(0, 0, 0, 0.8)
            cr.show_text(label)

    def _nearest(self, x, y):
        width, height = self.area.get_width(), self.area.get_height()
        best, distance = None, GRAB
        for i in range(self.count()):
            hx, hy = self._handle(i, width, height)
            d = math.hypot(hx - x, hy - y)
            if d <= distance:
                best, distance = i, d
        return best

    def _on_drag_begin(self, gesture, x, y):
        i = self._nearest(x, y)
        if i is None:
            gesture.set_state(Gtk.EventSequenceState.DENIED)
            return
        self._drag = (i, x, y)
        if i != self.selected:
            self.select(i)

    def _on_drag_update(self, _gesture, dx, dy):
        if self._drag is None:
            return
        i, x0, y0 = self._drag
        width, height = self.area.get_width(), self.area.get_height()
        band = self.band(i)
        freq = 20 * 1000 ** (min(max(x0 + dx, 0), width) / width)
        set_path(band, "frequency", round(freq, 1))
        if band.get("type") in GAIN_TYPES:
            set_path(band, "gain", round(max(min(self._db_of(y0 + dy, height), RANGE), -RANGE), 1))
        self._fill_band()
        self.changed()

    def _on_scroll(self, _controller, _dx, dy):
        i = self._nearest(*self._pointer)
        if i is None:
            return False
        if i != self.selected:
            self.select(i)
        band = self.band(i)
        q = float(band.get("q", 1.5)) * (1.1 ** -dy)
        set_path(band, "q", round(min(max(q, 0.1), 100), 2))
        self._fill_band()
        self.changed()
        return True
