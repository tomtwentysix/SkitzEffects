import json
from types import SimpleNamespace

import numpy as np
import pytest

from skitz_effects import config, graph, levels
from skitz_effects.levels import Meters, TapSpec


class FakePipeline:
    def __init__(self, device, steps=()):
        self.device = device
        self._steps = list(steps)

    def connect(self, *_args):
        pass

    def steps(self):
        return self._steps


@pytest.fixture
def meters():
    settings = config.Settings()
    output = FakePipeline(SimpleNamespace(name="alsa_output.dac"), [
        ("surround", "Surround Downmix", f"{graph.PLAYBACK}.surround"),
        ("equalizer_0", "Equalizer", graph.PLAYBACK)])
    inputs = FakePipeline(SimpleNamespace(name="alsa_input.mic"))
    controller = SimpleNamespace(settings=settings, output=output, input=inputs, pipelines=(output, inputs))
    return Meters(controller)


def test_meters_default_to_stereo_after_the_effects(meters):
    assert meters.layout("output") == "stereo"
    assert meters.tap("output") == "after"
    assert meters._meter_spec("output") == TapSpec("alsa_output.dac", True, False, "stereo")
    assert meters._meter_spec("input") == TapSpec(graph.SOURCE, False, False, "stereo")


def test_tap_points_run_in_chain_order(meters):
    assert meters.tap_points("output") == [
        ("before", "Before Effects"), ("surround", "After Surround Downmix"), ("equalizer_0", "After Equalizer"),
        ("after", "Final Output")]
    assert meters.tap_points("input") == [("before", "Before Effects"), ("after", "Final Output")]


def test_a_step_is_tapped_on_its_own_stream(meters, monkeypatch):
    monkeypatch.setattr(config.Settings, "save", lambda self: None)
    meters.set_meter("output", tap="surround", layout="7.1")
    spec = meters._meter_spec("output")
    assert spec == TapSpec(f"{graph.PLAYBACK}.surround", False, False, "7.1", linked=True)
    meters.set_meter("output", tap="before")
    assert meters._meter_spec("output") == TapSpec(graph.SINK, True, False, "7.1")
    meters.set_meter("input", tap="before", layout="mono")
    assert meters._meter_spec("input") == TapSpec("alsa_input.mic", False, False, "mono")


def test_a_new_layout_resizes_the_peaks_at_once(meters, monkeypatch):
    monkeypatch.setattr(config.Settings, "save", lambda self: None)
    assert len(meters.peaks["output"]) == 2
    meters.set_meter("output", layout="7.1")
    assert list(meters.peaks["output"]) == [levels.FLOOR] * 8


def test_a_step_gone_from_the_chain_reads_the_output(meters):
    meters.controller.settings.meters["output"]["tap"] = "limiter_0"
    assert meters.tap("output") == "after"
    meters.controller.settings.meters["output"]["layout"] = "9.1.6"
    assert meters.layout("output") == "stereo"


def test_meter_and_spectrum_share_a_tap(meters):
    wanted = meters._wanted()
    assert wanted[("output", "meter")] == wanted[("output", "after")]
    meters.controller.settings.meters["output"]["layout"] = "5.1"
    wanted = meters._wanted()
    assert wanted[("output", "meter")] != wanted[("output", "after")]
    assert len(set(wanted.values())) == len(wanted) - 1


def test_the_input_meter_opens_the_mic_only_while_shown(meters):
    meters.visible = "input"
    assert meters._meter_spec("input").active
    meters.controller.settings.meters["input"]["tap"] = "before"
    assert meters._meter_spec("input") == TapSpec("alsa_input.mic", False, True, "stereo")


def test_spectrum_mixes_every_channel():
    samples = np.zeros((levels.FFT, 8), np.float32)
    t = np.arange(levels.FFT) / levels.RATE
    samples[:, 6] = np.sin(2 * np.pi * 1000 * t)
    db = levels.spectrum(samples)
    assert db[np.argmin(abs(levels.POINTS - 1000))] > -30


def test_meter_settings_load_with_defaults(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    monkeypatch.setattr(config, "CONFIG_PATH", path)
    assert config.load().meters == {"output": config.meter(), "input": config.meter()}
    path.write_text(json.dumps({"meters": {"output": {"layout": "7.1"}}}))
    settings = config.load()
    assert settings.meters["output"] == {"layout": "7.1", "tap": "after"}
    assert settings.meters["input"] == config.meter()
    settings.meters["input"]["tap"] = "equalizer_0"
    settings.save()
    assert config.load().meters["input"]["tap"] == "equalizer_0"
