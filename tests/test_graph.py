import json

import pytest

from skitz_effects import graph, plugins, presets
from skitz_effects.config import LAYOUTS

from .conftest import chain_args, chain_modules, chain_nodes

HRIR = "/nonexistent/atmos.wav"
TARGET = "alsa_output.test"


@pytest.mark.parametrize("layout, device, downmix, hrir_ok, route", [
    (2, 2, "auto", True, "passthrough"),
    (2, 8, "always", True, "passthrough"),
    (8, 8, "auto", True, "passthrough"),
    (6, 8, "auto", True, "passthrough"),
    (8, 2, "auto", True, "hrir"),
    (8, 2, "auto", False, "stereo"),
    (8, 2, "never", True, "stereo"),
    (6, 2, "auto", True, "hrir"),
    (8, 8, "always", True, "hrir"),
    (8, 8, "always", False, "stereo"),
    (8, 6, "auto", True, "hrir"),
])
def test_choose_route(layout, device, downmix, hrir_ok, route):
    assert graph.choose_route(layout, device, downmix, hrir_ok) == route


def node_names(args):
    return {n["name"] for n in args["filter.graph"]["nodes"]}


def assert_wired(args):
    """Every link and graph port refers to a node that exists."""
    names = node_names(args)
    g = args["filter.graph"]
    ports = [link["output"] for link in g["links"]] + [link["input"] for link in g["links"]]
    for port in ports + g["inputs"] + g["outputs"]:
        assert port.split(":")[0] in names, port


def test_build_passthrough_runs_the_preset_on_every_channel(ee_root, lv2):
    text = graph.build(presets.load("Dali iO6"), True, "passthrough", "7.1", HRIR, TARGET)
    first, last = chain_args(text), chain_args(text, -1)
    for args in chain_modules(text):
        g = args["filter.graph"]
        # Two inputs for an 8-channel stream: filter-chain copies the graph per channel pair.
        assert len(g["inputs"]) == len(g["outputs"]) == 2
        assert args["capture.props"]["audio.position"] == list(LAYOUTS["7.1"])
        assert args["playback.props"]["audio.position"] == list(LAYOUTS["7.1"])
        assert_wired(args)
    assert first["capture.props"]["target.object"] == graph.SINK
    assert last["playback.props"]["target.object"] == TARGET
    plugins_used = [n["plugin"] for n in chain_nodes(text).values() if n["type"] == "lv2"]
    # The convolver is bypassed in this preset, so it is left out.
    assert plugins_used == [plugins.EFFECTS[k].uri for k in ("equalizer", "bass_loudness", "limiter")]
    assert last["filter.graph"]["outputs"] == ["limiter_0:out_l", "limiter_0:out_r"]


def test_build_keeps_devices_free_when_idle(ee_root, lv2):
    args = chain_args(graph.build(presets.load("Dali iO6"), True, "passthrough", "stereo", HRIR, TARGET))
    assert args["capture.props"]["node.passive"] is True
    assert args["playback.props"]["node.passive"] is True


def test_build_hrir_downmixes_every_channel(ee_root, lv2):
    args = chain_args(graph.build(None, True, "hrir", "7.1", HRIR, TARGET))
    nodes = {n["name"]: n for n in args["filter.graph"]["nodes"]}
    convolvers = [n for n in nodes.values() if n.get("label") == "convolver"]
    assert len(convolvers) == 2 * 8
    assert {n["config"]["filename"] for n in convolvers} == {HRIR}
    assert (nodes["hrir_FL_l"]["config"]["channel"], nodes["hrir_FL_r"]["config"]["channel"]) == graph.HESUVI["FL"]
    assert nodes["hrir_LFE_l"]["config"]["channel"] == graph.HESUVI["FC"][0]
    assert args["filter.graph"]["inputs"] == [f"in_{ch}:In" for ch in LAYOUTS["7.1"]]
    assert args["capture.props"]["audio.position"] == list(LAYOUTS["7.1"])
    assert args["playback.props"]["audio.position"] == list(LAYOUTS["stereo"])
    assert_wired(args)


def test_hrir_places_51_surrounds_beside_the_listener():
    g = graph.Graph()
    graph.hrir_downmix(g, "5.1", HRIR)
    channels = {n["name"]: n["config"]["channel"] for n in g.nodes if n.get("label") == "convolver"}
    assert (channels["hrir_RL_l"], channels["hrir_RL_r"]) == graph.HESUVI["SL"]
    assert (channels["hrir_RR_l"], channels["hrir_RR_r"]) == graph.HESUVI["SR"]


