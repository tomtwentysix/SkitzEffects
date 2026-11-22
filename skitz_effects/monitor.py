import time
from math import sqrt

from gi.repository import GLib, GObject

from . import graph, levels
from .check import Reading

ACTIVE_DB = -60.0


def _active(sample):
    _peak, energy, frames = sample
    return frames > 0 and sqrt(energy / (2 * frames)) > 10 ** (ACTIVE_DB / 20)


def _add(reading, sample, active):
    peak, energy, frames = sample
    reading.peak = max(reading.peak, peak)
    if peak > 1.0:
        reading.overs += 1
    if active:
        reading.energy += energy
        reading.frames += frames


def tick(before, readings, before_sample, samples):
    active = _active(before_sample)
    for key, sample in samples.items():
        _add(readings[key], sample, active)
    _add(before, before_sample, active)


class Check(GObject.Object):
    __gsignals__ = {"updated": (GObject.SignalFlags.RUN_FIRST, None, ()),
                    "aborted": (GObject.SignalFlags.RUN_FIRST, None, (str,))}

    def __init__(self, pipeline):
        super().__init__()
        self.pipeline = pipeline
        self.stages = pipeline.stages()
        self.before = Reading()
        self.readings = {stage.key: Reading() for stage in self.stages}
        self.elapsed = 0.0
        self._taps = {}
        self._input = None
        self._timer = 0
        self._started = 0.0
        self._handlers = [pipeline.connect(name, self._on_changed) for name in ("state-changed", "preset-changed")]

    def _input_spec(self):
        pipeline = self.pipeline
        if pipeline.direction == "output":
            layout = pipeline.controller.settings.layout if pipeline.route in ("hrir", "passthrough") else "stereo"
            return levels.TapSpec(graph.SINK, True, False, layout)
        device = pipeline.device
        return device and levels.TapSpec(device.name, False, False, "stereo")

    def start(self):
        if self._timer:
            return
        self._started = time.monotonic()
        self._timer = GLib.timeout_add(33, self._on_tick)
        self._sync()

    def _sync(self):
        pw = self.pipeline.pw
        wanted = {stage.key: (f"check_{i}", levels.TapSpec(stage.stream, False, False, "stereo", linked=True))
                  for i, stage in enumerate(self.stages)}
        for key, (name, spec) in wanted.items():
            if key not in self._taps and pw.node_id(spec.target) is not None:
                self._taps[key] = levels.Tap(name, spec)
        spec = self._input_spec()
        if self._input is None and spec and pw.node_id(spec.target) is not None:
            self._input = levels.Tap("check_input", spec)
        for tap in self._taps.values():
            if pw.node_id(tap.name) is not None and not pw.linked(tap.spec.target, tap.name):
                pw.link(tap.spec.target, tap.name)

    def _on_changed(self, *_):
        if self.pipeline.stages() != self.stages:
            self.stop()
            self.emit("aborted", "The effects changed during the check")

    def _sample(self, tap):
        energy, frames = tap.take_energy()
        return float(tap.take_peak().max()), energy, frames

    def _on_tick(self):
        self._sync()
        before = self._sample(self._input) if self._input else (0.0, 0.0, 0)
        samples = {key: self._sample(tap) for key, tap in self._taps.items()}
        tick(self.before, self.readings, before, samples)
        self.elapsed = time.monotonic() - self._started
        self.emit("updated")
        return True

    def stop(self):
        for handler in self._handlers:
            self.pipeline.disconnect(handler)
        self._handlers = []
        if self._timer:
            GLib.source_remove(self._timer)
            self._timer = 0
        for tap in [*self._taps.values(), *([self._input] if self._input else [])]:
            tap.stop()
        self._taps, self._input = {}, None
