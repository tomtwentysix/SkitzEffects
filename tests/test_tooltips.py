from skitz_effects import plugins, tooltips
from skitz_effects.ui import eq


def test_every_shown_setting_has_a_tooltip():
    missing = [(e.kind, p.key) for e in plugins.EFFECTS.values() if not e.missing for p in e.shown()
               if not tooltips.text(e.kind, p.key)]
    assert missing == []


def test_every_equaliser_band_and_extra_setting_has_a_tooltip():
    keys = [("equalizer_band", p.key) for p in eq.BAND_PARAMS] + [
        ("equalizer", "num-bands"), ("equalizer", "split-channels"), ("convolver", "kernel-name")]
    assert [k for k in keys if not tooltips.text(*k)] == []


def test_an_effect_can_override_a_shared_tooltip():
    assert tooltips.text("limiter", "threshold") != tooltips.text("compressor", "threshold")
    assert tooltips.text("compressor", "ratio") == tooltips.SHARED["ratio"]
