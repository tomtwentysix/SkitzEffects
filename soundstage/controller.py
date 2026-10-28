"""Keeps the sink, the filter-chain process and the loaded preset in step with PipeWire."""

import ctypes
import signal
import subprocess

from gi.repository import GLib, GObject

from . import config, graph, plugins, presets
from .config import LAYOUTS
from .pipewire import PipeWire

PR_SET_PDEATHSIG = 1


def _die_with_parent():
    ctypes.CDLL("libc.so.6").prctl(PR_SET_PDEATHSIG, signal.SIGTERM)


class Controller(GObject.Object):
    __gsignals__ = {
        "preset-changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "state-changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "devices-changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self, settings):
        super().__init__()
        self.settings = settings
        self.preset = presets.load(settings.preset) if settings.preset else None
        self.pw = None
        self.route = ""
        self.running = False
        self._proc = None
        self._conf = ""
        self._save_id = 0
        self._rebuild_id = 0
        self._devices = ()

    def start(self):
        if self.running:
            return
        self.running = True
        self.pw = PipeWire()
        self.pw.connect("changed", self._on_pipewire)

    def shutdown(self):
        if not self.running:
            return
        self._flush_save()
        self._stop_chain()
        if self.settings.output_device:
            self.pw.set_default(self.settings.output_device)
        self.pw.destroy(graph.SINK)
        self.pw.stop()
        self.running = False

    @property
    def output(self):
        return self.pw.sink(self.settings.output_device) if self.pw else None

    def _on_pipewire(self, _pw):
        pw = self.pw
        devices = tuple((s.name, s.description, s.channels) for s in pw.sinks())
        if devices != self._devices:
            self._devices = devices
            self.emit("devices-changed")
        positions = LAYOUTS[self.settings.layout]
        sink_channels = pw.node_channels(graph.SINK)
        if sink_channels != len(positions):
            if sink_channels:
                pw.destroy(graph.SINK)
            else:
                pw.create_sink(graph.SINK, "Soundstage", positions)
            return
        default = pw.default_sink
        if default and default != graph.SINK and pw.sink(default):
            # The user picked a device elsewhere (GNOME Settings, the volume menu):
            # play through it and take the default back.
            self.select_output(default)
            pw.set_default(graph.SINK)
        elif self.output is None:
            fallback = next((s for s in pw.sinks() if not s.virtual), None)
            if fallback:
                self.select_output(fallback.name)
        self.queue_rebuild()

    def select_output(self, name):
        if name == self.settings.output_device:
            return
        self.settings.output_device = name
        sink = self.pw.sink(name)
        if sink:
            self.settings.device_names[name] = sink.description
        rule = self.settings.device_presets.get(name)
        if rule and rule in presets.list_presets():
            self.load_preset(rule)
        self.settings.save()
        self.emit("state-changed")
        self.queue_rebuild()

    def load_preset(self, name):
        self._flush_save()
        self.preset = presets.load(name)
        self.settings.preset = name if self.preset else ""
        self.settings.save()
        self.emit("preset-changed")
        self.queue_rebuild()

    def new_preset(self, name):
        self._flush_save()
        self.preset = presets.create(name)
        self.settings.preset = name
        self.settings.save()
        self.emit("preset-changed")
        self.queue_rebuild()

    def set_enabled(self, on):
        self.settings.enabled = on
        self.settings.save()
        self.queue_rebuild()

    def hrir_ok(self):
        return presets.wav_channels(self.settings.hrir) == 14

    def queue_rebuild(self):
        if not self._rebuild_id:
            self._rebuild_id = GLib.idle_add(self._rebuild)

    def _rebuild(self):
        self._rebuild_id = 0
        sink = self.output
        if not self.running or sink is None or not self.pw.node_id(graph.SINK):
            return False
        route, conf = self._build(sink)
        if route != self.route:
            self.route = route
            self.emit("state-changed")
        if conf == self._conf and self._proc and self._proc.poll() is None:
            return False
        self._conf = conf
        path = config.runtime_dir() / "effects.conf"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(conf)
        self._stop_chain()
        self._proc = subprocess.Popen(["pipewire", "-c", str(path)], preexec_fn=_die_with_parent,
                                      stdin=subprocess.DEVNULL)
        GLib.child_watch_add(GLib.PRIORITY_DEFAULT, self._proc.pid, self._on_chain_exit, self._proc)
        return False

    def _build(self, sink):
        route = graph.choose_route(len(LAYOUTS[self.settings.layout]), sink.channels, self.settings.downmix,
                                   self.hrir_ok())
        return route, graph.build(self.preset, self.settings.enabled, route, self.settings.layout,
                                  self.settings.hrir, sink.name)

    def _on_chain_exit(self, _pid, status, proc):
        proc.poll()
        if proc is self._proc:
            self._proc = None
            self._conf = ""
            print(f"soundstage: filter-chain exited with status {status}")
            self.emit("state-changed")

    def _stop_chain(self):
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        self._proc = None

    @property
    def chain_running(self):
        return self._proc is not None and self._proc.poll() is None

    def changed(self, effect_id, structural=False):
        """Called after the UI edits the preset; saves it and applies the change."""
        self._queue_save()
        if structural or not self.preset:
            self.queue_rebuild()
            return
        effect = plugins.effect(presets.kind_of(effect_id))
        controls = graph.live_controls(effect_id, effect, self.preset.settings(effect_id))
        if controls is None:
            self.queue_rebuild()
        elif self.preset.enabled(effect_id):
            self.pw.set_controls(graph.CAPTURE, controls)
            # The running chain now matches the edited preset, so it needs no restart.
            if self.output:
                self._conf = self._build(self.output)[1]

    def _queue_save(self):
        if self._save_id:
            GLib.source_remove(self._save_id)
        self._save_id = GLib.timeout_add(500, self._on_save_timeout)

    def _on_save_timeout(self):
        self._save_id = 0
        return self._flush_save()

    def _flush_save(self):
        if self._save_id:
            GLib.source_remove(self._save_id)
            self._save_id = 0
        if self.preset:
            self.preset.save()
        return False
