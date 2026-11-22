import pytest

from skitz_effects import check, presets

S = lambda key, kind: check.Stage(key, key, kind, key)
peak_db = lambda db: check.Reading(peak=10 ** (db / 20), overs=1)
AMPLE = {"surround": 12.0, "equalizer#0": 36.0, "equalizer#1": 36.0, "bass_loudness#0": 36.0}


def test_cut_targets():
    assert check.cut_target("equalizer") == ("output-gain", -36.0, 0.1)
    assert check.cut_target("loudness")[0] == "volume"
    assert check.cut_target("maximizer")[:2] == ("ceiling", -20.0)
    assert check.cut_target("autogain")[:2] == ("target", -60.0)
    assert check.cut_target("surround") == ("surround", -12.0, 0.5)
    assert check.cut_target("reverb") is None


def test_each_over_is_cut_by_its_peak_plus_margin_minus_earlier_cuts():
    stages = [S("surround", "surround"), S("equalizer#0", "equalizer"), S("bass_loudness#0", "bass_loudness")]
    readings = {
        "surround": check.Reading(peak=1.0),
        "equalizer#0": peak_db(4.1),
        "bass_loudness#0": peak_db(9.8),
    }
    cuts, left = check.plan_cuts(stages, readings, AMPLE)
    assert [(c.key, c.control) for c in cuts] == [("equalizer#0", "output-gain"), ("bass_loudness#0", "output-gain")]
    assert [c.db for c in cuts] == pytest.approx([-4.6, -5.7])
    assert left == 0


def test_an_earlier_cut_can_cover_a_later_over():
    stages = [S("equalizer#0", "equalizer"), S("bass_loudness#0", "bass_loudness")]
    readings = {"equalizer#0": peak_db(6.0), "bass_loudness#0": peak_db(3.0)}
    cuts, left = check.plan_cuts(stages, readings, AMPLE)
    assert [c.key for c in cuts] == ["equalizer#0"]
    assert cuts[0].db == pytest.approx(-6.5)
    assert left == 0


def test_surround_cuts_round_up_to_half_a_db():
    cuts, _ = check.plan_cuts([S("surround", "surround")], {"surround": peak_db(1.2)}, AMPLE)
    assert cuts == [check.Cut("surround", "surround", -2.0)]


def test_a_cut_past_its_range_carries_on():
    stages = [S("equalizer#0", "equalizer"), S("bass_loudness#0", "bass_loudness")]
    readings = {"equalizer#0": peak_db(10), "bass_loudness#0": peak_db(2)}
    room = {"equalizer#0": 4.0, "bass_loudness#0": 36.0}
    cuts, left = check.plan_cuts(stages, readings, room)
    assert [c.db for c in cuts] == pytest.approx([-4.0, -6.5])
    assert left == 0
    cuts, left = check.plan_cuts(stages[:1], readings, room)
    assert [c.db for c in cuts] == pytest.approx([-4.0])
    assert left == pytest.approx(6.5)


def test_the_same_effect_twice_is_cut_separately():
    stages = [S("equalizer#0", "equalizer"), S("equalizer#1", "equalizer")]
    readings = {"equalizer#0": peak_db(2), "equalizer#1": peak_db(5)}
    cuts, _ = check.plan_cuts(stages, readings, AMPLE)
    assert [(c.key, c.db) for c in cuts] == [("equalizer#0", pytest.approx(-2.5)), ("equalizer#1", pytest.approx(-3.0))]


def test_nothing_measured_plans_nothing():
    stages = [S("surround", "surround"), S("equalizer#0", "equalizer")]
    readings = {s.key: check.Reading() for s in stages}
    assert check.plan_cuts(stages, readings, AMPLE) == ([], 0.0)
    assert check.level_change(check.Reading(), check.Reading()) is None
    assert check.drop_flagged(stages[1], None, "7.1") is False


