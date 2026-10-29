import math

import numpy as np
from gi.repository import Adw, Gtk

from .. import levels

TOP, BOTTOM = 0.0, -78.0
GRID_HZ = (50, 100, 200, 500, 1000, 2000, 5000, 10000)
BARS = 48


def hz_label(hz):
    return f"{hz // 1000}k" if hz >= 1000 else str(hz)


def x_of(hz, width):
    return width * math.log(hz / 20) / math.log(1000)


def accent():
    rgba = Adw.StyleManager.get_default().get_accent_color_rgba()
    return rgba.red, rgba.green, rgba.blue


def draw_grid(cr, widget, width, height, y_of, levels_db):
    fg = widget.get_color()
    cr.set_line_width(1)
    cr.set_source_rgba(fg.red, fg.green, fg.blue, 0.08)
    for hz in GRID_HZ:
        x = round(x_of(hz, width)) + 0.5
        cr.move_to(x, 0)
        cr.line_to(x, height)
    for db in levels_db:
        y = round(y_of(db)) + 0.5
        cr.move_to(0, y)
        cr.line_to(width, y)
    cr.stroke()
    cr.set_source_rgba(fg.red, fg.green, fg.blue, 0.45)
    cr.set_font_size(10)
    for hz in GRID_HZ:
        cr.move_to(x_of(hz, width) + 3, height - 4)
        cr.show_text(hz_label(hz))


class Spectrum(Gtk.Overlay):
    """Before and after spectra of the shown pipeline, drawn over each other."""

    def __init__(self, meters, settings):
        super().__init__(css_classes=["card"], margin_start=12, margin_end=12, margin_top=6, margin_bottom=6,
                         overflow=Gtk.Overflow.HIDDEN)
        self.meters = meters
        self.settings = settings
        self.area = Gtk.DrawingArea(content_height=120, hexpand=True)
        self.area.set_draw_func(self._draw)
        self.set_child(self.area)

        self.mode = Adw.ToggleGroup(css_classes=["round"], halign=Gtk.Align.END, valign=Gtk.Align.START,
                                    margin_top=6, margin_end=6)
        self.mode.add(Adw.Toggle(name="curves", icon_name="view-continuous-symbolic", tooltip="Curves"))
        self.mode.add(Adw.Toggle(name="bars", icon_name="view-grid-symbolic", tooltip="Bars"))
        self.mode.set_active_name(settings.analyser)
        self.mode.connect("notify::active-name", self._on_mode)
        self.add_overlay(self.mode)

        legend = Gtk.Box(spacing=12, halign=Gtk.Align.START, valign=Gtk.Align.START, margin_top=8, margin_start=10)
        for title, css in (("Before effects", "dim-label"), ("After effects", "accent")):
            legend.append(Gtk.Label(label=title, css_classes=["caption", css]))
        self.add_overlay(legend)
        meters.connect("updated", lambda *_: self.area.queue_draw())

    def _on_mode(self, group, _pspec):
        self.settings.analyser = group.get_active_name()
        self.settings.save()
        self.area.queue_draw()

    def _draw(self, area, cr, width, height):
        def y_of(db):
            return height * (TOP - db) / (TOP - BOTTOM)

        draw_grid(cr, area, width, height, y_of, (-20, -40, -60))
        fg = area.get_color()
        layers = ((self.meters.spectra["before"], (fg.red, fg.green, fg.blue), 0.10, 0.45),
                  (self.meters.spectra["after"], accent(), 0.30, 1.0))
        draw = self._bars if self.settings.analyser == "bars" else self._curve
        for values, colour, fill, line in layers:
            draw(cr, values, width, height, y_of, colour, fill, line)

    def _curve(self, cr, values, width, height, y_of, colour, fill, line):
        xs = [x_of(hz, width) for hz in levels.POINTS]
        cr.move_to(xs[0], y_of(values[0]))
        for x, db in zip(xs[1:], values[1:]):
            cr.line_to(x, y_of(db))
        path = cr.copy_path()
        cr.line_to(xs[-1], height)
        cr.line_to(xs[0], height)
        cr.close_path()
        cr.set_source_rgba(*colour, fill)
        cr.fill()
        cr.append_path(path)
        cr.set_line_width(1.5)
        cr.set_source_rgba(*colour, line)
        cr.stroke()

    def _bars(self, cr, values, width, height, y_of, colour, fill, line):
        bands = np.array_split(values, BARS)
        step = width / BARS
        for i, band in enumerate(bands):
            top = y_of(band.max())
            if top >= height:
                continue
            x = i * step + 1.5
            w = step - 3
            radius = min(3, w / 2)
            cr.new_sub_path()
            cr.arc(x + w - radius, top + radius, radius, -math.pi / 2, 0)
            cr.line_to(x + w, height)
            cr.line_to(x, height)
            cr.arc(x + radius, top + radius, radius, math.pi, 3 * math.pi / 2)
            cr.close_path()
        cr.set_source_rgba(*colour, fill if fill > 0.2 else 0.18)
        cr.fill_preserve()
        cr.set_line_width(1)
        cr.set_source_rgba(*colour, line * 0.8)
        cr.stroke()
