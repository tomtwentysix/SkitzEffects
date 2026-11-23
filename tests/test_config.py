import json

from skitz_effects import config


def load_from(tmp_path, monkeypatch, data):
    path = tmp_path / "config.json"
    path.write_text(json.dumps(data))
    monkeypatch.setattr(config, "CONFIG_PATH", path)
    return config.load()


def test_old_global_levels_move_to_the_current_device(tmp_path, monkeypatch):
    settings = load_from(tmp_path, monkeypatch, {"surround_levels": {"FC": 3.0}, "output": {"device": "alsa_output.a"}})
    assert settings.output["device_surround_levels"] == {"alsa_output.a": {"FC": 3.0}}
    assert not hasattr(settings, "surround_levels")


def test_old_global_levels_without_a_device_are_dropped(tmp_path, monkeypatch):
    settings = load_from(tmp_path, monkeypatch, {"surround_levels": {"FC": 3.0}})
    assert settings.output["device_surround_levels"] == {}


def test_only_the_output_has_device_levels(tmp_path, monkeypatch):
    settings = load_from(tmp_path, monkeypatch, {})
    assert "device_surround_levels" in settings.output
    assert "device_surround_levels" not in settings.input
