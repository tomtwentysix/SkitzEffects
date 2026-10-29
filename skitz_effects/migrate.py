"""Moves what the app left behind when it was called Soundstage."""

from pathlib import Path

from gi.repository import GLib

from . import config, deps, names

OLD_CONFIG = Path(GLib.get_user_config_dir()) / config.APP_NAME.replace("skitz-effects", "soundstage")
OLD_NAMES = names.CONF_DIR / "60-soundstage-devices.conf"
OLD_AUTOSTART = deps.AUTOSTART.with_name("uk.co.solarflareit.Soundstage.desktop")


def from_soundstage(autostart_command):
    for old, new in ((OLD_CONFIG, config.config_dir()), (OLD_NAMES, names.OWN)):
        if old.exists() and not new.exists():
            new.parent.mkdir(parents=True, exist_ok=True)
            old.rename(new)
    # The old entry runs a command the upgrade removes, so it is rewritten rather than moved.
    if OLD_AUTOSTART.exists():
        OLD_AUTOSTART.unlink()
        deps.set_autostart(True, autostart_command)
