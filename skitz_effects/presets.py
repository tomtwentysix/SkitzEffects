"""Reads and writes Easy Effects presets in place, so both apps share them.

A preset file is {"output": {"plugins_order": ["equalizer#0", ...],
"equalizer#0": {...}, ...}}. Presets from Easy Effects 6 use bare names such as
"equalizer" and have no "bypass" key.
"""

import copy
import json
import struct
from pathlib import Path

from gi.repository import GLib

FLATPAK = Path.home() / ".var/app/com.github.wwmm.easyeffects"


def roots():
    """Easy Effects data folders, preferred first. New presets are saved to the first."""
    candidates = [
        FLATPAK / "data/easyeffects",
        Path(GLib.get_user_data_dir()) / "easyeffects",
        FLATPAK / "config/easyeffects",
        Path(GLib.get_user_config_dir()) / "easyeffects",
    ]
    found = [p for p in candidates if p.is_dir()]
    return found or [candidates[1]]


def kind_of(effect_id):
    return effect_id.split("#")[0]


class Preset:
    def __init__(self, name, path, data=None, section="output"):
        self.name = name
        self.path = Path(path)
        self.section_name = section
        self.data = data if data is not None else json.loads(self.path.read_text())
        self.data.setdefault(section, {}).setdefault("plugins_order", [])

    @property
    def section(self):
        return self.data[self.section_name]

    @property
    def order(self):
        return self.section["plugins_order"]

    def settings(self, effect_id):
        return fill_defaults(self.section.setdefault(effect_id, {}), DEFAULTS.get(kind_of(effect_id), {}))

    def enabled(self, effect_id):
        return not self.settings(effect_id).get("bypass", False)

    def set_enabled(self, effect_id, on):
        self.settings(effect_id)["bypass"] = not on

    def add(self, kind):
        n = 0
        while f"{kind}#{n}" in self.order:
            n += 1
        effect_id = f"{kind}#{n}"
        self.section[effect_id] = copy.deepcopy(DEFAULTS.get(kind, {"bypass": False}))
        self.order.append(effect_id)
        return effect_id

    def remove(self, effect_id):
        self.order.remove(effect_id)
        self.section.pop(effect_id, None)

    def move(self, effect_id, offset):
        i = self.order.index(effect_id)
        j = max(0, min(len(self.order) - 1, i + offset))
        self.order.insert(j, self.order.pop(i))

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=4))
        tmp.replace(self.path)


def list_presets(section="output"):
    found = {}
    for root in roots():
        for path in sorted((root / section).glob("*.json")):
            found.setdefault(path.stem, path)
    return dict(sorted(found.items(), key=lambda kv: kv[0].casefold()))


def load(name, section="output"):
    path = list_presets(section).get(name)
    if path is None:
        return None
    try:
        return Preset(name, path, section=section)
    except (OSError, ValueError):
        return None


def create(name, section="output"):
    preset = Preset(name, roots()[0] / section / f"{name}.json", {section: {"blocklist": [], "plugins_order": []}},
                    section)
    preset.save()
    return preset


def autoload_rules(section="output"):
    """Easy Effects' per-device presets as {node name: preset name}."""
    rules = {}
    for root in roots():
        for path in (root / "autoload" / section).glob("*.json"):
            try:
                data = json.loads(path.read_text())
                rules.setdefault(data["device"], data["preset-name"])
            except (OSError, ValueError, KeyError):
                continue
    return rules


def list_irs():
    found = {}
    for root in roots():
        for path in sorted((root / "irs").glob("*")):
            if path.suffix.lower() in (".irs", ".wav"):
                found.setdefault(path.stem, path)
    return dict(sorted(found.items(), key=lambda kv: kv[0].casefold()))


def wav_channels(path):
    """Channel count from a RIFF/WAVE header, or 0 if the file is not one."""
    try:
        with open(path, "rb") as f:
            if f.read(4) != b"RIFF" or f.read(8)[4:] != b"WAVE":
                return 0
            while chunk := f.read(8):
                tag, size = chunk[:4], struct.unpack("<I", chunk[4:])[0]
                if tag == b"fmt ":
                    return struct.unpack("<HH", f.read(4))[1]
                f.seek(size + (size & 1), 1)
    except (OSError, struct.error):
        pass
    return 0


EQ_FREQUENCIES = (32, 64, 125, 250, 500, 1000, 2000, 4000, 8000, 16000)
MB_SPLITS = (500.0, 1000.0, 2000.0, 4000.0, 8000.0, 12000.0, 16000.0)


def _eq_side():
    return {
        f"band{i}": {"frequency": float(f), "gain": 0.0, "mode": "RLC (BT)", "mute": False, "q": 1.504760237537245,
                     "slope": "x1", "solo": False, "type": "Bell", "width": 4.0}
        for i, f in enumerate(EQ_FREQUENCIES)
    }


def _gains():
    return {"bypass": False, "input-gain": 0.0, "output-gain": 0.0}


