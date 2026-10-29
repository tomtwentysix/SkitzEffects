import json
import shutil
import wave
from pathlib import Path

import pytest

from skitz_effects import plugins, presets

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def ee_root(tmp_path, monkeypatch):
    """A private copy of the Easy Effects folder with the real presets in it."""
    root = tmp_path / "easyeffects"
    shutil.copytree(FIXTURES / "easyeffects", root)
    (root / "irs").mkdir()
    monkeypatch.setattr(presets, "roots", lambda: [root])
    return root


@pytest.fixture
def lv2(tmp_path, monkeypatch):
    """Makes every packaged plugin look installed, whatever the test machine has."""
    lib = tmp_path / "lv2"
    for bundle in ("lsp-plugins.lv2", "ZaMaximX2.lv2", "mda.lv2"):
        (lib / bundle).mkdir(parents=True)
    ladspa = tmp_path / "ladspa"
    ladspa.mkdir()
    (ladspa / "libdeep_filter_ladspa.so").touch()
    monkeypatch.setattr(plugins, "LV2_DIRS", [lib])
    monkeypatch.setattr(plugins, "LADSPA_DIRS", [ladspa])
    return lib


def write_wav(path, channels, rate=48000):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(bytes(2 * channels * 8))
    return path


def chain_args(text):
    """The filter-chain module's args from a generated config."""
    return json.loads(text)["context.modules"][-1]["args"]
