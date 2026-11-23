import json
import os
from types import SimpleNamespace

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
    monkeypatch.setattr(Pipeline, "emit", lambda self, name, *args: self.emitted.append(name))
    monkeypatch.setattr(Pipeline, "queue_rebuild", lambda self: self.rebuilds.append(1))
    pipeline = Pipeline.__new__(Pipeline)
    saves = []
    settings = SimpleNamespace(
        output={"preset": preset, "enabled": True, "device": "", "device_surround_levels": {},
                "device_presets": {}, "device_names": {}},
        layout=layout,
        hrir="/nonexistent/atmos.wav", downmix="auto", save=lambda: saves.append(1))
    pipeline.controller = SimpleNamespace(settings=settings, pw=None, hrir_ok=lambda: True)
    pipeline.direction = "output"
    pipeline.preset = presets.load(preset)
    pipeline.saved = pipeline._snapshot()
    pipeline.emitted = []
    pipeline.trims = []
    pipeline.levels = {}
    pipeline.levels_owner = ""
    pipeline.rebuilds = []
    pipeline._taps = []
    pipeline._proc = None
    pipeline._conf = ""
    pipeline._missing_since = 0.0
    pipeline.route = ""
    pipeline.virtual = "skitz_sink"
    pipeline.control_node = "capture"
    pipeline.playback_node = "playback"
    pipeline.saves = saves
    return pipeline


def test_build_includes_the_trims(ee_root, lv2, monkeypatch):
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
    assert pipeline.trims == [cut]
    assert path.read_bytes() == before
    assert pipeline.saves == []
    assert pipeline.rebuilds == []
    pipeline.fix([Cut("bass_loudness#0", "output-gain", -1.0)], True)
    assert not pipeline.unsaved
    assert pipeline.trims == []
    assert pipeline.preset.settings("bass_loudness#0")["output-gain"] == -10.0
    assert json.loads(path.read_text())["output"]["bass_loudness#0"]["output-gain"] == -10.0


def test_fix_saves_surround_cuts_into_the_levels(ee_root, monkeypatch):
    from skitz_effects.check import Cut
    pipeline = make_pipeline(monkeypatch, layout="5.1")
    pipeline.levels_owner = "a"
    pipeline.levels = {"FC": 3.0, "RL": 2.1}
    pipeline.fix([Cut("surround", "surround", -3.0)], True)
    levels = pipeline.controller.settings.output["device_surround_levels"]["a"]
    assert pipeline.levels == levels
    assert not pipeline.levels_unsaved
    assert "FC" not in levels
    assert levels["FL"] == -3.0
    assert levels["RL"] == -0.9
    assert pipeline.trims == []
    assert pipeline.saves.count(1) == 1


def test_stages_map_taps_back_to_effect_ids(ee_root, lv2, monkeypatch):
    pipeline = make_pipeline(monkeypatch)
    monkeypatch.setattr(type(pipeline), "steps", lambda self: [
        ("surround", "Surround Downmix", "a"), ("bass_loudness_0", "Bass Loudness", "b")])
    stages = pipeline.stages()
    assert [(s.key, s.kind, s.stream) for s in stages] == [
        ("surround", "surround", "a"), ("bass_loudness#0", "bass_loudness", "b")]


def test_fix_saving_tells_the_views_to_reload(ee_root, lv2, monkeypatch):
    from skitz_effects.check import Cut
    pipeline = make_pipeline(monkeypatch)
    pipeline.fix([Cut("bass_loudness#0", "output-gain", -1.0)], False)
    assert pipeline.emitted == []
    pipeline.fix([Cut("bass_loudness#0", "output-gain", -1.0)], True)
    assert "preset-changed" in pipeline.emitted


def test_fix_ignores_cuts_for_effects_the_preset_lacks(ee_root, lv2, monkeypatch):
    from skitz_effects.check import Cut
    pipeline = make_pipeline(monkeypatch)
    path = pipeline.preset.path
    before = path.read_text()
    pipeline.fix([Cut("bass_loudness#9", "output-gain", -1.0)], False)
    assert pipeline.trims == []
    pipeline.fix([Cut("bass_loudness#9", "output-gain", -1.0)], True)
    assert "bass_loudness#9" not in pipeline.preset.section
    assert path.read_text() == before


def test_a_structural_change_drops_trims_of_removed_effects(ee_root, lv2, monkeypatch):
    from skitz_effects.check import Cut
    pipeline = make_pipeline(monkeypatch)
    keep, gone = Cut("bass_loudness#0", "output-gain", -1.0), Cut("bass_loudness#7", "output-gain", -1.0)
    surround = Cut("surround", "surround", -1.0)
    pipeline.trims = [keep, gone, surround]
    pipeline.changed("bass_loudness#0")
    assert pipeline.trims == [keep, gone, surround]
    pipeline.changed("bass_loudness#7", structural=True)
    assert pipeline.trims == [keep, surround]


