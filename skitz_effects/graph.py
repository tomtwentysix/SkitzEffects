"""Builds the PipeWire filter-chain configs that do all of the processing.

Apps play into a lingering 5.1/7.1 null sink. The output filter-chain captures
that sink's monitor, runs the effects and plays into the real device. The input
filter-chain captures the microphone and plays into a lingering virtual source
that apps record from. A stereo
effect chain with fewer inputs than the stream has channels is instantiated
once per channel pair by filter-chain, which is how effects reach every
speaker on a surround device.
"""

import json
import re
from pathlib import Path

from . import plugins, presets
from .config import LAYOUTS

SINK = "skitz_sink"
CAPTURE = "skitz_effects"
PLAYBACK = "skitz_output"
SOURCE = "skitz_source"
MIC_CAPTURE = "skitz_mic"
MIC_PLAYBACK = "skitz_mic_output"

# Channel indices in a HeSuVi 14-channel HRIR, as (left ear, right ear).
HESUVI = {"FL": (0, 1), "SL": (2, 3), "RL": (4, 5), "FC": (6, 13), "FR": (8, 7), "SR": (10, 9), "RR": (12, 11)}
# 5.1 surrounds sit beside the listener, so they take the side IRs; LFE is placed like FC.
HRIR_SOURCE = {"5.1": {"RL": "SL", "RR": "SR", "LFE": "FC"}, "7.1": {"LFE": "FC"}}


def choose_route(layout_channels, device_channels, downmix, hrir_ok):
    """Decides how the surround stream reaches the device.

    Returns "passthrough" (every channel goes to the device), "hrir"
    (binaural downmix through the HRIR) or "stereo" (PipeWire's plain downmix).
    downmix is the user's setting: "auto", "always" or "never".
    """
    if layout_channels <= 2:
        return "passthrough"
    # "always" is for headphones that report surround channels, such as USB gaming headsets.
    if downmix == "always":
        return "hrir" if hrir_ok else "stereo"
    if device_channels >= layout_channels:
        return "passthrough"
    return "hrir" if downmix == "auto" and hrir_ok else "stereo"


def node_name(effect_id):
    return re.sub(r"\W", "_", effect_id)


def db(value):
    return 10 ** (float(value) / 20)


class Graph:
    def __init__(self):
        self.nodes = []
        self.links = []

    def add(self, **node):
        self.nodes.append(node)
        return node["name"]

    def link(self, out, into):
        self.links.append({"output": out, "input": into})

    def copy(self, name):
        return self.add(type="builtin", label="copy", name=name)

    def mixer(self, name, sources):
        self.add(type="builtin", label="mixer", name=name)
        for i, src in enumerate(sources, 1):
            self.link(src, f"{name}:In {i}")
        return f"{name}:Out"

    def convolver(self, name, path, channel, gain=1.0, source=None):
        self.add(type="builtin", label="convolver", name=name,
                 config={"filename": str(path), "channel": channel, "gain": gain})
        if source:
            self.link(source, f"{name}:In")
        return f"{name}:Out"


def resolve_ir(settings):
    name = settings.get("kernel-name") or ""
    path = Path(settings.get("kernel-path") or "")
    if path.is_file():
        return path
    return presets.list_irs().get(name)


def add_effect(graph, effect_id, effect, settings, left, right):
    """Wires one effect after the (left, right) outputs; returns its outputs."""
    name = node_name(effect_id)
    if effect.kind == "convolver":
        path = resolve_ir(settings)
        if not path:
            return left, right
        gain = db(settings.get("input-gain", 0) + settings.get("output-gain", 0))
        if presets.wav_channels(path) >= 4:
            # True stereo IR, channels are LL, LR, RL, RR.
            ll = graph.convolver(f"{name}_ll", path, 0, gain, left)
            lr = graph.convolver(f"{name}_lr", path, 1, gain, left)
            rl = graph.convolver(f"{name}_rl", path, 2, gain, right)
            rr = graph.convolver(f"{name}_rr", path, 3, gain, right)
            return graph.mixer(f"{name}_l", [ll, rl]), graph.mixer(f"{name}_r", [lr, rr])
        stereo = presets.wav_channels(path) >= 2
        return (graph.convolver(f"{name}_l", path, 0, gain, left),
                graph.convolver(f"{name}_r", path, 1 if stereo else 0, gain, right))
    in_l, in_r, out_l, out_r = effect.ports
    if effect.gain_nodes:
        left, right = gain_stage(graph, f"{name}_in", settings.get("input-gain", 0), left, right)
    if effect.ladspa:
        graph.add(type="ladspa", plugin=effect.ladspa, label=effect.uri, name=name, control=effect.controls(settings))
    else:
        graph.add(type="lv2", plugin=effect.uri, name=name, control=effect.controls(settings))
    graph.link(left, f"{name}:{in_l}")
    graph.link(right, f"{name}:{in_r}")
    left, right = f"{name}:{out_l}", f"{name}:{out_r}"
    if effect.gain_nodes:
        left, right = gain_stage(graph, f"{name}_out", settings.get("output-gain", 0), left, right)
    return left, right


def gain_stage(graph, name, gain, left, right):
    for side, src in (("l", left), ("r", right)):
        graph.add(type="builtin", label="linear", name=f"{name}_{side}", control={"Mult": db(gain), "Add": 0.0})
        graph.link(src, f"{name}_{side}:In")
    return f"{name}_l:Out", f"{name}_r:Out"


