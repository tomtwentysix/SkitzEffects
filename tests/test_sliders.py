import pytest

from skitz_effects import sliders
from skitz_effects.plugins import Param

FREQUENCY = Param("frequency", "", lo=10, hi=24000, step=1, digits=0, unit="Hz")
ATTACK = Param("attack", "", hi=2000, step=0.1, unit="ms")
GAIN = Param("gain", "", lo=-36, hi=36, step=0.1, unit="dB")
BETA = Param("beta", "", hi=0.05, step=0.001, digits=3)


def test_wide_ranges_are_logarithmic():
    assert sliders.logarithmic(FREQUENCY)
    assert sliders.logarithmic(ATTACK)
    assert not sliders.logarithmic(GAIN)
    assert not sliders.logarithmic(BETA)


def test_a_logarithmic_slider_spreads_octaves_evenly():
    low, mid, high = (sliders.position(FREQUENCY, f) for f in (20, 200, 2000))
    assert mid - low == pytest.approx(high - mid)
    assert sliders.position(FREQUENCY, 10) == 0.0
    assert sliders.position(FREQUENCY, 24000) == 1.0


def test_a_time_starting_at_zero_reaches_both_ends():
    assert sliders.position(ATTACK, 0) == 0.0
    assert sliders.position(ATTACK, 2000) == 1.0
    assert sliders.value_at(ATTACK, 0.0) == 0.0


def test_a_linear_slider_is_proportional():
    assert sliders.position(GAIN, 0) == pytest.approx(0.5)
    assert sliders.value_at(GAIN, 0.75) == pytest.approx(18.0)


@pytest.mark.parametrize("param, value", [(FREQUENCY, 80), (FREQUENCY, 12345), (ATTACK, 3.7), (GAIN, -4.6),
                                          (BETA, 0.02)])
def test_values_survive_a_round_trip_at_their_step(param, value):
    assert sliders.value_at(param, sliders.position(param, value)) == pytest.approx(value)


def test_positions_and_values_stay_in_range():
    assert sliders.position(GAIN, 99) == 1.0
    assert sliders.position(GAIN, -99) == 0.0
    assert sliders.value_at(FREQUENCY, 1.5) == 24000
