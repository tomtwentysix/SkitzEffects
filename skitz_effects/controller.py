"""Keeps the virtual devices, the filter-chain processes and the loaded presets in step with PipeWire."""

import ctypes
import os
import signal
import subprocess
import time

from gi.repository import GLib, GObject

from . import config, deps, graph, names, plugins, presets
from .config import LAYOUTS
from .pipewire import PipeWire

PR_SET_PDEATHSIG = 1
# Seconds a chosen device may be gone before another one stands in for it.
MISSING_GRACE = 5


def input_variants(profiles, current):
    """The card profiles that keep the current output side and differ only in their input.

    profiles is [(index, name)] with names such as
    "output:analog-stereo-output+input:analog-mono"; returns [(index, input part)].
    """
    keep = "+".join(part for part in current.split("+") if not part.startswith("input:"))
    out = []
    for index, name in profiles:
        parts = name.split("+")
        inputs = [part[len("input:"):] for part in parts if part.startswith("input:")]
        if inputs and "+".join(part for part in parts if not part.startswith("input:")) == keep:
            out.append((index, inputs[0]))
    return out


LAYOUT_TITLES = {"stereo": "Effects", "5.1": "5.1 Surround", "7.1": "7.1 Surround"}


def app_key(props):
    """How Easy Effects names an app in a preset's blocklist."""
    return props.get("application.id") or props.get("application.name") or props.get("node.name", "")


def truthy(value):
    return value is True or str(value).lower() == "true"


# Streams aimed at Easy Effects were set up to go through effects, so they come here instead.
EASY_EFFECTS_TARGETS = {"easyeffects_sink", "easyeffects_source"}