def test_the_input_build_includes_the_trims(ee_root, lv2, monkeypatch):
    from types import SimpleNamespace
    from skitz_effects import graph
    from skitz_effects.check import Cut
    seen = []
    monkeypatch.setattr(graph, "build_input", lambda preset, *args: seen.append(preset) or "{}")
    pipeline = make_pipeline(monkeypatch)
    pipeline.direction = "input"
    pipeline.controller.settings.input = {"enabled": True, "device_channels": {}}
    pipeline.trims = [Cut("bass_loudness#0", "output-gain", -6.0)]
    device = SimpleNamespace(name="alsa_input.test", positions=["FL", "FR"])
    pipeline._build(device)
    assert seen[0].settings("bass_loudness#0")["output-gain"] == -9.0
    assert pipeline.preset.settings("bass_loudness#0")["output-gain"] == -3.0


def edit_gain(pipeline, value):
    pipeline.preset.settings("bass_loudness#0")["output-gain"] = value
    pipeline.changed("bass_loudness#0")


def test_edits_are_live_but_unsaved(ee_root, lv2, monkeypatch):
    pipeline = make_pipeline(monkeypatch)
    path = pipeline.preset.path
    before = path.read_bytes()
    assert not pipeline.unsaved
    edit_gain(pipeline, -7.0)
    assert pipeline.unsaved
    assert "unsaved-changed" in pipeline.emitted
    assert path.read_bytes() == before
    pipeline.emitted.clear()
    pipeline.save_preset()
    assert json.loads(path.read_text())["output"]["bass_loudness#0"]["output-gain"] == -7.0
    assert not pipeline.unsaved
    assert pipeline.emitted == ["unsaved-changed"]


def test_editing_back_clears_unsaved(ee_root, lv2, monkeypatch):
    pipeline = make_pipeline(monkeypatch)
    edit_gain(pipeline, -7.0)
    edit_gain(pipeline, -3.0)
    assert not pipeline.unsaved


def test_discard_restores_the_saved_preset(ee_root, lv2, monkeypatch):
    pipeline = make_pipeline(monkeypatch)
    order = list(pipeline.preset.order)
    pipeline.preset.remove("limiter#0")
    pipeline.preset.settings("bass_loudness#0")["output-gain"] = -7.0
    pipeline.changed("limiter#0", structural=True)
    assert pipeline.unsaved
    pipeline.emitted.clear()
    pipeline.discard_preset()
    assert pipeline.preset.order == order
    assert pipeline.preset.settings("bass_loudness#0")["output-gain"] == -3.0
    assert not pipeline.unsaved
    assert "preset-changed" in pipeline.emitted
    assert "unsaved-changed" in pipeline.emitted


def test_loading_and_quitting_write_nothing(ee_root, lv2, monkeypatch):
    from skitz_effects.controller import Pipeline
    pipeline = make_pipeline(monkeypatch)
    path = pipeline.preset.path
    before = path.read_bytes()
    edit_gain(pipeline, -7.0)
    monkeypatch.setattr(Pipeline, "_stop_chain", lambda self: None)
    monkeypatch.setattr(Pipeline, "_route_streams", lambda self: None)
    pipeline.virtual = "skitz_sink"
    pipeline.controller.pw = SimpleNamespace(set_default=lambda name: None, destroy=lambda name: None)
    pipeline.shutdown()
    assert path.read_bytes() == before
    pipeline.load_preset("Laptop")
    assert path.read_bytes() == before
    assert not pipeline.unsaved


def test_the_mixer_switch_saves_only_the_blocklist(ee_root, lv2, monkeypatch):
    pipeline = make_pipeline(monkeypatch)
    monkeypatch.setattr(type(pipeline), "_route_streams", lambda self: None)
    path = pipeline.preset.path
    saved = json.loads(path.read_text())
    edit_gain(pipeline, -7.0)
    pipeline.set_blocked({"application.id": "org.example.App"}, True)
    on_disk = json.loads(path.read_text())
    assert on_disk["output"]["blocklist"] == ["org.example.App"]
    on_disk["output"]["blocklist"] = saved["output"]["blocklist"]
    assert on_disk == saved
    assert pipeline.unsaved
    pipeline.discard_preset()
    assert pipeline.preset.section["blocklist"] == ["org.example.App"]
    assert not pipeline.unsaved


