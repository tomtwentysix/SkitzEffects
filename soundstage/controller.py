"""Keeps the virtual devices, the filter-chain processes and the loaded presets in step with PipeWire."""

import ctypes
import os
import signal
import subprocess
import time

from gi.repository import GLib, GObject

from . import config, deps, graph, plugins, presets
from .config import LAYOUTS
from .pipewire import PipeWire

PR_SET_PDEATHSIG = 1
# Seconds a chosen device may be gone before another one stands in for it.
MISSING_GRACE = 5


def _die_with_parent():
    ctypes.CDLL("libc.so.6").prctl(PR_SET_PDEATHSIG, signal.SIGTERM)


class Pipeline(GObject.Object):
    """One direction: output (apps -> sink -> effects -> speakers) or input (mic -> effects -> source -> apps)."""

    __gsignals__ = {
        "preset-changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "state-changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self, controller, direction):
        super().__init__()
        self.controller = controller
        self.direction = direction
        output = direction == "output"
        self.media_class = "Audio/Sink" if output else "Audio/Source"
        self.virtual = graph.SINK if output else graph.SOURCE
        self.virtual_class = "Audio/Sink" if output else "Audio/Source/Virtual"
        self.virtual_description = "Soundstage" if output else "Soundstage Microphone"
        self.control_node = graph.CAPTURE if output else graph.MIC_CAPTURE
        self.preset = presets.load(self.state["preset"], direction) if self.state["preset"] else None
        self.route = ""
        self._proc = None
        self._started = 0.0
        self._failures = 0
        self._missing_since = 0.0
        self._conf = ""
        self._save_id = 0
        self._rebuild_id = 0

    @property
    def state(self):
        return getattr(self.controller.settings, self.direction)

    @property
    def pw(self):
        return self.controller.pw

    def devices(self):
        return self.pw.devices(self.media_class, deps.CONFLICT_NODES) if self.pw else []

    @property
    def device(self):
        """The chosen device, or while it is gone a stand-in that is not saved.

        Devices also vanish for a moment whenever WirePlumber restarts, so the
        stand-in only takes over once the chosen one has been gone for a while.
        """
        devices = self.devices()
        chosen = next((d for d in devices if d.name == self.state["device"]), None)
        if chosen or not self._missing_since or time.monotonic() - self._missing_since < MISSING_GRACE:
            return chosen
        return next((d for d in devices if not d.virtual), None)

    def positions(self):
        return LAYOUTS[self.controller.settings.layout] if self.direction == "output" else LAYOUTS["stereo"]

    def sync(self):
        pw = self.pw
        positions = self.positions()
        channels = pw.node_channels(self.virtual)
        if channels != len(positions):
            if channels:
                pw.destroy(self.virtual)
            else:
                pw.create_virtual(self.virtual, self.virtual_description, self.virtual_class, positions)
            return
        default = pw.default(self.media_class)
        devices = self.devices()
        if default and default != self.virtual and any(d.name == default for d in devices):
            # The user picked a device elsewhere (GNOME Settings, the volume menu):
            # use it and take the default back.
            self.select_device(default)
            pw.set_default(self.virtual)
        elif not self.state["device"]:
            fallback = next((d for d in devices if not d.virtual), None)
            if fallback:
                self.select_device(fallback.name)
        if any(d.name == self.state["device"] for d in devices):
            self._missing_since = 0.0
        elif not self._missing_since:
            self._missing_since = time.monotonic()
            GLib.timeout_add_seconds(MISSING_GRACE + 1, lambda: self.queue_rebuild() or False)
        if self.direction == "input" and pw.node_id(graph.MIC_PLAYBACK):
            if not pw.linked(graph.MIC_PLAYBACK, self.virtual):
                pw.link(graph.MIC_PLAYBACK, self.virtual)
        self._check_chain()
        self.queue_rebuild()

    def select_device(self, name):
        if name == self.state["device"]:
            return
        self.state["device"] = name
        device = next((d for d in self.devices() if d.name == name), None)
        if device:
            self.state["device_names"][name] = device.description
        rule = self.state["device_presets"].get(name)
        if rule and rule in presets.list_presets(self.direction):
            self.load_preset(rule)
        self.controller.settings.save()
        self.emit("state-changed")
        self.queue_rebuild()

    def load_preset(self, name):
        self._flush_save()
        self.preset = presets.load(name, self.direction)
        self.state["preset"] = name if self.preset else ""
        self.controller.settings.save()
        self.emit("preset-changed")
        self.queue_rebuild()

    def new_preset(self, name):
        self._flush_save()
        self.preset = presets.create(name, self.direction)
        self.state["preset"] = name
        self.controller.settings.save()
        self.emit("preset-changed")
        self.queue_rebuild()

    def set_enabled(self, on):
        self.state["enabled"] = on
        self.controller.settings.save()
        self.queue_rebuild()

    def restart(self):
        self._stop_chain()
        self._conf = ""
        self._failures = 0
        self.queue_rebuild()

    def queue_rebuild(self):
        if not self._rebuild_id:
            self._rebuild_id = GLib.idle_add(self._rebuild)

    def _rebuild(self):
        self._rebuild_id = 0
        device = self.device
        if not self.controller.running or device is None or not self.pw.node_id(self.virtual):
            return False
        route, conf = self._build(device)
        if route != self.route:
            self.route = route
            self.emit("state-changed")
        if conf == self._conf and (self.chain_running or self._failures >= 3):
            return False
        if conf != self._conf:
            self._failures = 0
        self._conf = conf
        path = config.runtime_dir() / f"{self.direction}.conf"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(conf)
        self._stop_chain()
        self._proc = subprocess.Popen(["pipewire", "-c", str(path)], preexec_fn=_die_with_parent,
                                      stdin=subprocess.DEVNULL)
        self._started = time.monotonic()
        GLib.child_watch_add(GLib.PRIORITY_DEFAULT, self._proc.pid, self._on_chain_exit, self._proc)
        GLib.timeout_add_seconds(3, self._check_chain)
        self.emit("state-changed")
        return False

    def _build(self, device):
        enabled = self.state["enabled"]
        if self.direction == "input":
            return "stereo", graph.build_input(self.preset, enabled, device.name)
        s = self.controller.settings
        route = graph.choose_route(len(LAYOUTS[s.layout]), device.channels, s.downmix, self.controller.hrir_ok())
        return route, graph.build(self.preset, enabled, route, s.layout, s.hrir, device.name)

    def _check_chain(self):
        """Restarts a chain whose streams were torn down while its process lives on.

        filter-chain destroys its streams when a target goes away and the stream
        may not reconnect, but keeps running with nothing in the graph.
        """
        if not self.chain_running or time.monotonic() - self._started < 3:
            return False
        if self.pw.node_id(self.control_node) is not None:
            self._failures = 0
        elif self._failures < 3:
            self._failures += 1
            print(f"soundstage: {self.direction} filter-chain lost its streams, restarting")
            self._stop_chain()
            self.queue_rebuild()
        else:
            self._stop_chain()
            self.emit("state-changed")
        return False

    def _on_chain_exit(self, _pid, status, proc):
        # GLib reaps the chain, so Popen's own wait() and poll() are never used on it.
        proc.returncode = status
        if proc is self._proc:
            self._proc = None
            self._failures += 1
            print(f"soundstage: {self.direction} filter-chain exited with status {status}")
            self.emit("state-changed")
            self.queue_rebuild()

    def _stop_chain(self):
        proc, self._proc = self._proc, None
        if proc is None or proc.returncode is not None:
            return
        proc.terminate()
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            # WNOWAIT leaves the exit status for the child watch to collect.
            if os.waitid(os.P_PID, proc.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT):
                return
            time.sleep(0.02)
        proc.kill()

    @property
    def chain_running(self):
        return self._proc is not None and self._proc.returncode is None

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
        elif self.preset.enabled(effect_id) and self.pw:
            self.pw.set_controls(self.control_node, controls)
            # The running chain now matches the edited preset, so it needs no restart.
            if self.device:
                self._conf = self._build(self.device)[1]

    def shutdown(self):
        self._flush_save()
        self._stop_chain()
        if self.state["device"]:
            self.pw.set_default(self.state["device"])
        self.pw.destroy(self.virtual)

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