def test_drops():
    change = check.level_change(check.Reading(energy=1.0, frames=10), check.Reading(energy=0.01, frames=10))
    assert change == pytest.approx(-20.0)
    eq, surround = S("equalizer#0", "equalizer"), S("surround", "surround")
    assert check.drop_flagged(eq, -7.0, "7.1")
    assert not check.drop_flagged(eq, -5.0, "7.1")
    assert not check.drop_flagged(surround, -15.0, "7.1")
    assert check.drop_flagged(surround, -17.0, "7.1")


def test_level_change_compares_mean_power():
    change = check.level_change(check.Reading(energy=1.0, frames=10), check.Reading(energy=0.2, frames=20))
    assert change == pytest.approx(-10.0)


def test_a_silent_output_is_a_drop():
    change = check.level_change(check.Reading(energy=1.0, frames=10), check.Reading(frames=10))
    assert change == -120.0
    assert check.drop_flagged(S("equalizer#0", "equalizer"), change, "7.1")
    assert check.level_change(check.Reading(frames=10), check.Reading(frames=10)) is None


def test_negative_room_applies_nothing():
    stages = [S("equalizer#0", "equalizer")]
    cuts, left = check.plan_cuts(stages, {"equalizer#0": peak_db(2)}, {"equalizer#0": -1.0})
    assert cuts == []
    assert left == pytest.approx(2.5)


def test_a_carry_passes_through_a_stage_with_no_cut_target():
    stages = [S("equalizer#0", "equalizer"), S("mystery#0", "unknown"), S("bass_loudness#0", "bass_loudness")]
    readings = {"equalizer#0": peak_db(10), "mystery#0": check.Reading(), "bass_loudness#0": check.Reading()}
    room = {"equalizer#0": 4.0, "mystery#0": 0.0, "bass_loudness#0": 36.0}
    cuts, left = check.plan_cuts(stages, readings, room)
    assert [(c.key, c.db) for c in cuts] == [("equalizer#0", pytest.approx(-4.0)), ("bass_loudness#0", pytest.approx(-6.5))]
    assert left == 0


def test_trimmed_leaves_the_preset_alone(ee_root):
    p = presets.load("Dali iO6")
    t = check.trimmed(p, [check.Cut("bass_loudness#0", "output-gain", -2.0)])
    assert t.settings("bass_loudness#0")["output-gain"] == pytest.approx(-5.0)
    assert p.settings("bass_loudness#0")["output-gain"] == -3.0
    assert check.trimmed(None, [check.Cut("bass_loudness#0", "output-gain", -2.0)]) is None


def test_fold_writes_into_the_preset(ee_root):
    p = presets.load("Dali iO6")
    check.fold(p, [check.Cut("bass_loudness#0", "output-gain", -2.0)])
    assert p.settings("bass_loudness#0")["output-gain"] == pytest.approx(-5.0)


def test_fold_rounds_the_written_value(ee_root):
    p = presets.load("Dali iO6")
    p.settings("bass_loudness#0")["output-gain"] = -0.2
    check.fold(p, [check.Cut("bass_loudness#0", "output-gain", -0.1)])
    assert p.settings("bass_loudness#0")["output-gain"] == -0.3


def test_trimmed_levels():
    cut = [check.Cut("surround", "surround", -2.0)]
    assert check.trimmed_levels("5.1", {"FC": 3.0}, cut) == {"FL": -2.0, "FR": -2.0, "FC": 1.0, "LFE": -2.0, "RL": -2.0, "RR": -2.0}
    assert check.trimmed_levels("5.1", {"FC": 3.0}, []) == {"FC": 3.0}


def test_room(ee_root):
    p = presets.load("Dali iO6")
    stages = [S("bass_loudness#0", "bass_loudness"), S("surround", "surround"), S("mystery#0", "unknown")]
    room = check.room(p, stages, "7.1", {"FC": -10.0})
    assert room["bass_loudness#0"] == pytest.approx(33.0)
    assert room["surround"] == pytest.approx(2.0)
    assert room["mystery#0"] == 0.0
    assert check.room(None, stages, "7.1", {})["bass_loudness#0"] == 0.0