def routable(props):
    """Whether an app stream should go through Skitz Effects.

    Left out: Skitz Effects' own streams, other filters and loopbacks (they have a
    link group), streams that capture a sink's monitor or only measure levels,
    and streams that name their own target, unless that target is Easy Effects.
    """
    if props.get("node.name", "").startswith("skitz_"):
        return False
    if {props.get("target.object"), props.get("node.target")} & EASY_EFFECTS_TARGETS:
        return True
    return not (props.get("node.link-group")
                or truthy(props.get("stream.capture.sink")) or truthy(props.get("stream.monitor"))
                or props.get("target.object") or props.get("node.target"))


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
        self.stream_class = "Stream/Output/Audio" if output else "Stream/Input/Audio"
        self.virtual = graph.SINK if output else graph.SOURCE
        self.virtual_class = "Audio/Sink" if output else "Audio/Source/Virtual"
        self.virtual_description = "Skitz Effects Microphone"
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
        fallback = self.pw.fallback(self.media_class)
        stand_ins = [d for d in devices if d.name == fallback] + [d for d in devices if not d.virtual]
        return stand_ins[0] if stand_ins else None

    def display_name(self, device):
        """Inputs show the card's name, since what they record is a setting of the device."""
        custom = names.custom().get(("node", device.name))
        if self.direction == "input" and device.card and not custom:
            return device.card
        return device.description

    def switch_profile(self, device, index):
        """Moves a card to another profile; sync() then follows its renamed node."""
        self.pw.set_profile(device.card_id, index)

    def _migrate(self, old, new):
        state = self.state
        for key in ("device_presets", "device_names", "device_channels"):
            if old in state[key]:
                state[key][new] = state[key].pop(old)
        state["device_channels"].pop(new, None)
        if state["device"] == old:
            state["device"] = new
        self.controller.settings.save()
        self.emit("state-changed")

    def positions(self):
        return LAYOUTS[self.controller.settings.layout] if self.direction == "output" else LAYOUTS["stereo"]

    def virtual_label(self):
        """The output sink is named after the device it plays through, which is what GNOME shows."""
        if self.direction == "input":
            return self.virtual_description
        device = self.state["device_names"].get(self.state["device"], "Skitz Effects")
        return f"{device} · {LAYOUT_TITLES[self.controller.settings.layout]}"

    def sync(self):
        pw = self.pw
        positions = self.positions()
        channels = pw.node_channels(self.virtual)
        label = self.virtual_label()
        # Names are fixed once a node exists, so a new device or layout means a new node.
        if channels != len(positions) or (channels and pw.node_description(self.virtual) != label):
            if channels:
                pw.destroy(self.virtual)
            else:
                pw.create_virtual(self.virtual, label, self.virtual_class, positions)
            return
        default = pw.default(self.media_class)
        devices = self.devices()
        if self.state["device"] and not any(d.name == self.state["device"] for d in devices):
            # A card's nodes are named after its profile, so a new profile renames the chosen device.
            base = self.state["device"].rsplit(".", 1)[0] + "."
            siblings = [d.name for d in devices if d.name.startswith(base)]
            if len(siblings) == 1:
                self._migrate(self.state["device"], siblings[0])
        if self.direction == "output":
            # Apps pick their channel count from the default output, so it is Skitz Effects' sink,
            # which has the surround layout. Choosing a device elsewhere, such as in GNOME, still
            # switches Skitz Effects to it.
            if any(d.name == default for d in devices):
                self.select_device(default)
            if default != self.virtual:
                pw.set_default(self.virtual)
        elif any(d.name == default for d in devices):
            # The mic stays the default, as GNOME shows it, and Skitz Effects records through it.
            self.select_device(default)
        elif any(d.name == self.state["device"] for d in devices):
            pw.set_default(self.state["device"])
        if not self.state["device"]:
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
        self._route_streams()
        self.queue_rebuild()

    def _route_streams(self):
        """Sends every app stream through Skitz Effects while its chain runs, unless the mixer leaves it out.

        This overrides targets restored by WirePlumber, such as an old Easy Effects sink. Streams
        that name their own target are left alone, and a stream left out or waiting for the chain
        goes back to the default only if Skitz Effects had sent it here.
        """
        pw = self.pw
        for oid, props in pw.streams(self.stream_class):
            if not routable(props):
                continue
            current = pw.stream_target(oid)
            if self.chain_running and not self.blocked(props):
                if current != self.virtual:
                    pw.move(oid, self.virtual)
            elif current == self.virtual:
                pw.move(oid, "")

    def blocked(self, props):
        """Apps left out of the effects, kept in the preset's blocklist as Easy Effects does."""
        return bool(self.preset) and app_key(props) in self.preset.section.get("blocklist", [])

    def set_blocked(self, props, on):
        if self.preset is None:
            return
        blocklist = self.preset.section.setdefault("blocklist", [])
        key = app_key(props)
        if on and key not in blocklist:
            blocklist.append(key)
        elif not on and key in blocklist:
            blocklist.remove(key)
        self._queue_save()
        self._route_streams()

    def select_device(self, name):
        target = self.virtual if self.direction == "output" else name
        if self.pw and self.pw.default(self.media_class) != target:
            self.pw.set_default(target)
        if name == self.state["device"]:
            return
        self.state["device"] = name
        device = next((d for d in self.devices() if d.name == name), None)
        if device:
            self.state["device_names"][name] = self.display_name(device)
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
        self.emit("state-changed")
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
            channel = self.state["device_channels"].get(device.name, "")
            if not channel and "MONO" in device.positions and len(device.positions) > 1:
                # ALSA's left and right mono profiles keep the unused input as AUX1, which would
                # otherwise reach the effects' right side.
                channel = "MONO"
            return "stereo", graph.build_input(self.preset, enabled, device.name, channel, device.positions)
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
            print(f"skitz-effects: {self.direction} filter-chain lost its streams, restarting")
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
            print(f"skitz-effects: {self.direction} filter-chain exited with status {status}")
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
        self._route_streams()
        if self.direction == "output" and self.state["device"]:
            # Hand the default back to the device, or WirePlumber picks one of its own.
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
        self._rates = set()

    @property
    def pipelines(self):
        return (self.output, self.input)

    def start(self):
        if self.running:
            return
        self.running = True
        self._load_rates()
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
        self._load_rates()
        for pipeline in self.pipelines:
            pipeline.restart()

    def _load_rates(self):
        """Sample rates pinned in Device Settings, which the graph has to be allowed to run at."""
        rates = {props[names.RATE] for props in names.rules().values() if names.RATE in props}
        self._rates = rates | {48000} if rates else set()

    def _on_pipewire(self, pw):
        if self._rates:
            pw.allow_rates(self._rates)
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
