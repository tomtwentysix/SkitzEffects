"""Builds the PipeWire filter-chain configs that do all of the processing.

Apps play into a lingering 5.1/7.1 null sink. The output filter-chain captures
that sink's monitor, runs the effects and plays into the real device. The input
filter-chain captures the microphone and plays into a lingering virtual source
that apps record from. A stereo
effect chain with fewer inputs than the stream has channels is instantiated
once per channel pair by filter-chain, which is how effects reach every
speaker on a surround device.

Each step of a chain (the HRIR downmix, then every effect) runs as a filter-chain
of its own in the one process, played from one to the next, so the meters can
tap the audio between steps: filter-chain keeps what passes between the nodes
of one graph to itself.
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
# Added to every sample entering a chain. A game's audio fading out reaches the chain as denormals,
# which run the convolvers' FFTs about 20 times slower: enough to keep a realtime data loop busy until
# the kernel kills it. PipeWire's cpu.zero.denormals cannot prevent that, as it is applied to the main
# thread instead whenever the data loop starts late, which it does under load. The offset keeps every
# value normal, is lost in the rounding of any sample above -180 dB, and is far below a DAC's last bit.
DENORMAL_GUARD = 1e-12


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

    def inlet(self, name, mult=1.0):
        return self.add(type="builtin", label="linear", name=name, control={"Mult": mult, "Add": DENORMAL_GUARD})

    def mixer(self, name, sources):
        self.add(type="builtin", label="mixer", name=name)
        for i, src in enumerate(sources, 1):
            self.link(src, f"{name}:In {i}")
        return f"{name}:Out"

    def convolver(self, name, path, channel, gain=1.0, source=None, **extra):
        self.add(type="builtin", label="convolver", name=name,
                 config={"filename": str(path), "channel": channel, "gain": gain, **extra})
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


# Past `tailsize` samples, the convolver works the rest of the IR in one batch every that many
# samples. With all 16 HRIR convolvers doing so in the same cycle the chain overran and
# crackled, so the tail starts beyond any HRIR's length and the work stays even.
HRIR_TAIL = 32768
# HRIRs often carry a long, faint room tail: in a typical HeSuVi file 99.99% of the energy is in the
# first 2048 samples and the rest is over 55 dB down. Cutting it there keeps 16 convolvers cheap
# enough to run without crackling, at 96 kHz too.
HRIR_LENGTH = 2048


def hrir_downmix(graph, layout, hrir, levels=None):
    """levels maps a channel to its gain in dB before the HRIR places it."""
    remap = HRIR_SOURCE.get(layout, {})
    left, right = [], []
    for ch in LAYOUTS[layout]:
        src = graph.inlet(f"in_{ch}", db((levels or {}).get(ch, 0)))
        ir_l, ir_r = HESUVI[remap.get(ch, ch)]
        left.append(graph.convolver(f"hrir_{ch}_l", hrir, ir_l, source=f"{src}:Out", tailsize=HRIR_TAIL,
                                    length=HRIR_LENGTH))
        right.append(graph.convolver(f"hrir_{ch}_r", hrir, ir_r, source=f"{src}:Out", tailsize=HRIR_TAIL,
                                     length=HRIR_LENGTH))
    inputs = [f"in_{ch}:In" for ch in LAYOUTS[layout]]
    return inputs, graph.mixer("hrir_mix_l", left), graph.mixer("hrir_mix_r", right)


def level_controls(layout, levels):
    """Control updates that apply surround levels to a running HRIR chain."""
    return {f"in_{ch}:Mult": db(levels.get(ch, 0)) for ch in LAYOUTS[layout]}


def effect_chain(preset, enabled):
    if preset is None or not enabled:
        return []
    chain = []
    for effect_id in preset.order:
        effect = plugins.effect(presets.kind_of(effect_id))
        if preset.enabled(effect_id) and effect.available():
            chain.append((effect_id, effect, preset.settings(effect_id)))
    return chain


def steps(preset, enabled, route):
    """The steps of a chain, as [(tap, title)]; each one plays into the next through a stream of its own."""
    taps = [("surround", "Surround Downmix")] if route == "hrir" else []
    for effect_id, effect, _settings in effect_chain(preset, enabled):
        index = int(effect_id.partition("#")[2] or 0)
        taps.append((node_name(effect_id), effect.title + (f" {index + 1}" if index else "")))
    return taps


def stream_names(taps, capture, playback):
    """Each step's (capture, playback) node names; the chain's own names are kept at its two ends."""
    last = len(taps) - 1
    return [(capture if i == 0 else f"{capture}.{tap}", playback if i == last else f"{playback}.{tap}")
            for i, tap in enumerate(taps)] or [(capture, playback)]


def joins(taps, capture, playback):
    """The (output node, input node) pairs the controller links, from each step into the next."""
    names = stream_names(taps, capture, playback)
    return [(names[i][1], names[i + 1][0]) for i in range(len(names) - 1)]


def control_node(taps, capture, playback, effect_id):
    """The node whose Props hold an effect's controls."""
    tap = node_name(effect_id)
    return stream_names(taps, capture, playback)[taps.index(tap)][0] if tap in taps else capture