class Controller(GObject.Object):
    __gsignals__ = {
        "devices-changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "conflicts-changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self, settings):
        super().__init__()
        self.settings = settings
        self.pw = None
        self.running = False
        self.conflicts = []
        self.output = Pipeline(self, "output")
        self.input = Pipeline(self, "input")
        self._devices = ()

    @property
    def pipelines(self):
        return (self.output, self.input)

    def start(self):
        if self.running:
            return
        self.running = True
        self.pw = PipeWire()
        self.pw.connect("changed", self._on_pipewire)

    def shutdown(self):
        if not self.running:
            return
        for pipeline in self.pipelines:
            pipeline.shutdown()
        self.pw.stop()
        self.running = False

    def hrir_ok(self):
        return presets.wav_channels(self.settings.hrir) == 14

    def restart_chains(self):
        for pipeline in self.pipelines:
            pipeline.restart()

    def _on_pipewire(self, pw):
        devices = tuple((d.name, d.description, d.channels) for p in self.pipelines for d in p.devices())
        if devices != self._devices:
            self._devices = devices
            self.emit("devices-changed")
        conflicts = deps.running_conflicts(pw.node_names())
        if conflicts != self.conflicts:
            self.conflicts = conflicts
            self.emit("conflicts-changed")
        for pipeline in self.pipelines:
            pipeline.sync()