def hrir_downmix(graph, layout, hrir):
    remap = HRIR_SOURCE.get(layout, {})
    left, right = [], []
    for ch in LAYOUTS[layout]:
        src = graph.copy(f"in_{ch}")
        ir_l, ir_r = HESUVI[remap.get(ch, ch)]
        left.append(graph.convolver(f"hrir_{ch}_l", hrir, ir_l, source=f"{src}:Out"))
        right.append(graph.convolver(f"hrir_{ch}_r", hrir, ir_r, source=f"{src}:Out"))
    inputs = [f"in_{ch}:In" for ch in LAYOUTS[layout]]
    return inputs, graph.mixer("hrir_mix_l", left), graph.mixer("hrir_mix_r", right)


def effect_chain(preset, enabled):
    if preset is None or not enabled:
        return []
    chain = []
    for effect_id in preset.order:
        effect = plugins.effect(presets.kind_of(effect_id))
        if preset.enabled(effect_id) and effect.available():
            chain.append((effect_id, effect, preset.settings(effect_id)))
    return chain


def stereo_chain(graph, preset, enabled, left, right):
    for effect_id, effect, settings in effect_chain(preset, enabled):
        left, right = add_effect(graph, effect_id, effect, settings, left, right)
    return [left, right]


def plain_inputs(graph):
    return [f"{graph.copy('in_l')}:In", f"{graph.copy('in_r')}:In"], "in_l:Out", "in_r:Out"


def config_text(description, graph, inputs, outputs, capture, playback):
    # Both ends are passive, so nothing is held open while no app is playing or recording.
    module = {
        "name": "libpipewire-module-filter-chain",
        "args": {
            "node.description": description,
            "media.name": description,
            "filter.graph": {"nodes": graph.nodes, "links": graph.links, "inputs": inputs, "outputs": outputs},
            "capture.props": {"node.passive": True, "node.dont-fallback": True, **capture},
            "playback.props": {"node.passive": True, "node.dont-fallback": True, "node.dont-reconnect": True,
                               **playback},
        },
    }
    conf = {
        "context.properties": {"log.level": 0},
        "context.spa-libs": {"audio.convert.*": "audioconvert/libspa-audioconvert",
                             "support.*": "support/libspa-support"},
        "context.modules": [
            {"name": "libpipewire-module-rt", "flags": ["ifexists", "nofail"]},
            {"name": "libpipewire-module-protocol-native"},
            {"name": "libpipewire-module-client-node"},
            {"name": "libpipewire-module-adapter"},
            module,
        ],
    }
    return json.dumps(conf, indent=2)


def without_realtime(text):
    """The same config with no realtime priority for the chain's audio thread."""
    conf = json.loads(text)
    conf["context.modules"] = [m for m in conf["context.modules"] if m["name"] != "libpipewire-module-rt"]
    return json.dumps(conf, indent=2)


def channels(positions):
    return {"audio.channels": len(positions), "audio.position": list(positions)}


def build(preset, enabled, route, layout, hrir, target):
    graph = Graph()
    if route == "hrir":
        inputs, left, right = hrir_downmix(graph, layout, hrir)
    else:
        inputs, left, right = plain_inputs(graph)
    outputs = stereo_chain(graph, preset, enabled, left, right)
    capture = LAYOUTS[layout] if route in ("passthrough", "hrir") else LAYOUTS["stereo"]
    playback = LAYOUTS[layout] if route == "passthrough" else LAYOUTS["stereo"]
    return config_text(
        "Skitz Effects Output", graph, inputs, outputs,
        {"node.name": CAPTURE, "target.object": SINK, "stream.capture.sink": True, **channels(capture)},
        {"node.name": PLAYBACK, "target.object": target, **channels(playback)},
    )


def build_input(preset, enabled, device, channel="", positions=()):
    """The mic chain; with a channel, only that one of the device's positions feeds both sides."""
    graph = Graph()
    stereo = channels(LAYOUTS["stereo"])
    if channel in positions:
        source = graph.copy("in_l")
        # A null input discards that channel of the capture.
        inputs = [f"{source}:In" if position == channel else None for position in positions]
        left = right = f"{source}:Out"
        capture = channels(positions)
    else:
        inputs, left, right = plain_inputs(graph)
        capture = stereo
    outputs = stereo_chain(graph, preset, enabled, left, right)
    return config_text(
        "Skitz Effects Microphone", graph, inputs, outputs,
        {"node.name": MIC_CAPTURE, "target.object": device, **capture},
        # WirePlumber only links playback streams to sinks, so the controller links this one to the source.
        {"node.name": MIC_PLAYBACK, "node.autoconnect": False, **stereo},
    )


def live_controls(effect_id, effect, settings):
    """Control updates for a running chain, keyed "node:port" as filter-chain expects."""
    if effect.kind == "convolver":
        return None
    name = node_name(effect_id)
    controls = {f"{name}:{port}": value for port, value in effect.controls(settings).items()}
    if effect.gain_nodes:
        for stage, key in (("in", "input-gain"), ("out", "output-gain")):
            for side in "lr":
                controls[f"{name}_{stage}_{side}:Mult"] = db(settings.get(key, 0))
    return controls
