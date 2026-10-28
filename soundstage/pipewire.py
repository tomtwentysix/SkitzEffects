"""Live view of PipeWire's sinks and default device, fed by `pw-dump --monitor`."""

import json
from dataclasses import dataclass

from gi.repository import Gio, GLib, GObject

OWN_PREFIX = "soundstage_"


@dataclass
class Sink:
    id: int
    name: str
    description: str
    channels: int
    priority: int
    virtual: bool


def _channels(info):
    props = info.get("props", {})
    if isinstance(props.get("audio.channels"), int):
        return props["audio.channels"]
    params = info.get("params", {})
    for fmt in params.get("Format") or []:
        if isinstance(fmt.get("channels"), int):
            return fmt["channels"]
    best = 0
    for fmt in params.get("EnumFormat") or []:
        ch = fmt.get("channels")
        # Choice values come through as {"default": n, "min": a, "max": b}.
        best = max(best, ch.get("max", ch.get("default", 0)) if isinstance(ch, dict) else ch or 0)
    return best or 2


def run(argv):
    try:
        Gio.Subprocess.new(argv, Gio.SubprocessFlags.STDOUT_SILENCE | Gio.SubprocessFlags.STDERR_SILENCE)
    except GLib.Error as e:
        print(f"soundstage: {argv[0]}: {e.message}")


class PipeWire(GObject.Object):
    __gsignals__ = {"changed": (GObject.SignalFlags.RUN_FIRST, None, ())}

    def __init__(self):
        super().__init__()
        self.objects = {}
        self.metadata = {}
        self.ready = False
        self._lines = []
        self._proc = None
        self._start()

    def _start(self):
        self._proc = Gio.Subprocess.new(["pw-dump", "--monitor", "--no-colors"], Gio.SubprocessFlags.STDOUT_PIPE)
        self._stream = Gio.DataInputStream.new(self._proc.get_stdout_pipe())
        self._lines = []
        self._read()

    def stop(self):
        if self._proc:
            self._proc.force_exit()
            self._proc = None

    def _read(self):
        self._stream.read_line_async(GLib.PRIORITY_DEFAULT, None, self._on_line)

    def _on_line(self, stream, result):
        try:
            line, _ = stream.read_line_finish_utf8(result)
        except GLib.Error:
            line = None
        if line is None:
            if self._proc:  # pw-dump died, usually because PipeWire restarted.
                GLib.timeout_add_seconds(1, lambda: self._start() and False)
            return
        self._lines.append(line)
        # Each update is one pretty-printed JSON array that closes on a bare "]".
        if line == "]":
            try:
                batch = json.loads("\n".join(self._lines))
            except ValueError:
                batch = []
            self._lines = []
            self._apply(batch)
        self._read()

    def _apply(self, batch):
        # Removals arrive as {"id": n, "info": null}; metadata objects carry their
        # props at the top level and list only the keys that changed.
        for obj in batch:
            oid = obj["id"]
            if obj.get("metadata"):
                entries = self.metadata.setdefault(oid, {})
                for m in obj["metadata"]:
                    if m.get("value") is None:
                        entries.pop(m["key"], None)
                    else:
                        entries[m["key"]] = m["value"]
            if "type" in obj:
                self.objects[oid] = obj
            elif obj.get("info", obj.get("metadata", 0)) is None:
                self.objects.pop(oid, None)
                self.metadata.pop(oid, None)
            elif obj.get("info") and oid in self.objects:
                self.objects[oid]["info"] = obj["info"]
        self.ready = True
        self.emit("changed")

    def _default(self, key):
        for oid, entries in self.metadata.items():
            if self.objects.get(oid, {}).get("props", {}).get("metadata.name") == "default":
                value = entries.get(key)
                return value.get("name", "") if isinstance(value, dict) else ""
        return ""

    @property
    def default_sink(self):
        return self._default("default.audio.sink")

    def nodes(self):
        for oid, obj in self.objects.items():
            if obj.get("type") == "PipeWire:Interface:Node" and obj.get("info"):
                yield oid, obj["info"]

    def node_id(self, name):
        for oid, info in self.nodes():
            if info.get("props", {}).get("node.name") == name:
                return oid
        return None

    def node_channels(self, name):
        for _oid, info in self.nodes():
            if info.get("props", {}).get("node.name") == name:
                return _channels(info)
        return 0

    def sinks(self):
        out = []
        for oid, info in self.nodes():
            props = info.get("props", {})
            name = props.get("node.name", "")
            if props.get("media.class") != "Audio/Sink" or name.startswith(OWN_PREFIX):
                continue
            out.append(Sink(oid, name, props.get("node.description") or name, _channels(info),
                            int(props.get("priority.session", 0)), bool(props.get("node.virtual"))))
        return sorted(out, key=lambda s: (s.virtual, -s.priority, s.description.casefold()))

    def sink(self, name):
        return next((s for s in self.sinks() if s.name == name), None)

    def set_default(self, name):
        oid = self.node_id(name)
        if oid is not None:
            run(["wpctl", "set-default", str(oid)])

    def set_controls(self, name, controls):
        oid = self.node_id(name)
        if oid is None or not controls:
            return
        params = []
        for key, value in controls.items():
            params += [key, value]
        run(["pw-cli", "set-param", str(oid), "Props", json.dumps({"params": params})])

    def create_sink(self, name, description, positions):
        props = {
            "factory.name": "support.null-audio-sink",
            "node.name": name,
            "node.description": description,
            "media.class": "Audio/Sink",
            "audio.channels": len(positions),
            "audio.position": list(positions),
            "monitor.channel-volumes": True,
            # Keeps the sink after pw-cli exits, so apps stay connected while effects restart.
            "object.linger": True,
        }
        run(["pw-cli", "create-node", "adapter", json.dumps(props)])

    def destroy(self, name):
        oid = self.node_id(name)
        if oid is not None:
            run(["pw-cli", "destroy", str(oid)])
