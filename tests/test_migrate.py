import pytest

from skitz_effects import config, deps, migrate, names


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(migrate, "OLD_CONFIG", tmp_path / "soundstage")
    monkeypatch.setattr(migrate, "OLD_NAMES", tmp_path / "wp" / "60-soundstage-devices.conf")
    monkeypatch.setattr(migrate, "OLD_AUTOSTART", tmp_path / "autostart" / "old.desktop")
    monkeypatch.setattr(config, "config_dir", lambda: tmp_path / "skitz-effects")
    monkeypatch.setattr(names, "OWN", tmp_path / "wp" / "60-skitz-effects-devices.conf")
    monkeypatch.setattr(deps, "AUTOSTART", tmp_path / "autostart" / "new.desktop")
    return tmp_path


def test_moves_old_files(home):
    (home / "soundstage").mkdir()
    (home / "soundstage" / "config.json").write_text("{}")
    (home / "wp").mkdir()
    (home / "wp" / "60-soundstage-devices.conf").write_text("rules")
    (home / "autostart").mkdir()
    (home / "autostart" / "old.desktop").write_text("Exec=soundstage")

    migrate.from_soundstage("skitz-effects")

    assert (home / "skitz-effects" / "config.json").read_text() == "{}"
    assert (home / "wp" / "60-skitz-effects-devices.conf").read_text() == "rules"
    assert not (home / "soundstage").exists()
    assert not (home / "autostart" / "old.desktop").exists()
    assert "Exec=skitz-effects --background" in (home / "autostart" / "new.desktop").read_text()


def test_keeps_newer_files_and_no_autostart(home):
    (home / "soundstage").mkdir()
    (home / "skitz-effects").mkdir()
    (home / "skitz-effects" / "config.json").write_text("new")

    migrate.from_soundstage("skitz-effects")

    assert (home / "skitz-effects" / "config.json").read_text() == "new"
    assert (home / "soundstage").exists()
    assert not (home / "autostart" / "new.desktop").exists()
