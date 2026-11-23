import copy
from dataclasses import dataclass
from math import ceil, log10

from . import plugins
from .config import LAYOUTS
from .graph import HRIR_HEADROOM

CUT_MARGIN_DB = 0.5
DROP_DB = -6.0
SILENCE_DB = -120.0
SURROUND_CUT = ("surround", -12.0, 0.5)
CUT_CONTROLS = {"output-gain", "volume", "ceiling", "target"}


@dataclass(frozen=True)
class Stage:
    key: str
    title: str
    kind: str
    stream: str


@dataclass
class Reading:
    peak: float = 0.0
    overs: int = 0
    energy: float = 0.0
    frames: int = 0


@dataclass(frozen=True)
class Cut:
    key: str
    control: str
    db: float


def cut_target(kind):
    """(control, lowest value, step), or None when the kind has nothing to cut."""
    if kind == "surround":
        return SURROUND_CUT
    effect = plugins.EFFECTS.get(kind)
    for param in effect.params if effect else ():
        if param.key in CUT_CONTROLS:
            return param.key, float(param.lo), float(param.step)
    return None


def plan_cuts(stages, readings, room):
    """Returns (cuts, dB that no stage had room to apply)."""
    cuts, cut_so_far, carry = [], 0.0, 0.0
    for stage in stages:
        target = cut_target(stage.kind)
        if target is None:
            continue
        control, _, step = target
        reading = readings[stage.key]
        needed = carry
        if reading.overs:
            over_db = 20 * log10(reading.peak)
            needed = max(needed, over_db + CUT_MARGIN_DB - cut_so_far)
        if needed <= 0:
            continue
        needed = round(ceil(needed / step - 1e-6) * step, 6)
        applied = min(needed, max(room[stage.key], 0.0))
        if applied > 0:
            cuts.append(Cut(stage.key, control, -applied))
            cut_so_far += applied
        carry = needed - applied
    return cuts, carry


def level_change(before, after):
    if not before.frames or not after.frames or before.energy <= 0:
        return None
    if after.energy <= 0:
        return SILENCE_DB
    return max(SILENCE_DB, 10 * log10((after.energy / after.frames) / (before.energy / before.frames)))


def drop_flagged(stage, change, layout):
    if change is None:
        return False
    limit = DROP_DB
    if stage.kind == "surround":
        limit += 20 * log10(HRIR_HEADROOM.get(layout, 1.0))
    return change < limit


def trimmed_levels(layout, levels, cuts):
    cut = sum(c.db for c in cuts if c.control == "surround")
    if not cut:
        return levels
    return {ch: levels.get(ch, 0.0) + cut for ch in LAYOUTS[layout]}


def fold(preset, cuts):
    for cut in cuts:
        if cut.control != "surround":
            settings = preset.settings(cut.key)
            settings[cut.control] = round(settings[cut.control] + cut.db, 6)


def room(preset, stages, layout, levels):
    result = {}
    for stage in stages:
        target = cut_target(stage.kind)
        if target is None:
            result[stage.key] = 0.0
        elif stage.kind == "surround":
            result[stage.key] = min(levels.get(ch, 0.0) for ch in LAYOUTS[layout]) - target[1]
        elif preset is None:
            result[stage.key] = 0.0
        else:
            result[stage.key] = preset.settings(stage.key)[target[0]] - target[1]
    return result