def staged(entry, effects, separate):
    """Splits a chain into its steps: the entry, then one per effect.

    entry is (graph, inputs, left, right). The first effect joins the entry's graph unless the entry
    is a step of its own, as the HRIR downmix is. Returns [(graph, inputs, outputs)].
    """
    graph, inputs, left, right = entry
    effects = list(effects)
    if not separate and effects:
        effect_id, effect, settings = effects.pop(0)
        left, right = add_effect(graph, effect_id, effect, settings, left, right)
    stages = [(graph, inputs, [left, right])]
    for effect_id, effect, settings in effects:
        graph = Graph()
        inputs, left, right = plain_inputs(graph)
        stages.append((graph, inputs, list(add_effect(graph, effect_id, effect, settings, left, right))))
    return stages


def modules(description, stages, taps, capture, playback):
    """One filter-chain per stage; the streams between stages carry the playback's channels."""
    names = stream_names(taps, capture["node.name"], playback["node.name"])
    inner = {k: playback[k] for k in ("audio.channels", "audio.position", "audio.rate") if k in playback}
    out = []
    for i, ((graph, inputs, outputs), (cap, play)) in enumerate(zip(stages, names)):
        out.append(filter_chain(
            description, graph, inputs, outputs,
            capture if i == 0 else {"node.name": cap, "node.autoconnect": False, **inner},
            playback if i == len(stages) - 1 else {"node.name": play, "node.autoconnect": False, **inner}))
    return out


def plain_inputs(graph):
    return [f"{graph.inlet('in_l')}:In", f"{graph.inlet('in_r')}:In"], "in_l:Out", "in_r:Out"


def filter_chain(description, graph, inputs, outputs, capture, playback):
    # filter-graph plays silence from a node that is both an input and an output of the graph, as
    # a chain without effects would be, so such outputs go through a node of their own.
    inlets = {port.split(":")[0] for port in inputs if port}
    outputs = list(outputs)
    for i, port in enumerate(outputs):
        if port.split(":")[0] in inlets:
            name = graph.add(type="builtin", label="linear", name=f"out_{i}", control={"Mult": 1.0, "Add": 0.0})
            graph.link(port, f"{name}:In")
            outputs[i] = f"{name}:Out"
    # Both ends are passive, so nothing is held open while no app is playing or recording.
    return {
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


def config_text(*modules):
    conf = {
        "context.properties": {"log.level": 0},
        "context.spa-libs": {"audio.convert.*": "audioconvert/libspa-audioconvert",
                             "support.*": "support/libspa-support"},
        "context.modules": [
            {"name": "libpipewire-module-protocol-native"},
            {"name": "libpipewire-module-client-node"},
            {"name": "libpipewire-module-adapter"},
            *modules,
        ],
    }
    return json.dumps(conf, indent=2)


def channels(positions):
    return {"audio.channels": len(positions), "audio.position": list(positions)}


def build(preset, enabled, route, layout, hrir, target, levels=None):
    graph = Graph()
    if route == "hrir":
        inputs, left, right = hrir_downmix(graph, layout, hrir, levels)
    else:
        inputs, left, right = plain_inputs(graph)
    stages = staged((graph, inputs, left, right), effect_chain(preset, enabled), route == "hrir")
    capture = LAYOUTS[layout] if route in ("passthrough", "hrir") else LAYOUTS["stereo"]
    playback = LAYOUTS[layout] if route == "passthrough" else LAYOUTS["stereo"]
    return config_text(*modules(
        "Skitz Effects Output", stages, [tap for tap, _title in steps(preset, enabled, route)],
        {"node.name": CAPTURE, "target.object": SINK, "stream.capture.sink": True, **channels(capture)},
        {"node.name": PLAYBACK, "target.object": target, **channels(playback)},
    ))


# The mic chain runs at 48 kHz whatever rate the graph runs at, as DeepFilterNet supports no other;
# PipeWire resamples at the chain's ends.
INPUT_RATE = 48000


def build_input(preset, enabled, device, channel="", positions=()):
    """The mic chain; with a channel, only that one of the device's positions feeds both sides."""
    graph = Graph()
    stereo = {**channels(LAYOUTS["stereo"]), "audio.rate": INPUT_RATE}
    if channel in positions:
        source = graph.inlet("in_l")
        # A null input discards that channel of the capture.
        inputs = [f"{source}:In" if position == channel else None for position in positions]
        left = right = f"{source}:Out"
        capture = {**channels(positions), "audio.rate": INPUT_RATE}
    else:
        inputs, left, right = plain_inputs(graph)
        capture = stereo
    stages = staged((graph, inputs, left, right), effect_chain(preset, enabled), False)
    return config_text(*modules(
        "Skitz Effects Microphone", stages, [tap for tap, _title in steps(preset, enabled, "stereo")],
        {"node.name": MIC_CAPTURE, "target.object": device, **capture},
        # WirePlumber only links playback streams to sinks, so the controller links this one to the source.
        {"node.name": MIC_PLAYBACK, "node.autoconnect": False, **stereo},
    ))


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
