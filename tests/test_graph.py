import json

import pytest

from skitz_effects import graph, plugins, presets
from skitz_effects.config import LAYOUTS

from .conftest import chain_args

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
    args = chain_args(graph.build(presets.load("Dali iO6"), True, "passthrough", "7.1", HRIR, TARGET))
    g = args["filter.graph"]
    # Two inputs for an 8-channel stream: filter-chain copies the graph per channel pair.
    assert len(g["inputs"]) == len(g["outputs"]) == 2
    assert args["capture.props"]["audio.position"] == list(LAYOUTS["7.1"])
    assert args["playback.props"]["audio.position"] == list(LAYOUTS["7.1"])
    assert args["capture.props"]["target.object"] == graph.SINK
    assert args["playback.props"]["target.object"] == TARGET
    plugins_used = [n["plugin"] for n in g["nodes"] if n["type"] == "lv2"]
    # The convolver is bypassed in this preset, so it is left out.
    assert plugins_used == [plugins.EFFECTS[k].uri for k in ("equalizer", "bass_loudness", "limiter")]
    assert g["outputs"] == ["limiter_0:out_l", "limiter_0:out_r"]
    assert_wired(args)


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
    assert node_names(off) == {"in_l", "in_r"}
    assert off["filter.graph"]["outputs"] == ["in_l:Out", "in_r:Out"]
    # Easy Effects 6 preset: Calf and bs2b effects have no plugin, and the IR is not installed.
    old = chain_args(graph.build(presets.load("Bass Boosted"), True, "passthrough", "stereo", HRIR, TARGET))
    assert {n.get("plugin") for n in old["filter.graph"]["nodes"]} == {
        None, plugins.EFFECTS["equalizer"].uri, plugins.EFFECTS["maximizer"].uri}
    assert_wired(old)


def test_convolver_uses_an_installed_ir(ee_root, lv2):
    from .conftest import write_wav
    write_wav(ee_root / "irs" / "Razor Surround ((48k Z-Edition)) 2.Stereo +20 bass.irs", 2)
    args = chain_args(graph.build(presets.load("Bass Boosted"), True, "passthrough", "stereo", HRIR, TARGET))
    nodes = {n["name"]: n for n in args["filter.graph"]["nodes"]}
    assert (nodes["convolver_l"]["config"]["channel"], nodes["convolver_r"]["config"]["channel"]) == (0, 1)
    assert nodes["convolver_l"]["config"]["gain"] == pytest.approx(graph.db(-2.0))
    assert_wired(args)


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
    args = chain_args(graph.build(preset, True, "passthrough", "stereo", HRIR, TARGET))
    nodes = {n["name"]: n for n in args["filter.graph"]["nodes"]}
    assert nodes["bass_loudness_0_out_l"]["control"]["Mult"] == pytest.approx(graph.db(settings["output-gain"]))
    live = graph.live_controls("bass_loudness#0", effect, settings)
    assert live["bass_loudness_0_out_r:Mult"] == pytest.approx(graph.db(-3.0))
    assert live["bass_loudness_0_in_l:Mult"] == pytest.approx(1.0)
    assert live["bass_loudness_0:link"] == pytest.approx(graph.db(-9.1))
    assert all(key.split(":")[1] for key in live)


def test_live_controls_match_the_built_graph(ee_root, lv2):
    preset = presets.load("Dali iO6")
    args = chain_args(graph.build(preset, True, "passthrough", "stereo", HRIR, TARGET))
    nodes = {n["name"]: n for n in args["filter.graph"]["nodes"]}
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
    assert g["outputs"] == ["in_l:Out", "in_l:Out"]
    assert args["capture.props"]["audio.position"] == ["FL", "FR"]
    # A channel the device does not have falls back to recording every channel.
    fallback = chain_args(graph.build_input(None, True, "alsa_input.mic", "AUX3", ("MONO",)))
    assert fallback["filter.graph"]["inputs"] == ["in_l:In", "in_r:In"]
    assert fallback["capture.props"]["audio.position"] == list(LAYOUTS["stereo"])


def test_mono_profile_records_only_its_mono_channel(ee_root, lv2):
    args = chain_args(graph.build_input(None, True, "alsa_input.umc22.analog-mono-left", "MONO", ("MONO", "AUX1")))
    assert args["filter.graph"]["inputs"] == ["in_l:In", None]
    assert args["filter.graph"]["outputs"] == ["in_l:Out", "in_l:Out"]
    assert args["capture.props"]["audio.position"] == ["MONO", "AUX1"]