def test_build_stereo_route_lets_pipewire_downmix(ee_root, lv2):
    args = chain_args(graph.build(None, True, "stereo", "7.1", HRIR, TARGET))
    assert args["capture.props"]["audio.position"] == list(LAYOUTS["stereo"])
    assert args["playback.props"]["audio.position"] == list(LAYOUTS["stereo"])


def test_effects_off_or_missing_leave_a_plain_copy(ee_root, lv2):
    off = chain_args(graph.build(presets.load("Dali iO6"), False, "passthrough", "stereo", HRIR, TARGET))
    assert node_names(off) == {"in_l", "in_r", "out_0", "out_1"}
    assert off["filter.graph"]["outputs"] == ["out_0:Out", "out_1:Out"]
    # Easy Effects 6 preset: Calf and bs2b effects have no plugin, and the IR is not installed.
    old = graph.build(presets.load("Bass Boosted"), True, "passthrough", "stereo", HRIR, TARGET)
    assert {n.get("plugin") for n in chain_nodes(old).values()} == {
        None, plugins.EFFECTS["equalizer"].uri, plugins.EFFECTS["maximizer"].uri}
    for args in chain_modules(old):
        assert_wired(args)


def test_convolver_uses_an_installed_ir(ee_root, lv2):
    from .conftest import write_wav
    write_wav(ee_root / "irs" / "Razor Surround ((48k Z-Edition)) 2.Stereo +20 bass.irs", 2)
    nodes = chain_nodes(graph.build(presets.load("Bass Boosted"), True, "passthrough", "stereo", HRIR, TARGET))
    assert (nodes["convolver_l"]["config"]["channel"], nodes["convolver_r"]["config"]["channel"]) == (0, 1)
    assert nodes["convolver_l"]["config"]["gain"] == pytest.approx(graph.db(-2.0))


def test_build_input_links_into_the_source_itself(ee_root, lv2):
    args = chain_args(graph.build_input(None, True, "alsa_input.mic"))
    assert args["capture.props"]["target.object"] == "alsa_input.mic"
    assert args["capture.props"]["node.name"] == graph.MIC_CAPTURE
    # WirePlumber cannot link a playback stream to a source, so the controller does it.
    assert "target.object" not in args["playback.props"]
    assert args["playback.props"]["node.autoconnect"] is False
    assert args["capture.props"]["node.passive"] is True


def test_config_is_multiline_json():
    # PipeWire's config parser rejects the whole module list when it is on one line.
    text = graph.build(None, True, "passthrough", "stereo", HRIR, TARGET)
    assert text.count("\n") > 10
    json.loads(text)


def test_bass_loudness_gains_are_live_controls(ee_root, lv2):
    preset = presets.load("Dali iO6")
    settings = preset.settings("bass_loudness#0")
    effect = plugins.effect("bass_loudness")
    nodes = chain_nodes(graph.build(preset, True, "passthrough", "stereo", HRIR, TARGET))
    assert nodes["bass_loudness_0_out_l"]["control"]["Mult"] == pytest.approx(graph.db(settings["output-gain"]))
    live = graph.live_controls("bass_loudness#0", effect, settings)
    assert live["bass_loudness_0_out_r:Mult"] == pytest.approx(graph.db(-3.0))
    assert live["bass_loudness_0_in_l:Mult"] == pytest.approx(1.0)
    assert live["bass_loudness_0:link"] == pytest.approx(graph.db(-9.1))
    assert all(key.split(":")[1] for key in live)


def test_live_controls_match_the_built_graph(ee_root, lv2):
    preset = presets.load("Dali iO6")
    nodes = chain_nodes(graph.build(preset, True, "passthrough", "stereo", HRIR, TARGET))
    live = graph.live_controls("limiter#0", plugins.effect("limiter"), preset.settings("limiter#0"))
    for key, value in live.items():
        name, port = key.split(":")
        assert nodes[name]["control"][port] == value
    assert graph.live_controls("convolver#0", plugins.effect("convolver"), {}) is None


def test_noise_remover_runs_as_ladspa(ee_root, lv2):
    preset = presets.create("Mic", "input")
    effect_id = preset.add("deepfilternet")
    preset.settings(effect_id)["attenuation-limit"] = 40.0
    args = chain_args(graph.build_input(preset, True, "alsa_input.mic"))
    nodes = {n["name"]: n for n in args["filter.graph"]["nodes"]}
    node = nodes["deepfilternet_0"]
    assert (node["type"], node["plugin"], node["label"]) == ("ladspa", "libdeep_filter_ladspa", "deep_filter_stereo")
    assert node["control"]["Attenuation Limit (dB)"] == 40.0
    assert {"deepfilternet_0_in_l", "deepfilternet_0_out_r"} <= set(nodes)
    assert {"output": "deepfilternet_0_in_l:Out", "input": "deepfilternet_0:Audio In L"} in args["filter.graph"]["links"]
    assert args["filter.graph"]["outputs"] == ["deepfilternet_0_out_l:Out", "deepfilternet_0_out_r:Out"]
    assert_wired(args)


