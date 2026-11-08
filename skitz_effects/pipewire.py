"""Live view of PipeWire's devices and defaults, fed by `pw-dump --monitor`."""

import json
import time
from dataclasses import dataclass

from gi.repository import Gio, GLib, GObject

OWN_PREFIX = "skitz_"


@dataclass
class Device:
    id: int
    name: str
    description: str
    channels: int
    priority: int
    virtual: bool
    positions: tuple = ()
    # The sound card's own name, such as "Midas UMC22", and its PipeWire id.
    card: str = ""
    card_id: int | None = None
    # The rate the device is running at, or 0 while it is suspended.
    rate: int = 0


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


def _positions(info):
    """A device's channel positions, such as ("FL", "FR") or ("MONO",)."""
    position = info.get("props", {}).get("audio.position")
    if isinstance(position, str):
        # Props carry it as text, such as "FL,FR" or "[ MONO ]".
        position = position.strip("[] ").replace(",", " ").split()
    if not position:
        for fmt in info.get("params", {}).get("Format") or []:
            position = fmt.get("position")
    return tuple(position or ())


def _rate(info):
    for fmt in info.get("params", {}).get("Format") or []:
        if isinstance(fmt.get("rate"), int):
            return fmt["rate"]
    return 0


def layout_name(positions, channels):
    """A short name for a stream's channel layout, such as "Stereo" or "7.1"."""
    channels = len(positions) or channels
    named = {1: "Mono", 2: "Stereo", 6: "5.1", 8: "7.1"}
    if channels in (6, 8) and positions and "LFE" not in positions:
        return f"{channels} channels"
    return named.get(channels, f"{channels} channels")


def run(argv):
    try:
        Gio.Subprocess.new(argv, Gio.SubprocessFlags.STDOUT_SILENCE | Gio.SubprocessFlags.STDERR_SILENCE)
    except GLib.Error as e:
        print(f"skitz-effects: {argv[0]}: {e.message}")


