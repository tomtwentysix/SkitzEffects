"""Live peaks and spectra, read from pw-record taps.

Taps are passive, so metering never wakes a device or opens the mic; they
simply receive nothing while nothing plays. The Input page makes its taps
active while it is shown, so the mic can be watched while its effects are tuned.
"""

import os
import subprocess
import time

import numpy as np
from gi.repository import GLib, GObject

from . import graph
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


def spectrum(samples):
    """dB levels at POINTS for a block of stereo samples, shape (FFT, 2)."""
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
    """Reads one node's audio as stereo floats into a ring buffer."""

    def __init__(self, name, target, sink_monitor, active):
        self.target = target
        self.active = active
        # node.dont-fallback stops WirePlumber resolving a sink's monitor as a target, so it is only
        # set for sources, where it keeps a tap from recording the default mic instead.
        props = f"{{ node.name = soundstage_tap_{name} node.passive = {str(not active).lower()} " \
                f"stream.capture.sink = {str(sink_monitor).lower()} node.dont-reconnect = true " \
                f"node.dont-fallback = {str(not sink_monitor).lower()} }}"
        self.proc = subprocess.Popen(
            ["pw-record", "--raw", "--format", "f32", "--rate", str(RATE), "--channels", "2",
             "--latency", "20ms", "--target", target, "-P", props, "-"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
            preexec_fn=_die_with_parent)
        self.fd = self.proc.stdout.fileno()
        os.set_blocking(self.fd, False)
        self.buffer = np.zeros((FFT, 2), np.float32)
        self.peak = np.zeros(2, np.float32)
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
        usable = len(data) - len(data) % 8
        self._partial = data[usable:]
        frames = np.frombuffer(data[:usable], np.float32).reshape(-1, 2)
        if len(frames):
            self.peak = np.maximum(self.peak, np.abs(frames).max(axis=0))
            self.buffer = np.concatenate((self.buffer, frames))[-FFT:]
            self.last = time.monotonic()
        return True

    def take_peak(self):
        peak, self.peak = self.peak, np.zeros(2, np.float32)
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
    """Taps before and after each pipeline's effects, measured about 30 times a second while running."""

    __gsignals__ = {"updated": (GObject.SignalFlags.RUN_FIRST, None, ())}

    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self.taps = {}
        self.visible = "output"
        self.spectra = {key: np.full(len(POINTS), FLOOR) for key in ("before", "after")}
        # Peak levels in dB after the effects, (left, right) per direction.
        self.peaks = {d: np.full(2, FLOOR) for d in ("output", "input")}
        self._tick = 0
        self._last = 0.0
        self._retried = 0.0
        for pipeline in controller.pipelines:
            pipeline.connect("state-changed", lambda *_: self._sync())

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

    def _wanted(self):
        output, inputs = self.controller.output, self.controller.input
        live = self.visible == "input"
        wanted = {("output", "before"): (graph.SINK, True, False)}
        if output.device:
            wanted[("output", "after")] = (output.device.name, True, False)
        if inputs.device:
            wanted[("input", "before")] = (inputs.device.name, False, live)
        wanted[("input", "after")] = (graph.SOURCE, False, live)
        return wanted

    def _sync(self):
        if not self._tick or not self.controller.running:
            return
        wanted = self._wanted()
        for key in list(self.taps):
            tap = self.taps[key]
            if key not in wanted or not tap.alive or (tap.target, tap.active) != (wanted[key][0], wanted[key][2]):
                tap.stop()
                del self.taps[key]
        pw = self.controller.pw
        for key, (target, sink_monitor, active) in wanted.items():
            # Started before its target exists, a tap would record the default device instead.
            if key not in self.taps and pw.node_id(target) is not None:
                self.taps[key] = Tap("_".join(key), target, sink_monitor, active)

    def _measure(self, key):
        tap = self.taps.get(key)
        if tap is None or tap.quiet():
            if tap:
                tap.take_peak()
            return np.full(len(POINTS), FLOOR), np.full(2, FLOOR)
        return spectrum(tap.buffer), to_db(tap.take_peak())

    def _on_tick(self):
        now = time.monotonic()
        dt, self._last = now - self._last, now
        # Taps wait for targets that do not exist yet, and one whose target goes away exits.
        if now - self._retried > 1:
            self._retried = now
            self._sync()
        for direction in ("output", "input"):
            levels, peak = self._measure((direction, "after"))
            self.peaks[direction] = smooth(self.peaks[direction], peak, dt)
            if direction == self.visible:
                self.spectra["after"] = smooth(self.spectra["after"], levels, dt)
                before, _ = self._measure((direction, "before"))
                self.spectra["before"] = smooth(self.spectra["before"], before, dt)
        self.emit("updated")
        return True
