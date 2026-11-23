"""Tooltips for every setting, by the key it has in an Easy Effects preset."""

SHARED = {
    "input-gain": "Gain applied to the signal before the effect processes it",
    "output-gain": "Gain applied to the signal after the effect, the last thing it does before the next effect",
    "mode": "How the effect processes the signal",
    "threshold": "Level above which the effect starts to act",
    "ratio": "How strongly the level is changed past the threshold: 4 means 4 dB in becomes 1 dB out",
    "knee": "How gradually the effect starts acting around the threshold; lower values give a softer transition",
    "attack": "How quickly the effect responds once the signal crosses the threshold",
    "release": "How quickly the effect lets go once the signal falls back",
    "release-threshold": "Level, relative to the threshold, at which the release starts; the lowest value turns it off",
    "hold": "How long the effect keeps acting after the signal falls back, before the release starts",
    "makeup": "Gain added after processing to make up for the level the effect removed",
    "dry": "Level of the unprocessed signal mixed into the output",
    "wet": "Level of the processed signal mixed into the output",
    "sidechain/type": "Which signal the effect listens to when deciding how much to act",
    "sidechain/mode": "How the level of the listened-to signal is measured: Peak follows every peak, RMS averages, "
                      "LPF smooths with a low-pass filter, SMA uses a simple moving average",
    "sidechain/source": "Which channels of the listened-to signal are measured: the middle, the sides, one "
                        "channel, or the quieter or louder of the two",
    "sidechain/lookahead": "Delays the audio so the effect can react to peaks before they arrive, at the cost of "
                           "that much latency",
    "sidechain/reactivity": "Time over which the level is measured; shorter reacts faster, longer is smoother",
    "sidechain/preamp": "Gain applied to the listened-to signal only, making the effect act as if the audio "
                        "were louder or quieter",
    "hpf-mode": "Filters low frequencies out of the listened-to signal, so bass does not trigger the effect",
    "hpf-frequency": "Frequency below which the listened-to signal is filtered out",
    "lpf-mode": "Filters high frequencies out of the listened-to signal, so treble does not trigger the effect",
    "lpf-frequency": "Frequency above which the listened-to signal is filtered out",
}

