from dataclasses import dataclass
from math import ceil, log10

from . import plugins
from .graph import HRIR_HEADROOM

CUT_MARGIN_DB = 0.5
DROP_DB = -6.0
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
        applied = min(needed, room[stage.key])
        if applied > 0:
            cuts.append(Cut(stage.key, control, -applied))
            cut_so_far += applied
        carry = needed - applied
    return cuts, carry


def level_change(before, after):
    if not before.frames or not after.frames or before.energy <= 0 or after.energy <= 0:
        return None
    return 10 * log10(after.energy / before.energy)


def drop_flagged(stage, change, layout):
    if change is None:
        return False
    limit = DROP_DB
    if stage.kind == "surround":
        limit += 20 * log10(HRIR_HEADROOM.get(layout, 1.0))
    return change < limit
