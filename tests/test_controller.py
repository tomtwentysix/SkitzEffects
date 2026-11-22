import json
import os

import pytest

from skitz_effects.controller import data_loop_threads, input_variants, rate_changed, routable

UMC22 = [
    (0, "off"),
    (1, "output:analog-stereo-output+input:analog-stereo-input"),
    (2, "output:analog-stereo-output+input:analog-mono-left"),
    (3, "output:analog-stereo-output+input:analog-mono-right"),
    (4, "output:analog-stereo-output+input:analog-mono"),
    (5, "output:analog-stereo-output"),
    (6, "input:analog-stereo-input"),
    (7, "input:analog-mono-left"),
    (8, "input:analog-mono-right"),
    (9, "input:analog-mono"),
    (10, "pro-audio"),
]


def test_rate_changed_only_between_two_known_rates():
    assert rate_changed(96000, 48000)
    assert not rate_changed(96000, 96000)
    # 0 is a suspended device, or a chain that has not seen its device run yet.
    assert not rate_changed(0, 48000)
    assert not rate_changed(96000, 0)


def test_data_loop_threads_of_a_process_without_any():
    assert data_loop_threads(os.getpid()) == []


def test_input_variants_keep_the_output_side():
    current = "output:analog-stereo-output+input:analog-mono"
    assert input_variants(UMC22, current) == [
        (1, "analog-stereo-input"), (2, "analog-mono-left"), (3, "analog-mono-right"), (4, "analog-mono")]
    assert [i for i, _p in input_variants(UMC22, "input:analog-mono")] == [6, 7, 8, 9]
    assert input_variants(UMC22, "pro-audio") == []


def test_routable_streams():
    assert routable({"node.name": "Firefox"})
    assert not routable({"node.name": "skitz_tap_output_after"})
    assert not routable({"node.name": "output.pw-loopback-1", "node.link-group": "loopback-1-20"})
    assert not routable({"node.name": "obs", "stream.capture.sink": "true"})
    assert not routable({"node.name": "peak", "stream.monitor": True})
    assert not routable({"node.name": "pw-play", "target.object": "alsa_output.x"})


def test_app_key_matches_easy_effects_blocklist_names():
    from skitz_effects.controller import app_key
    assert app_key({"application.id": "org.gnome.Rhythmbox3", "application.name": "Rhythmbox"}) == "org.gnome.Rhythmbox3"
    assert app_key({"application.name": "Firefox", "node.name": "Firefox"}) == "Firefox"
    assert app_key({"node.name": "mpv"}) == "mpv"


def test_streams_aimed_at_easy_effects_come_through_skitz_effects():
    loopback = {"node.name": "output.pw-loopback-1", "node.link-group": "loopback-1-20",
                "node.target": "easyeffects_sink"}
    assert routable(loopback)
    assert routable({"node.name": "obs-mic", "target.object": "easyeffects_source"})
    assert not routable({"node.name": "skitz_output", "target.object": "easyeffects_sink"})



def make_pipeline(monkeypatch, preset="Dali iO6", layout="stereo"):
    from types import SimpleNamespace
    from skitz_effects import presets
    from skitz_effects.controller import Pipeline
    monkeypatch.setattr(Pipeline, "emit", lambda self, *args: None)
    monkeypatch.setattr(Pipeline, "queue_rebuild", lambda self: self.rebuilds.append(1))
    pipeline = Pipeline.__new__(Pipeline)
    saves = []
    settings = SimpleNamespace(
        output={"preset": preset, "enabled": True, "device": ""}, layout=layout, surround_levels={},
        hrir="/nonexistent/atmos.wav", downmix="auto", save=lambda: saves.append(1))
    pipeline.controller = SimpleNamespace(settings=settings, pw=None, hrir_ok=lambda: True)
    pipeline.direction = "output"
    pipeline.preset = presets.load(preset)
    pipeline.trims = []
    pipeline.rebuilds = []
    pipeline._taps = []
    pipeline._save_id = 0
    pipeline._queue_save = lambda: setattr(pipeline, "_save_id", 0) or saves.append("queued")
    pipeline._proc = None
    pipeline._conf = ""
    pipeline._missing_since = 0.0
    pipeline.route = ""
    pipeline.control_node = "capture"
    pipeline.playback_node = "playback"
    pipeline.saves = saves
    return pipeline


