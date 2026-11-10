"""Settings that belong to Skitz Effects itself; effect settings live in Easy Effects presets."""

import json
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from gi.repository import GLib

DEVEL = os.environ.get("SKITZ_DEVEL") == "1"
APP_NAME = "skitz-effects-devel" if DEVEL else "skitz-effects"
ICON_NAME = "uk.co.solarflareit.SkitzEffects"
APP_ID = ICON_NAME + (".Devel" if DEVEL else "")

LAYOUTS = {
    "stereo": ("FL", "FR"),
    "5.1": ("FL", "FR", "FC", "LFE", "RL", "RR"),
    "7.1": ("FL", "FR", "FC", "LFE", "RL", "RR", "SL", "SR"),
}


def config_dir():
    return Path(GLib.get_user_config_dir()) / APP_NAME


def runtime_dir():
    return Path(GLib.get_user_runtime_dir()) / APP_NAME


CONFIG_PATH = config_dir() / "config.json"


def side():
    # device_presets maps a device's node.name to the preset loaded when Skitz Effects switches to it;
    # device_channels maps an input to the one channel position it is recorded from.
    return {"enabled": True, "preset": "", "device": "", "device_presets": {}, "device_names": {},
            "device_channels": {}}


def meter():
    # tap is "before", "after", or the step of the chain it follows, such as "equalizer_0" or "surround".
    return {"layout": "stereo", "tap": "after"}


@dataclass
class Settings:
    setup_done: bool = False
    output: dict = field(default_factory=side)
    input: dict = field(default_factory=side)
    layout: str = "7.1"
    # "auto" downmixes with the HRIR only when the device has fewer channels than the layout.
    downmix: str = "auto"
    hrir: str = ""
    # Gain in dB per channel before the HRIR, such as {"FC": 3.0}.
    surround_levels: dict = field(default_factory=dict)
    run_in_background: bool = True
    # Only applies to the launch at login.
    start_minimised: bool = True
    show_tray: bool = True
    # "curves" or "bars".
    analyser: str = "curves"
    meters: dict = field(default_factory=lambda: {"output": meter(), "input": meter()})

    def save(self):
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = CONFIG_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self), indent=2))
        tmp.replace(CONFIG_PATH)


def load():
    try:
        data = json.loads(CONFIG_PATH.read_text())
    except (OSError, ValueError):
        return Settings()
    known = {f.name for f in fields(Settings)}
    settings = Settings(**{k: v for k, v in data.items() if k in known})
    for direction in ("output", "input"):
        setattr(settings, direction, {**side(), **getattr(settings, direction)})
    settings.meters = {d: {**meter(), **settings.meters.get(d, {})} for d in ("output", "input")}
    return settings
