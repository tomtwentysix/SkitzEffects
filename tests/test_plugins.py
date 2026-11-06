import pytest

from skitz_effects import graph, plugins, presets


def test_equalizer_from_the_dali_preset(ee_root):
    preset = presets.load("Dali iO6")
    settings = preset.settings("equalizer#0")
    controls = plugins.effect("equalizer").controls(settings)
    band0 = settings["left"]["band0"]
    assert controls["gl_0"] == pytest.approx(graph.db(band0["gain"]))
    assert controls["fl_0"] == band0["frequency"]
    assert controls["ftl_0"] == plugins.EQ_TYPES.index(band0["type"])
    assert controls["g_in"] == pytest.approx(graph.db(settings["input-gain"]))
    assert controls["mode"] == ("IIR", "FIR", "FFT", "SPM").index(settings["mode"])
    # Bands past num-bands are switched off.
    n = settings["num-bands"]
    assert all(controls[f"ftl_{i}"] == controls[f"ftr_{i}"] == 0.0 for i in range(n, plugins.EQ_BANDS))


def test_equalizer_mirrors_left_unless_split():
    left = {"band0": {"gain": 6.0, "frequency": 100.0}}
    right = {"band0": {"gain": -6.0, "frequency": 200.0}}
    eq = plugins.effect("equalizer")
    joined = eq.controls({"num-bands": 1, "split-channels": False, "left": left, "right": right})
    assert joined["gr_0"] == joined["gl_0"] == pytest.approx(graph.db(6.0))
    split = eq.controls({"num-bands": 1, "split-channels": True, "left": left, "right": right})
    assert split["gr_0"] == pytest.approx(graph.db(-6.0))
    assert split["fr_0"] == 200.0


def test_limiter_from_the_dali_preset(ee_root):
    settings = presets.load("Dali iO6").settings("limiter#0")
    controls = plugins.effect("limiter").controls(settings)
    assert controls["th"] == pytest.approx(graph.db(settings["threshold"]))
    assert controls["boost"] == 1.0
    assert controls["dith"] == 0.0
    assert controls["at"] == settings["attack"]


def test_bass_loudness_takes_linear_values(ee_root):
    settings = presets.load("Dali iO6").settings("bass_loudness#0")
    controls = plugins.effect("bass_loudness").controls(settings)
    assert set(controls) == {"loudness", "output", "link"}
    assert controls["link"] == pytest.approx(0.3508, abs=1e-4)
    assert all(0 <= v <= 1 for v in controls.values())


def test_laptop_preset_maps_completely(ee_root):
    preset = presets.load("Laptop")
    for effect_id in preset.order:
        effect = plugins.effect(presets.kind_of(effect_id))
        controls = effect.controls(preset.settings(effect_id))
        assert controls, effect_id
        assert all(isinstance(v, float) for v in controls.values()), effect_id


def test_old_enum_names_are_aliased(ee_root):
    settings = presets.load("Laptop")
    compressor = plugins.effect("compressor").controls(settings.settings("compressor#0"))
    assert compressor["cm"] == plugins.COMP_MODES.index("Up")
    limiter = plugins.effect("limiter").controls(settings.settings("limiter#0"))
    assert limiter["ovs"] == plugins.OVERSAMPLING.index("True Peak/16 bit")
    assert plugins.Param("x", "x", "enum", ("A", "B")).control("C") is None


def test_expander_maps_easy_effects_defaults():
    controls = plugins.effect("expander").controls(presets.DEFAULTS["expander"])
    assert controls["em"] == 1  # Upward, as LSP's "Up"
    assert controls["er"] == 4.0
    assert controls["al"] == pytest.approx(graph.db(-12.0))
    assert controls["sci"] == 0
    assert controls["scm"] == 1


def test_ports_are_unique_per_effect():
    for effect in plugins.EFFECTS.values():
        ports = [p.port for p in effect.params if p.port]
        assert len(ports) == len(set(ports)), effect.kind


def test_availability_follows_installed_bundles(lv2):
    assert plugins.effect("bass_loudness").available()
    assert plugins.effect("convolver").available()
    assert not plugins.effect("exciter").available()
    (lv2 / "mda.lv2").rmdir()
    assert not plugins.effect("bass_loudness").available()
    assert plugins.effect("no_such_thing").missing == "Unknown effect"
