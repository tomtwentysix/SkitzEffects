from skitz_effects import check
from skitz_effects.ui import check as ui

S = lambda key, kind: check.Stage(key, key, kind, key)
R = lambda **kw: check.Reading(**kw)


def test_overs_text():
    assert ui.overs_text(R(frames=10)) == "No overs"
    assert ui.overs_text(R(peak=10 ** (4.1 / 20), overs=37)) == "Over by up to 4.1 dB, 37 times"
    assert ui.overs_text(R(peak=10 ** (0.5 / 20), overs=1)) == "Over by up to 0.5 dB, 1 time"


def test_the_surround_stage_has_no_expected_drop():
    assert ui.change_text(-3.0) == "-3.0 dB"
    assert ui.change_text(-9.9) == "Drops 9.9 dB"


def test_a_flagged_drop_is_reported_as_a_drop():
    assert ui.change_text(-23.4) == "Drops 23.4 dB"
    assert ui.change_text(-30.0) == "Drops 30.0 dB"


def test_ordinary_changes_and_unmeasured_stages():
    assert ui.change_text(-2.04) == "-2.0 dB"
    assert ui.change_text(3.0) == "+3.0 dB"
    assert ui.change_text(None) is None


def test_planned_cut_text_for_each_control():
    assert ui.cut_text(check.Cut("a", "output-gain", -4.6)) == "Output gain lowered by 4.6 dB"
    assert ui.cut_text(check.Cut("surround", "surround", -2.0)) == "Surround levels lowered by 2.0 dB"
    assert ui.cut_text(check.Cut("a", "ceiling", -1.0)) == "Ceiling lowered by 1.0 dB"
    assert ui.cut_text(check.Cut("a", "volume", -1.0)) == "Volume lowered by 1.0 dB"
    assert ui.cut_text(check.Cut("a", "target", -1.0)) == "Target lowered by 1.0 LU, applied gradually"


def test_input_and_leftover_lines():
    assert ui.input_text(R(overs=2, peak=2.0)) == "Apps are sending audio over 0 dB"
    assert ui.input_text(R(frames=5)) is None
    assert ui.leftover_text(6.5) == "Could not lower the preset by a further 6.5 dB"
    assert ui.leftover_text(0.0) is None


def test_nothing_measured():
    assert ui.nothing_measured(R(), {"a": R(), "b": R()})
    assert not ui.nothing_measured(R(frames=1), {"a": R(), "b": R()})
    assert not ui.nothing_measured(R(), {"a": R(), "b": R(frames=1)})
    assert not ui.nothing_measured(R(), {"a": R(overs=1, peak=2.0), "b": R()})
    assert not ui.nothing_measured(R(overs=1, peak=2.0), {"a": R(), "b": R()})


def test_elapsed_text():
    assert ui.elapsed_text(7.4) == "0:07"
    assert ui.elapsed_text(75.0) == "1:15"