def test_input_channel_feeds_both_sides(ee_root, lv2):
    args = chain_args(graph.build_input(None, True, "alsa_input.mic", "FR", ("FL", "FR")))
    g = args["filter.graph"]
    assert g["inputs"] == [None, "in_l:In"]
    assert g["outputs"] == ["out_0:Out", "out_1:Out"]
    assert args["capture.props"]["audio.position"] == ["FL", "FR"]
    # A channel the device does not have falls back to recording every channel.
    fallback = chain_args(graph.build_input(None, True, "alsa_input.mic", "AUX3", ("MONO",)))
    assert fallback["filter.graph"]["inputs"] == ["in_l:In", "in_r:In"]
    assert fallback["capture.props"]["audio.position"] == list(LAYOUTS["stereo"])


def test_mono_profile_records_only_its_mono_channel(ee_root, lv2):
    args = chain_args(graph.build_input(None, True, "alsa_input.umc22.analog-mono-left", "MONO", ("MONO", "AUX1")))
    assert args["filter.graph"]["inputs"] == ["in_l:In", None]
    assert args["filter.graph"]["outputs"] == ["out_0:Out", "out_1:Out"]
    assert args["capture.props"]["audio.position"] == ["MONO", "AUX1"]


@pytest.mark.parametrize("text", [
    graph.build(None, True, "hrir", "7.1", HRIR, TARGET),
    graph.build(None, True, "passthrough", "stereo", HRIR, TARGET),
    graph.build_input(None, True, "alsa_input.test"),
    graph.build_input(None, True, "alsa_input.test", "AUX1", ("MONO", "AUX1")),
])
def test_every_input_is_guarded_against_denormals(text):
    modules = [m for m in json.loads(text)["context.modules"] if "filter-chain" in m["name"]]
    for module in modules:
        g = module["args"]["filter.graph"]
        nodes = {n["name"]: n for n in g["nodes"]}
        for port in filter(None, g["inputs"]):
            node = nodes[port.split(":")[0]]
            assert node["label"] == "linear"
            assert node["control"] == {"Mult": 1.0, "Add": graph.DENORMAL_GUARD}


def test_chains_never_ask_for_realtime():
    text = graph.build(None, True, "passthrough", "stereo", HRIR, TARGET)
    assert "libpipewire-module-rt" not in [m["name"] for m in json.loads(text)["context.modules"]]


def test_every_route_runs_one_chain():
    def chains(text):
        return len([m for m in json.loads(text)["context.modules"] if "filter-chain" in m["name"]])
    assert chains(graph.build(None, True, "hrir", "7.1", HRIR, TARGET)) == 1
    assert chains(graph.build(None, True, "passthrough", "7.1", HRIR, TARGET)) == 1


def test_steps_follow_the_preset(ee_root, lv2):
    preset = presets.load("Dali iO6")
    assert graph.steps(preset, True, "passthrough") == [
        ("equalizer_0", "Equalizer"), ("bass_loudness_0", "Bass Loudness"), ("limiter_0", "Limiter")]
    assert graph.steps(preset, True, "hrir")[0] == ("surround", "Surround Downmix")
    assert graph.steps(preset, False, "passthrough") == []
    assert graph.steps(None, True, "hrir") == [("surround", "Surround Downmix")]


def test_second_copies_of_an_effect_are_numbered(ee_root, lv2):
    preset = presets.create("Twice")
    preset.add("equalizer")
    preset.add("equalizer")
    assert [title for _tap, title in graph.steps(preset, True, "stereo")] == ["Equalizer", "Equalizer 2"]