def test_build_includes_the_trims(ee_root, lv2, monkeypatch):
    import json
    from types import SimpleNamespace
    from skitz_effects import graph
    from skitz_effects.check import Cut
    pipeline = make_pipeline(monkeypatch)
    device = SimpleNamespace(name="alsa_output.test", channels=2, positions=["FL", "FR"])
    pipeline.trims = [Cut("bass_loudness#0", "output-gain", -6.0)]
    _route, conf = pipeline._build(device)
    modules = [m for m in json.loads(conf)["context.modules"] if "filter-chain" in m["name"]]
    nodes = {n["name"]: n for m in modules for n in m["args"]["filter.graph"]["nodes"]}
    assert nodes["bass_loudness_0_out_l"]["control"]["Mult"] == pytest.approx(graph.db(-9.0))
    assert pipeline.preset.settings("bass_loudness#0")["output-gain"] == -3.0


def test_loading_a_preset_drops_the_trims(ee_root, monkeypatch):
    from skitz_effects.check import Cut
    pipeline = make_pipeline(monkeypatch)
    pipeline.trims = [Cut("bass_loudness#0", "output-gain", -6.0)]
    pipeline.load_preset("Dali iO6")
    assert pipeline.trims == []


def test_a_new_preset_drops_the_trims(ee_root, monkeypatch):
    from skitz_effects.check import Cut
    pipeline = make_pipeline(monkeypatch)
    pipeline.trims = [Cut("bass_loudness#0", "output-gain", -6.0)]
    pipeline.new_preset("Fresh")
    assert pipeline.trims == []


def test_fix_settings_writes_nothing(ee_root, lv2, monkeypatch):
    from skitz_effects.check import Cut
    pipeline = make_pipeline(monkeypatch)
    path = pipeline.preset.path
    before = path.read_bytes()
    cut = Cut("bass_loudness#0", "output-gain", -6.0)
    pipeline.fix([cut], False)
    pipeline._flush_save()
    assert pipeline.trims == [cut]
    assert path.read_bytes() == before
    assert pipeline.saves == []
    assert pipeline.rebuilds == []
    pipeline.fix([Cut("bass_loudness#0", "output-gain", -1.0)], True)
    pipeline._flush_save()
    assert pipeline.trims == []
    assert pipeline.preset.settings("bass_loudness#0")["output-gain"] == -10.0
    assert json.loads(path.read_text())["output"]["bass_loudness#0"]["output-gain"] == -10.0


def test_fix_saves_surround_cuts_into_the_levels(ee_root, monkeypatch):
    from skitz_effects.check import Cut
    pipeline = make_pipeline(monkeypatch, layout="5.1")
    levels = pipeline.controller.settings.surround_levels
    levels["FC"] = 3.0
    pipeline.fix([Cut("surround", "surround", -3.0)], True)
    assert "FC" not in levels
    assert levels["FL"] == -3.0
    assert pipeline.trims == []
    assert pipeline.saves.count(1) == 1


def test_stages_map_taps_back_to_effect_ids(ee_root, lv2, monkeypatch):
    pipeline = make_pipeline(monkeypatch)
    monkeypatch.setattr(type(pipeline), "steps", lambda self: [
        ("surround", "Surround Downmix", "a"), ("bass_loudness_0", "Bass Loudness", "b")])
    stages = pipeline.stages()
    assert [(s.key, s.kind, s.stream) for s in stages] == [
        ("surround", "surround", "a"), ("bass_loudness#0", "bass_loudness", "b")]
