"""Maps Easy Effects effect settings onto the LV2 plugins Easy Effects itself uses.

Each Param ties a key in an Easy Effects preset section ("/" walks into nested
objects) to an LV2 control port symbol. Easy Effects stores gains in dB, while
the LSP plugins take linear gain, hence the "db" kind.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

LV2_DIRS = [Path(p) for p in os.environ.get("LV2_PATH", "").split(":") if p] + [
    Path.home() / ".lv2",
    Path("/usr/lib64/lv2"),
    Path("/usr/lib/lv2"),
    Path("/usr/local/lib/lv2"),
]

LSP = "http://lsp-plug.in/plugins/lv2/"
LSP_PORTS = ("in_l", "in_r", "out_l", "out_r")


@dataclass(frozen=True)
class Param:
    key: str
    port: str
    kind: str = "float"
    options: tuple = ()
    label: str = ""
    lo: float = 0.0
    hi: float = 1.0
    step: float = 1.0
    digits: int = 1
    unit: str = ""

    def control(self, value):
        if self.kind == "db":
            return 10 ** (float(value) / 20)
        if self.kind == "bool":
            return 1.0 if value else 0.0
        if self.kind == "enum":
            value = ALIASES.get(value, value)
            return float(self.options.index(value)) if value in self.options else None
        return float(value)


@dataclass(frozen=True)
class Effect:
    kind: str
    title: str
    uri: str = ""
    bundle: str = ""
    package: str = ""
    ports: tuple = LSP_PORTS
    params: tuple = ()
    builtin: bool = False
    missing: str = ""
    custom: Callable | None = field(default=None, compare=False)

    def available(self):
        if self.builtin:
            return True
        return bool(self.bundle) and any((d / self.bundle).is_dir() for d in LV2_DIRS)

    def controls(self, data):
        if self.custom:
            return self.custom(self, data)
        return mapped_controls(self.params, data)

    def shown(self):
        return [p for p in self.params if p.label]


def lookup(data, key):
    for part in key.split("/"):
        if not isinstance(data, dict) or part not in data:
            return None
        data = data[part]
    return data


def mapped_controls(params, data):
    out = {}
    for p in params:
        value = lookup(data, p.key)
        if value is None:
            continue
        control = p.control(value)
        if control is not None:
            out[p.port] = control
    return out


# Older Easy Effects presets name LSP's oversampling modes by filter length.
ALIASES = {"Upward": "Up", "Downward": "Down", "Boosting": "Boost"}
for _kind in ("Half", "Full"):
    for _n in (2, 3, 4, 6, 8):
        ALIASES[f"{_kind} x{_n}(2L)"] = f"{_kind} x{_n}/16 bit"
        ALIASES[f"{_kind} x{_n}(3L)"] = f"{_kind} x{_n}/24 bit"

OVERSAMPLING = ("None",) + tuple(
    f"{k} x{n}/{b} bit" for k in ("Half", "Full") for n in (2, 3, 4, 6, 8) for b in (16, 24)
) + ("True Peak/16 bit", "True Peak/24 bit")
FILTER_MODES = ("Off", "12 dB/oct", "24 dB/oct", "36 dB/oct")
SC_MODES = ("Peak", "RMS", "LPF", "SMA")
SC_SOURCES = ("Middle", "Side", "Left", "Right", "Min", "Max")
SPLIT_SOURCES = ("Left/Right", "Right/Left", "Mid/Side", "Side/Mid", "Min", "Max")
COMP_MODES = ("Down", "Up", "Boost")
EQ_TYPES = ("Off", "Bell", "Hi-pass", "Hi-shelf", "Lo-pass", "Lo-shelf", "Notch", "Resonance",
            "Allpass", "Bandpass", "Ladder-pass", "Ladder-rej")
EQ_MODES = ("RLC (BT)", "RLC (MT)", "BWC (BT)", "BWC (MT)", "LRX (BT)", "LRX (MT)", "APO (DR)")
EQ_SLOPES = ("x1", "x2", "x3", "x4")
EQ_BANDS = 32


def gains(lo=-36.0, hi=36.0):
    return (
        Param("input-gain", "g_in", "db", label="Input gain", lo=lo, hi=hi, step=0.1, unit="dB"),
        Param("output-gain", "g_out", "db", label="Output gain", lo=lo, hi=hi, step=0.1, unit="dB"),
    )


def sidechain_mix():
    return tuple(
        Param(key, port, "db")
        for key, port in (
            ("input-to-link", "in2lk"), ("link-to-input", "lk2in"), ("link-to-sidechain", "lk2sc"),
            ("input-to-sidechain", "in2sc"), ("sidechain-to-input", "sc2in"),
            ("sidechain-to-link", "sc2lk"),
        )
    )


def sidechain_filters():
    return (
        Param("hpf-mode", "shpm", "enum", FILTER_MODES, "Sidechain high-pass"),
        Param("hpf-frequency", "shpf", label="High-pass frequency", lo=10, hi=20000, unit="Hz", digits=0),
        Param("lpf-mode", "slpm", "enum", FILTER_MODES, "Sidechain low-pass"),
        Param("lpf-frequency", "slpf", label="Low-pass frequency", lo=10, hi=20000, unit="Hz", digits=0),
    )


def sidechain(type_port, types):
    return (
        Param("sidechain/type", type_port, "enum", types, "Sidechain type"),
        Param("sidechain/mode", "scm", "enum", SC_MODES, "Sidechain mode"),
        Param("sidechain/source", "scs", "enum", SC_SOURCES, "Sidechain source"),
        Param("sidechain/stereo-split-source", "sscs", "enum", SPLIT_SOURCES),
        Param("sidechain/lookahead", "sla", label="Lookahead", hi=20, step=0.1, unit="ms"),
        Param("sidechain/reactivity", "scr", label="Reactivity", hi=250, step=0.1, unit="ms"),
        Param("sidechain/preamp", "scp", "db", label="Sidechain preamp", lo=-80, hi=40, step=0.1, unit="dB"),
        Param("stereo-split", "ssplit", "bool"),
    )


def equalizer_controls(effect, data):
    data = dict(data)
    if not data.get("split-channels", False) and "left" in data:
        data["right"] = data["left"]
    out = mapped_controls(effect.params, data)
    for i in range(int(data.get("num-bands", EQ_BANDS)), EQ_BANDS):
        out[f"ftl_{i}"] = out[f"ftr_{i}"] = 0.0
    return out


def equalizer_params():
    params = list(gains()) + [
        Param("mode", "mode", "enum", ("IIR", "FIR", "FFT", "SPM"), "Mode"),
        Param("balance", "bal", label="Balance", lo=-100, hi=100, unit="%", digits=0),
    ]
    for side, s in (("left", "l"), ("right", "r")):
        for i in range(EQ_BANDS):
            b = f"{side}/band{i}/"
            params += [
                Param(b + "type", f"ft{s}_{i}", "enum", EQ_TYPES),
                Param(b + "mode", f"fm{s}_{i}", "enum", EQ_MODES),
                Param(b + "slope", f"s{s}_{i}", "enum", EQ_SLOPES),
                Param(b + "solo", f"xs{s}_{i}", "bool"),
                Param(b + "mute", f"xm{s}_{i}", "bool"),
                Param(b + "frequency", f"f{s}_{i}"),
                Param(b + "width", f"w{s}_{i}"),
                Param(b + "gain", f"g{s}_{i}", "db"),
                Param(b + "q", f"q{s}_{i}"),
            ]
    return tuple(params)


def multiband_params():
    params = list(gains()) + list(sidechain_mix()) + [
        Param("compressor-mode", "mode", "enum", ("Classic", "Modern", "Linear Phase"), "Operating mode"),
        Param("envelope-boost", "envb", "enum", ("None", "Pink BT", "Pink MT", "Brown BT", "Brown MT"),
              "Envelope boost"),
        Param("dry", "g_dry", "db", label="Dry", lo=-80, hi=20, step=0.1, unit="dB"),
        Param("wet", "g_wet", "db", label="Wet", lo=-80, hi=20, step=0.1, unit="dB"),
        Param("stereo-split", "ssplit", "bool"),
    ]
    for i in range(8):
        b = f"band{i}/"
        params += [
            Param(b + "enable-band", f"cbe_{i}", "bool"),
            Param(b + "split-frequency", f"sf_{i}"),
            Param(b + "compression-mode", f"cm_{i}", "enum", COMP_MODES),
            Param(b + "compressor-enable", f"ce_{i}", "bool"),
            Param(b + "solo", f"bs_{i}", "bool"),
            Param(b + "mute", f"bm_{i}", "bool"),
            Param(b + "attack-threshold", f"al_{i}", "db"),
            Param(b + "attack-time", f"at_{i}"),
            Param(b + "release-threshold", f"rrl_{i}", "db"),
            Param(b + "release-time", f"rt_{i}"),
            Param(b + "ratio", f"cr_{i}"),
            Param(b + "knee", f"kn_{i}", "db"),
            Param(b + "makeup", f"mk_{i}", "db"),
            Param(b + "boost-threshold", f"bth_{i}", "db"),
            Param(b + "boost-amount", f"bsa_{i}", "db"),
            Param(b + "sidechain-type", f"sce_{i}", "enum", ("Internal", "External", "Link")),
            Param(b + "sidechain-source", f"scs_{i}", "enum", SC_SOURCES),
            Param(b + "stereo-split-source", f"sscs_{i}", "enum", SPLIT_SOURCES),
            Param(b + "sidechain-mode", f"scm_{i}", "enum", SC_MODES),
            Param(b + "sidechain-lookahead", f"sla_{i}"),
            Param(b + "sidechain-reactivity", f"scr_{i}"),
            Param(b + "sidechain-preamp", f"scp_{i}", "db"),
            Param(b + "sidechain-custom-lowcut-filter", f"sclc_{i}", "bool"),
            Param(b + "sidechain-custom-highcut-filter", f"schc_{i}", "bool"),
            Param(b + "sidechain-lowcut-frequency", f"sclf_{i}"),
            Param(b + "sidechain-highcut-frequency", f"schf_{i}"),
        ]
    return tuple(params)


NOT_PACKAGED = "Fedora does not package the {} LV2 plugins this effect needs"

EFFECTS = {
    e.kind: e
    for e in (
        Effect(
            "equalizer", "Equalizer", LSP + "para_equalizer_x32_lr", "lsp-plugins.lv2", "lsp-plugins-lv2",
            params=equalizer_params(), custom=equalizer_controls,
        ),
        Effect(
            "limiter", "Limiter", LSP + "sc_limiter_stereo", "lsp-plugins.lv2", "lsp-plugins-lv2",
            params=gains() + sidechain_mix() + (
                Param("mode", "mode", "enum", ("Herm Thin", "Herm Wide", "Herm Tail", "Herm Duck",
                                               "Exp Thin", "Exp Wide", "Exp Tail", "Exp Duck",
                                               "Line Thin", "Line Wide", "Line Tail", "Line Duck"), "Mode"),
                Param("oversampling", "ovs", "enum", OVERSAMPLING, "Oversampling"),
                Param("dithering", "dith", "enum", ("None", "7bit", "8bit", "11bit", "12bit", "15bit",
                                                    "16bit", "23bit", "24bit"), "Dithering"),
                Param("sidechain-type", "extsc", "enum", ("Internal", "External", "Link")),
                Param("threshold", "th", "db", label="Threshold", lo=-48, hi=0, step=0.1, unit="dB"),
                Param("attack", "at", label="Attack", lo=0.25, hi=20, step=0.01, digits=2, unit="ms"),
                Param("release", "rt", label="Release", lo=0.25, hi=20, step=0.01, digits=2, unit="ms"),
                Param("lookahead", "lk", label="Lookahead", lo=0.1, hi=20, step=0.01, digits=2, unit="ms"),
                Param("stereo-link", "slink", label="Stereo link", hi=100, unit="%", digits=0),
                Param("sidechain-preamp", "scp", "db", label="Sidechain preamp", lo=-80, hi=40, step=0.1,
                      unit="dB"),
                Param("gain-boost", "boost", "bool", label="Gain boost"),
                Param("alr", "alr", "bool", label="Automatic level regulation"),
                Param("alr-attack", "alr_at", label="ALR attack", lo=0.1, hi=200, step=0.1, unit="ms"),
                Param("alr-release", "alr_rt", label="ALR release", lo=10, hi=1000, unit="ms", digits=0),
                Param("alr-knee", "knee", "db", label="ALR knee", lo=-12, hi=12, step=0.1, unit="dB"),
            ),
        ),
        Effect(
            "compressor", "Compressor", LSP + "sc_compressor_stereo", "lsp-plugins.lv2", "lsp-plugins-lv2",
            params=gains() + sidechain_mix() + (
                Param("mode", "cm", "enum", COMP_MODES, "Mode"),
                Param("threshold", "al", "db", label="Threshold", lo=-60, hi=0, step=0.1, unit="dB"),
                Param("ratio", "cr", label="Ratio", lo=1, hi=100, step=0.1, digits=1),
                Param("knee", "kn", "db", label="Knee", lo=-24, hi=0, step=0.1, unit="dB"),
                Param("attack", "at", label="Attack", hi=2000, step=0.1, unit="ms"),
                Param("release", "rt", label="Release", hi=5000, step=1, unit="ms", digits=0),
                Param("release-threshold", "rrl", "db", label="Release threshold", lo=-80.01, hi=0, step=0.1,
                      unit="dB"),
                Param("hold", "hold", label="Hold", hi=1000, unit="ms", digits=0),
                Param("makeup", "mk", "db", label="Makeup", lo=-60, hi=60, step=0.1, unit="dB"),
                Param("boost-threshold", "bth", "db", label="Boost threshold", lo=-120, hi=-60, step=0.1,
                      unit="dB"),
                Param("boost-amount", "bsa", "db", label="Boost amount", lo=-72, hi=72, step=0.1, unit="dB"),
                Param("dry", "cdr", "db", label="Dry", lo=-80.01, hi=20, step=0.1, unit="dB"),
                Param("wet", "cwt", "db", label="Wet", lo=-80.01, hi=20, step=0.1, unit="dB"),
            ) + sidechain("sct", ("Feed-forward", "Feed-back", "External", "Link")) + sidechain_filters(),
        ),
        Effect(
            "gate", "Gate", LSP + "sc_gate_stereo", "lsp-plugins.lv2", "lsp-plugins-lv2",
            params=gains() + sidechain_mix() + (
                Param("curve-threshold", "gt", "db", label="Threshold", lo=-60, hi=0, step=0.1, unit="dB"),
                Param("curve-zone", "gz", "db", label="Zone", lo=-60, hi=0, step=0.1, unit="dB"),
                Param("hysteresis", "gh", "bool", label="Hysteresis"),
                Param("hysteresis-threshold", "ht", "db", label="Hysteresis threshold", lo=-60, hi=0,
                      step=0.1, unit="dB"),
                Param("hysteresis-zone", "hz", "db", label="Hysteresis zone", lo=-60, hi=0, step=0.1, unit="dB"),
                Param("reduction", "gr", "db", label="Reduction", lo=-72, hi=72, step=0.1, unit="dB"),
                Param("attack", "at", label="Attack", hi=2000, step=0.1, unit="ms"),
                Param("release", "rt", label="Release", hi=5000, unit="ms", digits=0),
                Param("hold", "hold", label="Hold", hi=1000, unit="ms", digits=0),
                Param("makeup", "mk", "db", label="Makeup", lo=-60, hi=60, step=0.1, unit="dB"),
                Param("dry", "cdr", "db", label="Dry", lo=-80.01, hi=20, step=0.1, unit="dB"),
                Param("wet", "cwt", "db", label="Wet", lo=-80.01, hi=20, step=0.1, unit="dB"),
            ) + sidechain("sci", ("Internal", "External", "Link")) + sidechain_filters(),
        ),
        Effect(
            "multiband_compressor", "Multiband Compressor", LSP + "sc_mb_compressor_stereo", "lsp-plugins.lv2",
            "lsp-plugins-lv2", params=multiband_params(),
        ),
        Effect(
            "loudness", "Loudness", LSP + "loud_comp_stereo", "lsp-plugins.lv2", "lsp-plugins-lv2",
            params=(
                Param("input-gain", "input", "db", label="Input gain", lo=-36, hi=36, step=0.1, unit="dB"),
                Param("std", "std", "enum", ("Flat", "ISO226-2003", "Fletcher-Munson", "Robinson-Dadson",
                                             "ISO226-2023"), "Standard"),
                Param("fft", "fft", "enum", ("256", "512", "1024", "2048", "4096", "8192", "16384"), "FFT size"),
                Param("volume", "volume", label="Volume", lo=-83, hi=7, step=0.1, unit="dB"),
                Param("clipping", "hclip", "bool", label="Clipping"),
                Param("clipping-range", "hcrange", label="Clipping range", hi=24, step=0.1, unit="dB"),
            ),
        ),
        Effect(
            "autogain", "Autogain", LSP + "autogain_stereo", "lsp-plugins.lv2", "lsp-plugins-lv2",
            params=(
                Param("target", "level", label="Target", lo=-60, hi=0, step=0.1, unit="LUFS"),
                Param("silence-threshold", "silence", label="Silence threshold", lo=-84, hi=-36, step=0.1,
                      unit="dB"),
                Param("maximum-gain", "max_amp", label="Maximum gain", hi=108, step=0.1, unit="dB"),
            ),
        ),
        Effect(
            "maximizer", "Maximizer", "urn:zamaudio:ZaMaximX2", "ZaMaximX2.lv2", "lv2-zam-plugins",
            ports=("lv2_audio_in_1", "lv2_audio_in_2", "lv2_audio_out_1", "lv2_audio_out_2"),
            params=(
                Param("threshold", "thresh", label="Threshold", lo=-30, hi=0, step=0.1, unit="dB"),
                Param("ceiling", "gain", label="Ceiling", lo=-20, hi=20, step=0.1, unit="dB"),
                Param("release", "rel", label="Release", lo=1, hi=100, step=0.1, unit="ms"),
            ),
        ),
        Effect(
            "convolver", "Convolver", builtin=True, ports=(),
            params=(
                Param("input-gain", "", label="Input gain", lo=-36, hi=36, step=0.1, unit="dB"),
                Param("output-gain", "", label="Output gain", lo=-36, hi=36, step=0.1, unit="dB"),
            ),
        ),
    )
}

for _kind, _title, _missing in (
    ("bass_enhancer", "Bass Enhancer", NOT_PACKAGED.format("Calf")),
    ("exciter", "Exciter", NOT_PACKAGED.format("Calf")),
    ("stereo_tools", "Stereo Tools", NOT_PACKAGED.format("Calf")),
    ("reverb", "Reverberation", NOT_PACKAGED.format("Calf")),
    ("deesser", "Deesser", NOT_PACKAGED.format("Calf")),
    ("bass_loudness", "Bass Loudness", NOT_PACKAGED.format("MDA")),
    ("crossfeed", "Crossfeed", "Fedora packages no bs2b plugin for this effect"),
    ("crystalizer", "Crystalizer", "This effect is built into Easy Effects and has no plugin"),
    ("delay", "Delay", "Not supported yet"),
    ("filter", "Filter", "Not supported yet"),
    ("expander", "Expander", "Not supported yet"),
    ("multiband_gate", "Multiband Gate", "Not supported yet"),
    ("pitch", "Pitch", "Not supported yet"),
    ("level_meter", "Level Meter", "Not supported yet"),
    ("rnnoise", "Noise Reduction", "Not supported yet"),
    ("deepfilternet", "Deep Noise Remover", "Not supported yet"),
    ("speex", "Speech Processor", "Not supported yet"),
    ("echo_canceller", "Echo Canceller", "Not supported yet"),
):
    EFFECTS[_kind] = Effect(_kind, _title, missing=_missing)


def effect(kind):
    return EFFECTS.get(kind) or Effect(kind, kind.replace("_", " ").title(), missing="Unknown effect")