def test_a_preset_missing_defaults_is_not_unsaved(ee_root, lv2, monkeypatch):
    path = ee_root / "output" / "Dali iO6.json"
    data = json.loads(path.read_text())
    del data["output"]["bass_loudness#0"]["output-gain"]
    path.write_text(json.dumps(data))
    pipeline = make_pipeline(monkeypatch)
    for effect_id in pipeline.preset.order:
        pipeline.preset.enabled(effect_id)
        pipeline.preset.settings(effect_id)
    assert not pipeline.unsaved


def test_the_mixer_switch_survives_a_missing_file(ee_root, lv2, monkeypatch):
    pipeline = make_pipeline(monkeypatch)
    monkeypatch.setattr(type(pipeline), "_route_streams", lambda self: None)
    edit_gain(pipeline, -7.0)
    pipeline.preset.path.unlink()
    pipeline.set_blocked({"application.id": "org.example.App"}, True)
    on_disk = json.loads(pipeline.preset.path.read_text())
    assert on_disk["output"]["blocklist"] == ["org.example.App"]
    assert on_disk["output"]["bass_loudness#0"]["output-gain"] == -3.0
    assert pipeline.unsaved


def test_levels_are_live_until_saved(monkeypatch):
    pipeline = make_pipeline(monkeypatch, layout="5.1")
    pipeline.levels_owner = "a"
    pipeline.set_surround_level("FC", -3.0)
    assert pipeline.levels_unsaved
    assert pipeline.saves == []
    assert "unsaved-changed" in pipeline.emitted
    saved = pipeline.controller.settings.output["device_surround_levels"]
    assert saved == {}
    pipeline.save_levels()
    assert saved["a"]["FC"] == -3.0
    assert not pipeline.levels_unsaved
    assert pipeline.saves == [1]


def test_editing_a_level_back_clears_the_mark(monkeypatch):
    pipeline = make_pipeline(monkeypatch, layout="5.1")
    pipeline.set_surround_level("FC", -3.0)
    pipeline.set_surround_level("FC", 0.0)
    assert not pipeline.levels_unsaved


def test_discarding_levels_restores_the_saved_ones(monkeypatch):
    pipeline = make_pipeline(monkeypatch, layout="5.1")
    pipeline.controller.settings.output["device_surround_levels"]["a"] = {"FC": 2.0}
    pipeline.levels_owner = "a"
    pipeline.levels = {"FC": 2.0}
    pipeline.set_surround_level("FC", -3.0)
    pipeline.set_surround_level("RL", 1.0)
    pipeline.discard_levels()
    assert pipeline.levels == {"FC": 2.0}
    assert not pipeline.levels_unsaved


def test_input_has_no_levels(monkeypatch):
    pipeline = make_pipeline(monkeypatch)
    pipeline.direction = "input"
    pipeline.levels = {"FC": 1.0}
    assert not pipeline.levels_unsaved
    pipeline.save_levels()
    pipeline.discard_levels()
    assert pipeline.saves == []
    assert pipeline.emitted == []


def test_unedited_levels_follow_the_device(monkeypatch):
    pipeline = make_pipeline(monkeypatch, layout="5.1")
    saved = pipeline.controller.settings.output["device_surround_levels"]
    saved.update({"a": {"FC": 1.0}, "b": {"FC": -2.0}})
    pipeline.controller.settings.output["device"] = "a"
    pipeline.levels_owner = "a"
    pipeline.levels = {"FC": 1.0}
    pipeline.select_device("b")
    assert pipeline.levels_owner == "b"
    assert pipeline.levels == {"FC": -2.0}
    assert pipeline.rebuilds


def test_edited_levels_stay_with_their_owner(monkeypatch):
    pipeline = make_pipeline(monkeypatch, layout="5.1")
    saved = pipeline.controller.settings.output["device_surround_levels"]
    saved.update({"a": {"FC": 1.0}, "b": {"FC": -2.0}})
    pipeline.controller.settings.output["device"] = "a"
    pipeline.levels_owner = "a"
    pipeline.levels = {"FC": 1.0}
    pipeline.set_surround_level("FC", 4.0)
    pipeline.select_device("b")
    assert pipeline.levels_owner == "a"
    assert pipeline.levels == {"FC": 4.0}
    assert pipeline.levels_unsaved


def test_a_profile_rename_carries_the_levels(monkeypatch):
    pipeline = make_pipeline(monkeypatch, layout="5.1")
    state = pipeline.controller.settings.output
    state.update({"device": "old", "device_channels": {}})
    state["device_surround_levels"]["old"] = {"FC": 1.0}
    pipeline.levels_owner = "old"
    pipeline.levels = {"FC": 1.0}
    pipeline._migrate("old", "new")
    assert state["device_surround_levels"] == {"new": {"FC": 1.0}}
    assert pipeline.levels_owner == "new"
    assert not pipeline.levels_unsaved
