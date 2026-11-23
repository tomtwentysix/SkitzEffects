"""Maps a setting's value to a slider position from 0 to 1 and back.

A setting that starts at or above zero and spans a hundredfold or more, such as a frequency, a time or a
ratio, gets a logarithmic slider so each octave or decade takes the same length of track. A range that
starts at zero is shifted by one unit so its log can reach zero.
"""

import math


def _offset(param):
    return 0.0 if param.lo > 0 else 1.0


def logarithmic(param):
    if param.lo < 0:
        return False
    off = _offset(param)
    return (param.hi + off) / (param.lo + off) >= 100


def position(param, value):
    value = min(max(float(value), param.lo), param.hi)
    if logarithmic(param):
        off = _offset(param)
        return math.log((value + off) / (param.lo + off)) / math.log((param.hi + off) / (param.lo + off))
    return (value - param.lo) / (param.hi - param.lo)


def value_at(param, pos):
    pos = min(max(pos, 0.0), 1.0)
    if logarithmic(param):
        off = _offset(param)
        value = (param.lo + off) * ((param.hi + off) / (param.lo + off)) ** pos - off
    else:
        value = param.lo + pos * (param.hi - param.lo)
    value = param.lo + round((value - param.lo) / param.step) * param.step
    return round(min(max(value, param.lo), param.hi), max(param.digits, 2) + 2)
