import pytest

from skitz_effects import check

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