def test_each_step_plays_into_the_next(ee_root, lv2):
    preset = presets.load("Dali iO6")
    text = graph.build(preset, True, "hrir", "7.1", HRIR, TARGET)
    modules = chain_modules(text)
    taps = [tap for tap, _title in graph.steps(preset, True, "hrir")]
    assert len(modules) == len(taps) == 4
    names = [(m["capture.props"]["node.name"], m["playback.props"]["node.name"]) for m in modules]
    assert names == graph.stream_names(taps, graph.CAPTURE, graph.PLAYBACK)
    assert names[0] == (graph.CAPTURE, f"{graph.PLAYBACK}.surround")
    assert names[-1] == (f"{graph.CAPTURE}.limiter_0", graph.PLAYBACK)
    assert graph.joins(taps, graph.CAPTURE, graph.PLAYBACK) == [
        (f"{graph.PLAYBACK}.surround", f"{graph.CAPTURE}.equalizer_0"),
        (f"{graph.PLAYBACK}.equalizer_0", f"{graph.CAPTURE}.bass_loudness_0"),
        (f"{graph.PLAYBACK}.bass_loudness_0", f"{graph.CAPTURE}.limiter_0")]
    # The 16 HRIR convolvers stay in the first step, which ends in the stereo downmix.
    assert sum(n.get("label") == "convolver" for n in modules[0]["filter.graph"]["nodes"]) == 16
    assert modules[0]["filter.graph"]["outputs"] == ["hrir_mix_l:Out", "hrir_mix_r:Out"]
    for args in modules[1:]:
        # Streams inside the chain are linked by the controller, and stay passive like the ends.
        assert args["capture.props"]["node.autoconnect"] is False
        assert args["capture.props"]["node.passive"] is True
        assert args["capture.props"]["audio.position"] == list(LAYOUTS["stereo"])
    for args in modules[:-1]:
        assert args["playback.props"]["node.autoconnect"] is False
        assert "target.object" not in args["playback.props"]
        assert args["playback.props"]["audio.position"] == list(LAYOUTS["stereo"])
    for args in modules:
        assert_wired(args)


def test_the_first_effect_shares_the_entry_step(ee_root, lv2):
    text = graph.build(presets.load("Dali iO6"), True, "passthrough", "stereo", HRIR, TARGET)
    first = chain_args(text)
    assert node_names(first) == {"in_l", "in_r", "equalizer_0"}
    assert first["playback.props"]["node.name"] == f"{graph.PLAYBACK}.equalizer_0"


def test_one_step_chains_keep_their_names(ee_root, lv2):
    assert graph.stream_names([], graph.CAPTURE, graph.PLAYBACK) == [(graph.CAPTURE, graph.PLAYBACK)]
    assert graph.joins([], graph.CAPTURE, graph.PLAYBACK) == []
    args = chain_args(graph.build_input(None, True, "alsa_input.mic"))
    assert (args["capture.props"]["node.name"], args["playback.props"]["node.name"]) == (
        graph.MIC_CAPTURE, graph.MIC_PLAYBACK)


def test_controls_go_to_the_step_that_holds_the_effect(ee_root, lv2):
    taps = ["surround", "equalizer_0", "limiter_0"]
    assert graph.control_node(taps, graph.CAPTURE, graph.PLAYBACK, "limiter#0") == f"{graph.CAPTURE}.limiter_0"
    assert graph.control_node(["equalizer_0", "limiter_0"], graph.CAPTURE, graph.PLAYBACK,
                              "equalizer#0") == graph.CAPTURE
    # An effect the running chain does not have yet goes to the first step, as before.
    assert graph.control_node(taps, graph.CAPTURE, graph.PLAYBACK, "gate#0") == graph.CAPTURE


def test_mic_steps_follow_its_preset(ee_root, lv2):
    preset = presets.create("Mic", "input")
    preset.add("deepfilternet")
    preset.add("limiter")
    modules = chain_modules(graph.build_input(preset, True, "alsa_input.mic", "FR", ("FL", "FR")))
    assert len(modules) == 2
    assert modules[0]["filter.graph"]["inputs"] == [None, "in_l:In"]
    assert modules[1]["filter.graph"]["inputs"] == ["in_l:In", "in_r:In"]
    assert modules[-1]["playback.props"]["node.name"] == graph.MIC_PLAYBACK


def test_the_mic_chain_runs_at_48_khz(ee_root, lv2):
    preset = presets.create("Mic", "input")
    preset.add("deepfilternet")
    preset.add("limiter")
    for text in (graph.build_input(preset, True, "alsa_input.mic"),
                 graph.build_input(preset, True, "alsa_input.mic", "FR", ("FL", "FR"))):
        for module in chain_modules(text):
            assert module["capture.props"]["audio.rate"] == graph.INPUT_RATE == 48000
            assert module["playback.props"]["audio.rate"] == graph.INPUT_RATE
    output = chain_modules(graph.build(preset, True, "passthrough", "stereo", HRIR, TARGET))
    assert all("audio.rate" not in m["capture.props"] for m in output)


def test_no_chain_outputs_straight_from_an_input(ee_root, lv2):
    for text in (graph.build_input(None, True, "alsa_input.mic"),
                 graph.build_input(None, True, "alsa_input.mic", "MONO", ("MONO", "AUX1")),
                 graph.build(None, True, "passthrough", "stereo", HRIR, TARGET)):
        for module in chain_modules(text):
            g = module["filter.graph"]
            inlets = {port.split(":")[0] for port in g["inputs"] if port}
            assert not inlets & {port.split(":")[0] for port in g["outputs"]}
            assert {port.split(":")[0] for port in g["outputs"]} <= node_names(module)