EFFECTS = {
    "equalizer": {
        "mode": "IIR filters work like analogue ones with no latency; FIR and FFT keep the phase linear at the "
                "cost of latency; SPM processes in the frequency domain",
        "balance": "Shifts the level between the left and right channels",
        "num-bands": "How many bands the equaliser uses",
        "split-channels": "Gives the left and right channels separate band settings",
    },
    "equalizer_band": {
        "type": "The filter shape: Bell lifts or cuts around the frequency, shelves lift or cut everything "
                "above or below it, passes remove everything beyond it",
        "frequency": "Centre or corner frequency of the band",
        "gain": "How much the band lifts or cuts",
        "q": "Width of the band: higher values affect a narrower range of frequencies",
        "slope": "Steepness of a shelf or pass filter: each step doubles it",
        "mode": "The filter design: RLC is analogue-like, BWC is Butterworth, LRX is Linkwitz-Riley, APO follows "
                "the Audio EQ Cookbook; BT and MT are two ways of converting them to digital, MT matching the "
                "analogue response more closely near the top of the range",
        "mute": "Turns this band off",
        "solo": "Plays only this band, to hear what it affects",
    },
    "limiter": {
        "mode": "Shape of the gain reduction curve: Herm, Exp and Line set its curve; Thin, Wide, Tail and Duck "
                "set how long it lasts around each peak",
        "oversampling": "Processes at a higher rate to catch peaks between samples, at the cost of CPU",
        "dithering": "Adds low-level noise to mask distortion when the output is reduced to that many bits",
        "threshold": "Highest level the output may reach",
        "attack": "How long the limiter takes to bring the gain down ahead of a peak",
        "release": "How long the limiter takes to bring the gain back up after a peak",
        "lookahead": "How far ahead the limiter looks for peaks, adding that much latency",
        "stereo-link": "How much the two channels share their gain reduction: 100% keeps the stereo image steady",
        "sidechain-preamp": "Gain applied to the signal the limiter measures, making it act as if the audio were "
                            "louder or quieter",
        "gain-boost": "Raises the output by the amount the threshold is below 0 dB, so peaks still reach full scale",
        "alr": "Automatic level regulation: gently lowers the level ahead of the limiter, so it has to work less "
               "hard on sustained loud passages",
        "alr-attack": "How quickly automatic level regulation lowers the level",
        "alr-release": "How quickly automatic level regulation lets the level recover",
        "alr-knee": "How far below the threshold automatic level regulation starts acting",
    },
    "compressor": {
        "mode": "Down lowers loud passages, Up raises quiet ones, Boost raises quiet ones while keeping loud "
                "ones as they are",
        "threshold": "Level above which the compressor starts lowering the signal",
        "boost-threshold": "In Up and Boost modes, level below which quiet passages are no longer raised",
        "boost-amount": "In Up and Boost modes, the most that quiet passages are raised",
        "sidechain/type": "Feed-forward listens to the input, Feed-back to the output, External to another "
                          "signal, Link to a linked effect",
    },
    "expander": {
        "mode": "Down lowers quiet passages further, Up raises loud passages further",
        "threshold": "Level below which (in Down mode) or above which (in Up mode) the expander acts",
        "sidechain/type": "Internal listens to the input, External to another signal, Link to a linked effect",
    },
    "gate": {
        "curve-threshold": "Level above which the gate opens",
        "curve-zone": "Range below the threshold over which the gate closes gradually rather than at once",
        "hysteresis": "Uses a separate, lower threshold for closing, so the gate does not flutter around one level",
        "hysteresis-threshold": "Level below which an open gate closes",
        "hysteresis-zone": "Range below the closing threshold over which the gate closes gradually",
        "reduction": "How much the signal is lowered while the gate is closed",
        "sidechain/type": "Internal listens to the input, External to another signal, Link to a linked effect",
    },
    "multiband_compressor": {
        "compressor-mode": "Classic and Modern split the bands with different crossover filters; Linear Phase "
                           "keeps the phase intact at the cost of latency",
        "envelope-boost": "Tilts the level detection towards the treble, so bands react to how loud they sound "
                          "rather than their raw level",
    },
    "loudness": {
        "input-gain": "Gain applied to the signal before the loudness compensation",
        "std": "The equal-loudness curves used to work out how much bass and treble to add at low volume",
        "fft": "Resolution of the compensation filter: larger is more precise at low frequencies but adds latency",
        "volume": "The listening volume to compensate for; lower values add more bass and treble to make up for "
                  "how hearing loses them at low volume, and also lower the output",
        "clipping": "Limits the output so it cannot go over the clipping range",
        "clipping-range": "Level the output is limited to when clipping is on",
    },
    "autogain": {
        "target": "Loudness the output is kept at",
        "silence-threshold": "Loudness below which the input counts as silence, so the gain is not raised during it",
        "maximum-gain": "The most the effect may raise the level",
    },
    "maximizer": {
        "threshold": "Level above which peaks are limited; lowering it makes everything louder and denser",
        "ceiling": "Highest level the output may reach",
        "release": "How quickly the gain recovers after a peak",
    },
    "bass_loudness": {
        "loudness": "How much bass is added to make up for quiet listening: -6 dB leaves the sound flat, higher "
                    "values add bass (about +34 dB at 60 Hz at the top), lower values take it away",
        "output": "Level after the bass correction: -6 dB leaves the level unchanged, and the gain rises steeply "
                  "above it, to about +10 dB at the top of the slider",
    },
    "deepfilternet": {
        "attenuation-limit": "The most the noise may be lowered; 100 dB removes as much as it can, lower values "
                             "leave some noise in and sound more natural",
        "min-processing-threshold": "Below this signal-to-noise ratio, a moment is treated as noise only and "
                                    "lowered fully",
        "max-erb-processing-threshold": "Above this signal-to-noise ratio, the first stage of noise removal is "
                                        "skipped as the speech is already clean",
        "max-df-processing-threshold": "Above this signal-to-noise ratio, the second, finer stage of noise "
                                       "removal is skipped",
        "min-processing-buffer": "Frames buffered before processing; more makes it steadier under load but "
                                 "adds latency",
        "post-filter-beta": "Strength of an extra filter that removes noise left between words; 0 turns it off",
    },
    "convolver": {
        "kernel-name": "The impulse response the signal is convolved with, such as a room or a speaker correction",
    },
}


def text(kind, key):
    return EFFECTS.get(kind, {}).get(key) or SHARED.get(key, "")