class PipeWire(GObject.Object):
    __gsignals__ = {"changed": (GObject.SignalFlags.RUN_FIRST, None, ())}

    def __init__(self):
        super().__init__()
        self.ready = False
        self._controls = {}
        self._controls_id = 0
        self._proc = None
        self._start()

    def _start(self):
        # A restarted pw-dump describes a new daemon from scratch, with new ids.
        self.objects = {}
        self.metadata = {}
        # Actions sent but not yet seen in pw-dump, as {key: deadline}; see _once().
        self._pending = {}
        self._reloading = set()
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
        # props at the top level and list only the entries that changed, each one
        # keyed by the object it is about (its subject) as well as its key.
        # A removed entry shows up only as an empty list, without saying which.
        for obj in batch:
            oid = obj["id"]
            if obj.get("metadata"):
                entries = self.metadata.setdefault(oid, {})
                for m in obj["metadata"]:
                    key = (m.get("subject", 0), m["key"])
                    if m.get("value") is None:
                        entries.pop(key, None)
                    else:
                        entries[key] = m["value"]
            elif obj.get("metadata") == [] and oid in self.metadata:
                self._reload_metadata(oid)
            if "type" in obj:
                self.objects[oid] = obj
            elif obj.get("info", obj.get("metadata", 0)) is None:
                self.objects.pop(oid, None)
                self.metadata.pop(oid, None)
                # Ids are reused, so a closed stream's entries must not carry over to the next.
                for entries in self.metadata.values():
                    for key in [k for k in entries if k[0] == oid]:
                        del entries[key]
            elif obj.get("info") and oid in self.objects:
                self.objects[oid]["info"] = obj["info"]
        self.ready = True
        defaults = (self.default("Audio/Sink"), self.default("Audio/Source"))
        for key in list(self._pending):
            action, target = key
            if (action == "create" and self.node_id(target) is not None
                    or action == "destroy" and target not in self.objects
                    or action == "default" and target in defaults
                    or action == "link" and self.linked(*target)
                    or action == "move" and self.stream_target(target[0]) == target[1]):
                del self._pending[key]
        self.emit("changed")

    def _reload_metadata(self, oid):
        if oid in self._reloading:
            return
        self._reloading.add(oid)
        try:
            proc = Gio.Subprocess.new(["pw-dump", "--no-colors", str(oid)], Gio.SubprocessFlags.STDOUT_PIPE)
        except GLib.Error:
            self._reloading.discard(oid)
            return
        proc.communicate_utf8_async(None, None, self._on_metadata_reloaded, oid)

    def _on_metadata_reloaded(self, proc, result, oid):
        self._reloading.discard(oid)
        try:
            _ok, out, _err = proc.communicate_utf8_finish(result)
            dump = json.loads(out or "[]")
        except (GLib.Error, ValueError):
            return
        for obj in dump:
            if obj.get("id") == oid and oid in self.metadata:
                self.metadata[oid] = {(m.get("subject", 0), m["key"]): m["value"]
                                      for m in obj.get("metadata") or [] if m.get("value") is not None}
                self.emit("changed")

    def _once(self, action, target):
        """False while the same action is still on its way, so a burst of updates sends it only once.

        pw-cli and wpctl return before pw-dump reports the result, and every update
        in between would otherwise repeat the action. Unanswered actions are retried
        after two seconds.
        """
        now = time.monotonic()
        if self._pending.get((action, target), 0) > now:
            return False
        self._pending[(action, target)] = now + 2
        return True

    def _default_metadata(self):
        for oid, entries in self.metadata.items():
            if self.objects.get(oid, {}).get("props", {}).get("metadata.name") == "default":
                return entries
        return {}

    def _default(self, key):
        value = self._default_metadata().get((0, key))
        return value.get("name", "") if isinstance(value, dict) else ""

    def fallback(self, media_class):
        """WirePlumber's own pick while the configured default is missing, as GNOME shows it."""
        kind = "sink" if media_class == "Audio/Sink" else "source"
        return self._default(f"default.audio.{kind}")

    def stream_target(self, oid):
        """Where a stream has been sent with target.object metadata, or ""."""
        value = self._default_metadata().get((oid, "target.object"))
        return value if isinstance(value, str) else ""

    def move(self, oid, target):
        """Sends one stream to a node, or with an empty target back to the default."""
        if not self._once("move", (oid, target)):
            return
        if target:
            run(["pw-metadata", str(oid), "target.object", target, "Spa:String"])
        else:
            run(["pw-metadata", "-d", str(oid), "target.object"])

    def streams(self, media_class):
        """App streams of one class ("Stream/Output/Audio" or "Stream/Input/Audio") as (id, props)."""
        for oid, info in self.nodes():
            props = info.get("props", {})
            if props.get("media.class") == media_class:
                yield oid, props

    def stream_channels(self, oid):
        """A stream's channel count once its format is set, or 0 before that."""
        info = (self.objects.get(oid) or {}).get("info") or {}
        formats = info.get("params", {}).get("Format") or []
        return next((f["channels"] for f in formats if isinstance(f.get("channels"), int)), 0)

    def upmixes(self, oid):
        """Whether a stream spreads its channels over speakers it has no audio for."""
        info = (self.objects.get(oid) or {}).get("info") or {}
        for props in info.get("params", {}).get("Props") or []:
            # Props carry the converter's settings as a flat [key, value, key, value, ...] list.
            values = props.get("params") or []
            for key, value in zip(values[::2], values[1::2]):
                if key == "channelmix.upmix":
                    return bool(value)
        return False

    def stop_upmix(self, oid):
        if self._once("stop-upmix", oid):
            run(["pw-cli", "set-param", str(oid), "Props", '{ params = [ "channelmix.upmix" false ] }'])

    def layout(self, oid):
        """A node's channel layout name; streams report theirs as soon as their format is set."""
        info = (self.objects.get(oid) or {}).get("info") or {}
        return layout_name(_positions(info), _channels(info))

    def default(self, media_class):
        # The configured default is the user's choice. WirePlumber's effective default also
        # wanders through each device as they reappear after a restart.
        kind = "sink" if media_class == "Audio/Sink" else "source"
        return self._default(f"default.configured.audio.{kind}")

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

    def node_description(self, name):
        oid = self.node_id(name)
        return ((self.objects.get(oid) or {}).get("info") or {}).get("props", {}).get("node.description", "")

    def node_names(self):
        return [info.get("props", {}).get("node.name", "") for _oid, info in self.nodes()]

    def devices(self, media_class, exclude=()):
        """Best first; leaves out Skitz Effects' own nodes and any whose name starts with one in exclude."""
        out = []
        for oid, info in self.nodes():
            props = info.get("props", {})
            name = props.get("node.name", "")
            if props.get("media.class") != media_class or name.startswith((OWN_PREFIX, *exclude)):
                continue
            card_id = props.get("device.id")
            card = ((self.objects.get(card_id) or {}).get("info") or {}).get("props", {})
            out.append(Device(oid, name, props.get("node.description") or name, _channels(info),
                              int(props.get("priority.session", 0)), bool(props.get("node.virtual")),
                              _positions(info), card.get("device.description", ""), card_id, _rate(info)))
        return sorted(out, key=lambda d: (d.virtual, -d.priority, d.description.casefold()))

    def linked(self, out_name, in_name):
        out_id, in_id = self.node_id(out_name), self.node_id(in_name)
        return any(obj.get("type") == "PipeWire:Interface:Link"
                   and (obj.get("info") or {}).get("output-node-id") == out_id
                   and (obj.get("info") or {}).get("input-node-id") == in_id
                   for obj in self.objects.values())

    def link(self, out_name, in_name):
        """Links every port of one node to the next, passively, and keeps the links after pw-link exits."""
        if self._once("link", (out_name, in_name)):
            run(["pw-link", "--passive", "--linger", out_name, in_name])

    def profiles(self, card_id):
        """A card's profiles as [(index, name)], and the name of the one in use."""
        params = ((self.objects.get(card_id) or {}).get("info") or {}).get("params", {})
        listed = [(p["index"], p["name"]) for p in params.get("EnumProfile") or [] if p.get("available") != "no"]
        current = next((p.get("name", "") for p in params.get("Profile") or []), "")
        return listed, current

    def set_profile(self, card_id, index):
        run(["wpctl", "set-profile", str(card_id), str(index)])

    def set_default(self, name):
        oid = self.node_id(name)
        if oid is not None and self._once("default", name):
            run(["wpctl", "set-default", str(oid)])

    def set_controls(self, name, controls):
        """Queues control updates; a drag sends one pw-cli call per frame rather than per motion event."""
        if not controls:
            return
        self._controls.setdefault(name, {}).update(controls)
        if not self._controls_id:
            self._controls_id = GLib.timeout_add(30, self._send_controls)

    def _send_controls(self):
        self._controls_id = 0
        queued, self._controls = self._controls, {}
        for name, controls in queued.items():
            oid = self.node_id(name)
            if oid is None:
                continue
            params = []
            for key, value in controls.items():
                params += [key, value]
            run(["pw-cli", "set-param", str(oid), "Props", json.dumps({"params": params})])
        return False

    def _oid(self, node):
        return node if isinstance(node, int) else self.node_id(node)

    def volume(self, node):
        """A node's volume (by name or id) on wpctl's cubic scale, 1.0 being unity, and whether it is muted."""
        oid = self._oid(node)
        for props in ((self.objects.get(oid) or {}).get("info") or {}).get("params", {}).get("Props") or []:
            if "channelVolumes" in props:
                levels = props["channelVolumes"] or [1.0]
                return max(levels) ** (1 / 3), bool(props.get("mute"))
        return None, False

    def set_volume(self, node, volume):
        oid = self._oid(node)
        if oid is not None:
            run(["wpctl", "set-volume", str(oid), f"{max(volume, 0.0):.3f}"])

    def set_mute(self, node, mute):
        oid = self._oid(node)
        if oid is not None:
            run(["wpctl", "set-mute", str(oid), "1" if mute else "0"])

    def create_virtual(self, name, description, media_class, positions):
        if not self._once("create", name):
            return
        props = {
            "factory.name": "support.null-audio-sink",
            "node.name": name,
            "node.description": description,
            "media.class": media_class,
            "audio.channels": len(positions),
            "audio.position": list(positions),
            "monitor.channel-volumes": True,
            # Keeps the node after pw-cli exits, so apps stay connected while effects restart.
            "object.linger": True,
        }
        run(["pw-cli", "create-node", "adapter", json.dumps(props)])

    def destroy(self, name):
        oid = self.node_id(name)
        if oid is not None and self._once("destroy", oid):
            run(["pw-cli", "destroy", str(oid)])
