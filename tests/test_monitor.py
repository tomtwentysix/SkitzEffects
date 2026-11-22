from math import sqrt
from types import SimpleNamespace

import pytest
from gi.repository import GObject

from skitz_effects import check, monitor


def sample(peak, db, frames=1000):
    # Two channels at a constant RMS, so the energy is 2 * frames * rms^2.
    rms = 10 ** (db / 20)
    return peak, 2 * frames * rms ** 2, frames


def test_tick_counts_overs_and_keeps_the_largest_peak():
    before, readings = check.Reading(), {"a": check.Reading()}
    monitor.tick(before, readings, sample(0.5, -20), {"a": sample(1.5, -20)})
    monitor.tick(before, readings, sample(0.5, -20), {"a": sample(1.2, -20)})
    assert readings["a"].peak == 1.5
    assert readings["a"].overs == 2
    assert before.overs == 0


def test_tick_ignores_energy_while_the_input_is_quiet():
    before, readings = check.Reading(), {"a": check.Reading()}
    monitor.tick(before, readings, sample(0.01, -70), {"a": sample(1.5, -20)})
    for reading in (before, readings["a"]):
        assert (reading.energy, reading.frames) == (0.0, 0)
    assert readings["a"].overs == 1
    monitor.tick(before, readings, sample(0.2, -20), {"a": sample(0.2, -20)})
    for reading in (before, readings["a"]):
        assert reading.frames == 1000
        assert sqrt(reading.energy / (2 * reading.frames)) == pytest.approx(0.1)


def test_tick_counts_a_silent_stage_while_the_input_plays():
    before, readings = check.Reading(), {"a": check.Reading()}
    monitor.tick(before, readings, sample(0.2, -20), {"a": (0.0, 0.0, 480)})
    assert (readings["a"].energy, readings["a"].frames) == (0.0, 480)


def test_tick_leaves_a_stage_without_a_sample_alone():
    before, readings = check.Reading(), {"a": check.Reading(), "b": check.Reading()}
    monitor.tick(before, readings, sample(0.2, -20), {"a": sample(0.2, -20)})
    assert readings["b"] == check.Reading()


class FakePipeline(GObject.Object):
    __gsignals__ = {"state-changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
                    "preset-changed": (GObject.SignalFlags.RUN_FIRST, None, ())}

    def __init__(self):
        super().__init__()
        self.current = [check.Stage("surround", "Surround", "surround", "node")]
        self.direction = "output"
        self.device = SimpleNamespace(name="sink_a")

    def stages(self):
        return self.current


def test_check_aborts_when_the_stages_change():
    fake = FakePipeline()
    run = monitor.Check(fake)
    reasons = []
    run.connect("aborted", lambda _c, reason: reasons.append(reason))
    assert list(run.readings) == ["surround"]
    fake.emit("state-changed")
    assert reasons == []
    fake.current = []
    fake.emit("state-changed")
    assert reasons == ["The effects changed during the check"]
    run.stop()


def test_check_aborts_when_the_device_changes():
    fake = FakePipeline()
    run = monitor.Check(fake)
    reasons = []
    run.connect("aborted", lambda _c, reason: reasons.append(reason))
    assert not run._check_device(fake.device)
    fake.device = SimpleNamespace(name="sink_b")
    assert run._check_device(fake.device)
    assert reasons == ["The output device changed during the check"]


def test_check_aborts_when_the_device_goes_away():
    fake = FakePipeline()
    fake.direction = "input"
    run = monitor.Check(fake)
    reasons = []
    run.connect("aborted", lambda _c, reason: reasons.append(reason))
    assert run._check_device(None)
    assert reasons == ["The input device changed during the check"]