def _mix():
    return {key: -80.01 for key in ("input-to-link", "input-to-sidechain", "link-to-input", "link-to-sidechain",
                                    "sidechain-to-input", "sidechain-to-link")}


def _dynamics(sidechain_type):
    return {**_gains(), **_mix(), "dry": -80.01, "wet": 0.0, "makeup": 0.0, "attack": 20.0, "release": 100.0,
            "stereo-split": False, "hpf-mode": "Off", "hpf-frequency": 10.0, "lpf-mode": "Off",
            "lpf-frequency": 20000.0,
            "sidechain": {"type": sidechain_type, "mode": "Peak", "source": "Middle",
                          "stereo-split-source": "Left/Right", "lookahead": 0.0, "reactivity": 10.0, "preamp": 0.0}}


def _mb_band(i):
    band = {"compression-mode": "Downward", "compressor-enable": True, "solo": False, "mute": False,
            "attack-threshold": -12.0, "attack-time": 20.0, "release-threshold": -80.01, "release-time": 100.0,
            "ratio": 1.0, "knee": -6.0, "makeup": 0.0, "boost-threshold": -72.0, "boost-amount": 6.0,
            "sidechain-type": "Internal", "sidechain-mode": "RMS", "sidechain-source": "Middle",
            "stereo-split-source": "Left/Right", "sidechain-lookahead": 0.0, "sidechain-reactivity": 10.0,
            "sidechain-preamp": 0.0, "sidechain-custom-lowcut-filter": False,
            "sidechain-custom-highcut-filter": False,
            "sidechain-lowcut-frequency": MB_SPLITS[i - 1] if i else 10.0,
            "sidechain-highcut-frequency": MB_SPLITS[i] if i < len(MB_SPLITS) else 20000.0}
    if i:
        band["enable-band"] = i <= 3
        band["split-frequency"] = MB_SPLITS[i - 1]
    return band


# Easy Effects' own defaults for a newly added effect, from its kcfg files as of 8.3.2, except the
# equalizer, which starts with 10 octave bands rather than Easy Effects' 32.
DEFAULTS = {
    "equalizer": {**_gains(), "mode": "IIR", "num-bands": 10, "split-channels": False, "balance": 0.0,
                  "left": _eq_side(), "right": _eq_side()},
    "limiter": {**_gains(), **_mix(), "mode": "Herm Thin", "oversampling": "None", "dithering": "None",
                "sidechain-type": "Internal", "threshold": 0.0, "attack": 5.0, "release": 5.0, "lookahead": 5.0,
                "stereo-link": 100.0, "sidechain-preamp": 0.0, "gain-boost": True, "alr": False,
                "alr-attack": 5.0, "alr-release": 50.0, "alr-knee": 0.0, "alr-knee-smooth": -5.0},
    "compressor": {**_dynamics("Feed-forward"), "mode": "Downward", "threshold": -12.0, "ratio": 4.0,
                   "knee": -6.0, "release-threshold": -80.01, "boost-threshold": -72.0, "boost-amount": 6.0},
    "expander": {**_dynamics("Internal"), "mode": "Upward", "threshold": -12.0, "ratio": 4.0, "knee": -6.0,
                 "release-threshold": -80.01},
    "gate": {**_dynamics("Internal"), "curve-threshold": -24.0, "curve-zone": -6.0, "hysteresis": False,
             "hysteresis-threshold": -12.0, "hysteresis-zone": -6.0, "reduction": -24.0},
    "multiband_compressor": {**_gains(), **_mix(), "compressor-mode": "Modern", "envelope-boost": "None",
                             "dry": -80.01, "wet": 0.0, "stereo-split": False,
                             **{f"band{i}": _mb_band(i) for i in range(8)}},
    "loudness": {**_gains(), "std": "ISO226-2023", "fft": "4096", "volume": 0.0, "clipping": False,
                 "clipping-range": 6.0},
    "autogain": {**_gains(), "target": -23.0, "silence-threshold": -70.0, "maximum-gain": 36.0},
    "maximizer": {**_gains(), "threshold": 0.0, "ceiling": 0.0, "release": 25.0},
    "bass_loudness": {**_gains(), "loudness": -3.1, "output": -6.0, "link": -9.1},
    "deepfilternet": {**_gains(), "attenuation-limit": 100.0, "min-processing-threshold": -10.0,
                      "max-erb-processing-threshold": 30.0, "max-df-processing-threshold": 20.0,
                      "min-processing-buffer": 0, "post-filter-beta": 0.02},
    "convolver": {**_gains(), "kernel-name": "", "ir-width": 100, "autogain": True, "dry": -100.0, "wet": 0.0},
}


def fill_defaults(settings, defaults):
    """Adds the keys an older or hand-written preset lacks, so they read as Easy Effects would read them."""
    for key, value in defaults.items():
        if isinstance(value, dict) and isinstance(settings.get(key), dict):
            fill_defaults(settings[key], value)
        elif key not in settings:
            settings[key] = copy.deepcopy(value)
    return settings
