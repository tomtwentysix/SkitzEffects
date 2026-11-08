"""Live peaks and spectra, read from pw-record taps.

Taps are passive, so metering never wakes a device or opens the mic; they
simply receive nothing while nothing plays. The Input page makes its taps
active while it is shown, so the mic can be watched while its effects are tuned.
"""

import os
import subprocess
import time

from dataclasses import dataclass

import numpy as np
from gi.repository import GLib, GObject

from . import graph
from .config import LAYOUTS
from .controller import _die_with_parent

RATE = 48000
FFT = 4096
FLOOR = -90.0
RELEASE = 24.0
# Log-spaced points the spectrum is drawn at, from 20 Hz to 20 kHz.
POINTS = np.geomspace(20, 20000, 160)
WINDOW = np.hanning(FFT).astype(np.float32)
# Tilts the spectrum up 3 dB per octave around 1 kHz, so pink noise and most music draw level.
TILT = 3 * np.log2(POINTS / 1000)


def _bin_edges():
    edges = np.sqrt(POINTS[:-1] * POINTS[1:])
    edges = np.concatenate(([POINTS[0] / 1.02], edges, [POINTS[-1] * 1.02]))
    bins = np.clip(np.round(edges * FFT / RATE).astype(int), 1, FFT // 2)
    return bins[:-1], np.maximum(bins[1:], bins[:-1] + 1)


STARTS, ENDS = _bin_edges()

METER_LAYOUTS = {"mono": ("MONO",), **LAYOUTS}


@dataclass(frozen=True)
class TapSpec:
    target: str
    sink_monitor: bool
    active: bool = False
    layout: str = "stereo"
    # The target is a stream inside a chain, which the meters link to the tap themselves.
    linked: bool = False


def spectrum(samples):
    """dB levels at POINTS for a block of samples, shape (FFT, channels)."""
    mono = samples.mean(axis=1) * WINDOW
    mag = np.abs(np.fft.rfft(mono)) * (2 / WINDOW.sum())
    peaks = np.array([mag[a:b].max() for a, b in zip(STARTS, ENDS)])
    return np.maximum(20 * np.log10(np.maximum(peaks, 1e-9)) + TILT, FLOOR)


def to_db(level):
    return np.maximum(20 * np.log10(np.maximum(level, 1e-9)), FLOOR)


def smooth(shown, measured, dt):
    """Moves the levels on screen (dB, numpy arrays) toward the newly measured ones over dt seconds.

    Rises at once and falls at RELEASE dB per second, like a meter's ballistics.
    """
    return np.maximum(np.maximum(shown - RELEASE * dt, measured), FLOOR)


class Tap:
    """Reads one node's audio as floats into a ring buffer, one column per channel."""

    def __init__(self, name, spec):
        self.spec = spec
        self.name = f"skitz_tap_{name}"
        positions = METER_LAYOUTS[spec.layout]
        # node.dont-fallback stops WirePlumber resolving a sink's monitor as a target, so it is only
        # set for sources, where it keeps a tap from recording the default mic instead. A tap on a
        # stream between two steps of a chain is linked by the meters, as WirePlumber links no stream
        # to another. Upmixing is off so a stereo signal does not light up a 7.1 meter's rears.
        props = f"{{ node.name = {self.name} node.passive = {str(not spec.active).lower()} " \
                f"stream.capture.sink = {str(spec.sink_monitor).lower()} node.dont-reconnect = true " \
                f"node.dont-fallback = {str(not spec.sink_monitor).lower()} " \
                f"node.autoconnect = {str(not spec.linked).lower()} channelmix.upmix = false }}"
        target = [] if spec.linked else ["--target", spec.target]
        self.proc = subprocess.Popen(
            ["pw-record", "--raw", "--format", "f32", "--rate", str(RATE), "--channels", str(len(positions)),
             "--channel-map", ",".join(positions), "--latency", "20ms", *target, "-P", props, "-"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
            preexec_fn=_die_with_parent)
        self.fd = self.proc.stdout.fileno()
        os.set_blocking(self.fd, False)
        self.channels = len(positions)
        self.buffer = np.zeros((FFT, self.channels), np.float32)
        self.peak = np.zeros(self.channels, np.float32)
        self.last = 0.0
        self._partial = b""
        self._watch = GLib.io_add_watch(self.fd, GLib.PRIORITY_DEFAULT, GLib.IO_IN | GLib.IO_HUP, self._on_data)

    @property
    def alive(self):
        return self._watch != 0

    def _on_data(self, _fd, condition):
        try:
            data = os.read(self.fd, 65536)
        except BlockingIOError:
            return True
        except OSError:
            data = b""
        if not data:
            self._watch = 0
            return False
        data = self._partial + data
        frame = 4 * self.channels
        usable = len(data) - len(data) % frame
        self._partial = data[usable:]
        frames = np.frombuffer(data[:usable], np.float32).reshape(-1, self.channels)
        if len(frames):
            self.peak = np.maximum(self.peak, np.abs(frames).max(axis=0))
            self.buffer = np.concatenate((self.buffer, frames))[-FFT:]
            self.last = time.monotonic()
        return True

    def take_peak(self):
        peak, self.peak = self.peak, np.zeros(self.channels, np.float32)
        return peak

    def quiet(self):
        """True once the tap has had nothing for a moment: passive taps go silent rather than stop."""
        return time.monotonic() - self.last > 0.2

    def stop(self):
        if self._watch:
            GLib.source_remove(self._watch)
            self._watch = 0
        self.proc.terminate()
        try:
            self.proc.wait(timeout=1)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait()
        self.proc.stdout.close()


class Meters(GObject.Object):
    """Taps before and after each pipeline's effects, measured about 30 times a second while running.

    Each peak meter reads from its own tap point, in the layout chosen for it; taps that would read
    the same thing are shared.
    """

    __gsignals__ = {"updated": (GObject.SignalFlags.RUN_FIRST, None, ()),
                    "meter-changed": (GObject.SignalFlags.RUN_FIRST, None, (str,))}

    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self.taps = {}
        self.roles = {}
        self.visible = "output"
        self.spectra = {key: np.full(len(POINTS), FLOOR) for key in ("before", "after")}
        # Peak levels in dB at each meter's tap point, one per channel of its layout.
        self.peaks = {d: np.full(len(METER_LAYOUTS[self.layout(d)]), FLOOR) for d in ("output", "input")}
        self._tick = 0
        self._last = 0.0
        self._retried = 0.0
        for pipeline in controller.pipelines:
            pipeline.connect("state-changed", lambda *_: self._sync())
            pipeline.connect("preset-changed", lambda *_: self._sync())

    @property
    def running(self):
        return bool(self._tick)

    def start(self):
        if not self._tick:
            self._last = time.monotonic()
            self._tick = GLib.timeout_add(33, self._on_tick)
            self._sync()

    def stop(self):
        if self._tick:
            GLib.source_remove(self._tick)
            self._tick = 0
        for tap in self.taps.values():
            tap.stop()
        self.taps = {}

    def show(self, direction):
        """Points the before/after spectrum at a pipeline; the input taps open the mic while it is shown."""
        self.visible = direction
        self._sync()

    def layout(self, direction):
        layout = self.controller.settings.meters[direction]["layout"]
        return layout if layout in METER_LAYOUTS else "stereo"

    def tap_points(self, direction):
        """Where a meter can read from, in chain order, as [(tap, title)]."""
        steps = getattr(self.controller, direction).steps()
        return [("before", "Before Effects"), *[(tap, f"After {title}") for tap, title, _node in steps],
                ("after", "Final Output")]

    def tap(self, direction):
        """The meter's tap point, or "after" while the step it was set to is not in the chain."""
        tap = self.controller.settings.meters[direction]["tap"]
        return tap if tap in dict(self.tap_points(direction)) else "after"

    def set_meter(self, direction, **changes):
        settings = self.controller.settings
        settings.meters[direction].update(changes)
        settings.save()
        self.peaks[direction] = np.full(len(METER_LAYOUTS[self.layout(direction)]), FLOOR)
        self._sync()
        self.emit("meter-changed", direction)

    def _ends(self, direction, layout="stereo"):
        """Specs for the taps before and after a pipeline's effects, None where there is no device."""
        live = direction == "input" and self.visible == "input"
        if direction == "output":
            device = self.controller.output.device
            return (TapSpec(graph.SINK, True, False, layout),
                    device and TapSpec(device.name, True, False, layout))
        device = self.controller.input.device
        return (device and TapSpec(device.name, False, live, layout),
                TapSpec(graph.SOURCE, False, live, layout))

    def _meter_spec(self, direction):
        layout, tap = self.layout(direction), self.tap(direction)
        before, after = self._ends(direction, layout)
        if tap == "before":
            return before
        streams = {t: node for t, _title, node in getattr(self.controller, direction).steps()}
        if tap in streams:
            return TapSpec(streams[tap], False, before is not None and before.active, layout, linked=True)
        return after

    def _wanted(self):
        wanted = {}
        for direction in ("output", "input"):
            before, after = self._ends(direction)
            wanted[(direction, "before")] = before
            wanted[(direction, "after")] = after
            wanted[(direction, "meter")] = self._meter_spec(direction)
        return {role: spec for role, spec in wanted.items() if spec}

    def _sync(self):
        if not self._tick or not self.controller.running:
            return
        self.roles = self._wanted()
        specs = set(self.roles.values())
        for spec in list(self.taps):
            if spec not in specs or not self.taps[spec].alive:
                self.taps.pop(spec).stop()
        pw = self.controller.pw
        for role, spec in self.roles.items():
            # Started before its target exists, a tap would record the default device instead.
            if spec not in self.taps and pw.node_id(spec.target) is not None:
                self.taps[spec] = Tap("_".join(role), spec)
        for spec, tap in self.taps.items():
            if spec.linked and pw.node_id(tap.name) is not None and not pw.linked(spec.target, tap.name):
                pw.link(spec.target, tap.name)

    def _live_tap(self, role):
        tap = self.taps.get(self.roles.get(role))
        return tap if tap and not tap.quiet() else None

    def _spectrum(self, role):
        tap = self._live_tap(role)
        return spectrum(tap.buffer) if tap else np.full(len(POINTS), FLOOR)

    def _peak(self, direction):
        silent = np.full(len(METER_LAYOUTS[self.layout(direction)]), FLOOR)
        tap = self.taps.get(self.roles.get((direction, "meter")))
        if tap is None or tap.channels != len(silent):
            return silent
        # Taken even while quiet, so a stale peak is not shown when the tap wakes up.
        peak = tap.take_peak()
        return silent if tap.quiet() else to_db(peak)

    def _on_tick(self):
        now = time.monotonic()
        dt, self._last = now - self._last, now
        # Taps wait for targets that do not exist yet, and one whose target goes away exits.
        if now - self._retried > 1:
            self._retried = now
            self._sync()
        for direction in ("output", "input"):
            peak = self._peak(direction)
            shown = self.peaks[direction]
            self.peaks[direction] = smooth(shown, peak, dt) if len(shown) == len(peak) else peak
            if direction == self.visible:
                for key in ("before", "after"):
                    self.spectra[key] = smooth(self.spectra[key], self._spectrum((direction, key)), dt)
        self.emit("updated")
        return True
