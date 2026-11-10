import json

import pytest

from skitz_effects import presets

from .conftest import write_wav


def test_list_presets_sorts_without_case(ee_root):
    assert list(presets.list_presets()) == ["Bass Boosted", "Dali iO6", "Laptop", "Perfect EQ"]
    assert presets.list_presets("input") == {}


def test_load_easy_effects_7_preset(ee_root):
    preset = presets.load("Dali iO6")
    assert preset.order == ["equalizer#0", "bass_loudness#0", "convolver#0", "limiter#0"]
    assert presets.kind_of("bass_loudness#0") == "bass_loudness"
    assert preset.enabled("equalizer#0")
    assert not preset.enabled("convolver#0")


def test_load_easy_effects_6_preset(ee_root):
    preset = presets.load("Bass Boosted")
    assert preset.order[0] == "equalizer"
    assert presets.kind_of("equalizer") == "equalizer"
    # Easy Effects 6 has no bypass key, so everything listed is on.
    assert all(preset.enabled(e) for e in preset.order)
    assert preset.settings("convolver")["input-gain"] == -2.0


def test_missing_or_broken_presets_load_as_none(ee_root):
    assert presets.load("Nope") is None
    (ee_root / "output" / "Broken.json").write_text("{")
    assert presets.load("Broken") is None


def test_edits_save_in_place(ee_root):
    preset = presets.load("Perfect EQ")
    effect_id = preset.add("limiter")
    assert effect_id == "limiter#0"
    assert preset.add("limiter") == "limiter#1"
    preset.set_enabled("equalizer", False)
    preset.move("limiter#1", -10)
    preset.save()
    data = json.loads((ee_root / "output" / "Perfect EQ.json").read_text())["output"]
    assert data["plugins_order"] == ["limiter#1", "equalizer", "limiter#0"]
    assert data["equalizer"]["bypass"] is True
    assert data["limiter#0"]["threshold"] == presets.DEFAULTS["limiter"]["threshold"]


def test_create_writes_an_empty_preset(ee_root):
    preset = presets.create("New", "input")
    assert json.loads(preset.path.read_text()) == {"input": {"blocklist": [], "plugins_order": []}}
    assert presets.list_presets("input") == {"New": preset.path}


def test_autoload_rules(ee_root):
    assert presets.autoload_rules() == {
        "alsa_output.usb-0a12_DALI_IO_100306010587-00.analog-stereo": "Dali iO6",
        "alsa_output.usb-Burr-Brown_from_TI_USB_Audio_CODEC-00.analog-stereo-output": "HS8",
    }


def test_irs_and_wav_channels(ee_root, tmp_path):
    hrir = write_wav(ee_root / "irs" / "atmos.wav", 14)
    write_wav(ee_root / "irs" / "Room.irs", 2)
    (ee_root / "irs" / "notes.txt").write_text("x")
    assert presets.list_irs() == {"atmos": hrir, "Room": ee_root / "irs" / "Room.irs"}
    assert presets.wav_channels(hrir) == 14
    assert presets.wav_channels(ee_root / "irs" / "notes.txt") == 0
    assert presets.wav_channels(tmp_path / "missing.wav") == 0


def test_device_positions_from_props():
    from skitz_effects.pipewire import _positions
    assert _positions({"props": {"audio.position": "[ MONO ]"}}) == ("MONO",)
    assert _positions({"props": {"audio.position": "FL,FR"}}) == ("FL", "FR")
    assert _positions({"props": {}, "params": {"Format": [{"position": ["FL", "FR"]}]}}) == ("FL", "FR")


def test_levels_rise_at_once_and_fall_steadily():
    import numpy as np
    from skitz_effects import levels
    shown = np.array([-60.0, -10.0])
    out = levels.smooth(shown, np.array([-20.0, -90.0]), 0.5)
    assert out[0] == -20.0
    assert out[1] == -10.0 - levels.RELEASE * 0.5
    assert levels.smooth(np.array([-89.0]), np.array([-90.0]), 10)[0] == levels.FLOOR


def test_layout_names():
    from skitz_effects.pipewire import layout_name
    assert layout_name(("FL", "FR"), 2) == "Stereo"
    assert layout_name(("MONO",), 1) == "Mono"
    assert layout_name(("FL", "FR", "FC", "LFE", "RL", "RR"), 6) == "5.1"
    assert layout_name(("FL", "FR", "FC", "LFE", "RL", "RR", "SL", "SR"), 8) == "7.1"
    assert layout_name((), 8) == "7.1"
    assert layout_name(tuple(f"AUX{i}" for i in range(8)), 8) == "8 channels"
    assert layout_name(("FL", "FR", "RL", "RR"), 4) == "4 channels"


def test_missing_settings_read_as_easy_effects_defaults(ee_root):
    preset = presets.load("Laptop")
    gate = preset.settings("gate#0")
    assert gate["curve-threshold"] == -40.0
    assert gate["sidechain"]["mode"] == "Peak"
    del gate["reduction"], gate["sidechain"]["reactivity"]
    gate = preset.settings("gate#0")
    assert gate["reduction"] == presets.DEFAULTS["gate"]["reduction"]
    assert gate["sidechain"]["reactivity"] == 10.0
    band = preset.settings("multiband_compressor#0")["band7"]
    assert band["split-frequency"] == 16000.0 and band["enable-band"] is False
    assert presets.DEFAULTS["multiband_compressor"]["band7"]["sidechain-lowcut-frequency"] == 16000.0


def test_new_effects_do_not_share_default_objects(ee_root):
    preset = presets.load("Perfect EQ")
    first, second = preset.add("equalizer"), preset.add("equalizer")
    preset.settings(first)["left"]["band0"]["gain"] = 6.0
    assert preset.settings(second)["left"]["band0"]["gain"] == 0.0
    assert presets.DEFAULTS["equalizer"]["left"]["band0"]["gain"] == 0.0
    assert len(presets.DEFAULTS["equalizer"]["left"]) == presets.DEFAULTS["equalizer"]["num-bands"] == 10


def test_importing_an_ir_copies_it_into_the_shared_folder(ee_root, tmp_path):
    source = tmp_path / "Room.wav"
    source.write_bytes(b"one")
    dest = presets.import_ir(source)
    assert dest == presets.ir_dir() / "Room.wav"
    assert dest.read_bytes() == b"one"
    assert presets.list_irs()["Room"] == dest
    source.write_bytes(b"two")
    with pytest.raises(FileExistsError):
        presets.import_ir(source)
    presets.import_ir(source, replace=True)
    assert dest.read_bytes() == b"two"
    assert presets.import_ir(dest) == dest
