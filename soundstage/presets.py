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
        return self.section.setdefault(effect_id, {})

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


def _eq_side():
    return {
        f"band{i}": {"frequency": float(f), "gain": 0.0, "mode": "RLC (BT)", "mute": False, "q": 1.504760237537245,
                     "slope": "x1", "solo": False, "type": "Bell", "width": 4.0}
        for i, f in enumerate(EQ_FREQUENCIES)
    }


# Easy Effects' own defaults for a newly added effect.
DEFAULTS = {
    "equalizer": {"bypass": False, "input-gain": 0.0, "output-gain": 0.0, "mode": "IIR", "num-bands": 10,
                  "split-channels": False, "balance": 0.0, "left": _eq_side(), "right": _eq_side()},
    "limiter": {"bypass": False, "input-gain": 0.0, "output-gain": 0.0, "mode": "Herm Thin",
                "oversampling": "None", "dithering": "None", "threshold": -1.0, "attack": 5.0, "release": 5.0,
                "lookahead": 5.0, "stereo-link": 100.0, "sidechain-preamp": 0.0, "gain-boost": True,
                "alr": False, "alr-attack": 5.0, "alr-release": 50.0, "alr-knee": 0.0},
    "compressor": {"bypass": False, "input-gain": 0.0, "output-gain": 0.0, "mode": "Downward",
                   "threshold": -12.0, "ratio": 4.0, "knee": -6.0, "attack": 20.0, "release": 100.0,
                   "release-threshold": -80.01, "makeup": 0.0, "boost-threshold": -72.0, "boost-amount": 6.0,
                   "dry": -80.01, "wet": 0.0, "hpf-mode": "Off", "hpf-frequency": 10.0, "lpf-mode": "Off",
                   "lpf-frequency": 20000.0,
                   "sidechain": {"type": "Feed-forward", "mode": "RMS", "source": "Middle",
                                 "stereo-split-source": "Left/Right", "lookahead": 0.0, "reactivity": 10.0,
                                 "preamp": 0.0}},
    "gate": {"bypass": False, "input-gain": 0.0, "output-gain": 0.0, "curve-threshold": -24.0,
             "curve-zone": -6.0, "hysteresis": False, "hysteresis-threshold": -12.0, "hysteresis-zone": -6.0,
             "reduction": -24.0, "attack": 20.0, "release": 100.0, "makeup": 0.0, "dry": -80.01, "wet": 0.0,
             "hpf-mode": "Off", "hpf-frequency": 10.0, "lpf-mode": "Off", "lpf-frequency": 20000.0,
             "sidechain": {"type": "Internal", "mode": "RMS", "source": "Middle",
                           "stereo-split-source": "Left/Right", "lookahead": 0.0, "reactivity": 10.0,
                           "preamp": 0.0}},
    "loudness": {"bypass": False, "input-gain": 0.0, "output-gain": 0.0, "std": "ISO226-2003", "fft": "4096",
                 "volume": -6.0, "clipping": False, "clipping-range": 6.0},
    "autogain": {"bypass": False, "target": -23.0, "silence-threshold": -70.0, "maximum-gain": 36.0},
    "maximizer": {"bypass": False, "threshold": 0.0, "ceiling": 0.0, "release": 25.0},
    "deepfilternet": {"bypass": False, "input-gain": 0.0, "output-gain": 0.0, "attenuation-limit": 100.0,
                      "min-processing-threshold": -10.0, "max-erb-processing-threshold": 30.0,
                      "max-df-processing-threshold": 20.0, "min-processing-buffer": 0, "post-filter-beta": 0.02},
    "convolver": {"bypass": False, "input-gain": 0.0, "output-gain": 0.0, "kernel-name": "", "ir-width": 100},
    "multiband_compressor": {"bypass": False, "input-gain": 0.0, "output-gain": 0.0,
                             "compressor-mode": "Modern", "envelope-boost": "None", "dry": -80.01, "wet": 0.0},
}
