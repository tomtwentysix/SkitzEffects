# Distortion Check Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A dialog on the Effects page that monitors every stage of the running chain for overs and sharp level drops, then turns down each stage that went over, for the session or saved into the preset.

**Architecture:** The planning logic (stages, readings, cuts, drops, applying cuts to a preset copy) is a GTK-free module, `skitz_effects/check.py`, tested with made-up readings. A `Check` object in the same module taps each stage's output stream with `levels.Tap` and fills the readings. `Pipeline` holds session-only cuts ("trims") that it applies whenever it builds the chain or sends live controls. A new `ui/check.py` dialog drives the flow.

**Tech Stack:** Python 3, PyGObject (GTK 4, libadwaita), numpy, PipeWire (`pw-record` taps, `pw-link`), pytest.

**Spec:** `docs/superpowers/specs/2026-11-22-distortion-check-design.md`

## Global Constraints

- Cuts only ever lower a gain; nothing is raised. Volume drops are flagged, never fixed.
- Each stage is cut after its processing: `output-gain` for equaliser, limiter, compressor, expander, gate, multiband compressor, Bass Loudness, Deep Noise Remover and convolver; `volume` for Loudness; `ceiling` for Maximizer; `target` for Autogain; every channel's surround level for the Surround Downmix.
- `needed = over + 0.5 - cut_so_far`; cuts round up (away from zero) to 0.1 dB for effects and 0.5 dB for surround levels.
- A cut that does not fit its control's range applies what fits and carries the rest to the next stage; any remainder at the end of the chain is reported.
- Drops are flagged when a stage's output is more than 6 dB below its input, after subtracting `20 * log10(graph.HRIR_HEADROOM[layout])` for the Surround Downmix. Only ticks where the chain's input is above -60 dBFS count.
- "Fix settings" writes nothing to disk; its cuts survive chain restarts and are dropped on loading or creating a preset, or quitting. "Fix and save preset" folds them into the preset and the surround levels and saves both.
- Code style: no section banners, no docstrings restating names, comments only for what the code cannot show (CLAUDE.md). UI copy is formal.
- GUI test runs: give the app a private `XDG_RUNTIME_DIR` (`rt=$(mktemp -d) && chmod 700 "$rt"`, removed afterwards) when running it headless.

## Review Focus

- Nothing plays during the run: every reading is empty. The summary should say nothing was measured, plan no cuts and flag no drops, not divide by zero.
- The chain is rebuilt mid-run (preset edited, device changed): the check stops and says so instead of reporting readings from taps that no longer match the stages.
- The same effect twice (`equalizer#0`, `equalizer#1`): cuts and readings stay separate per effect id.
- A cut larger than a control's room (output gain already near -36 dB): what fits is applied, the rest is carried, and the leftover is reported.
- Loading another preset after "Fix settings": the trims are dropped and never written into the newly loaded preset.

---

### Task 1: Energy accumulation in the meter tap

**Files:**
- Modify: `skitz_effects/levels.py` (class `Tap`)
- Test: `tests/test_levels.py`

**Interfaces:**
- Produces: `Tap.take_energy() -> tuple[float, int]`: the sum of squares of the first two channels and the frame count since the last call, then resets both. `Tap._on_data` accumulates them alongside `peak`.

- [ ] **Step 1: Write the failing test** `test_tap_energy_counts_the_first_two_channels_and_resets`. Build a `Tap` with `object.__new__(levels.Tap)`, set `channels = 8`, `peak = np.zeros(8)`, `buffer = np.zeros((levels.FFT, 8))`, `_partial = b""`, `energy = 0.0`, `frames = 0`, `last = 0.0`, and feed it through a pipe so `_on_data` reads real bytes: 100 frames where FL = 0.5, FR = 0.5 and every other channel = 1.0. Assert `take_energy() == pytest.approx((50.0, 100))`, then `take_energy() == (0.0, 0)`.
- [ ] **Step 2: Run it and see it fail.** `pytest tests/test_levels.py -k energy -v` → FAIL (`take_energy` missing).
- [ ] **Step 3: Implement** the accumulation in `Tap.__init__` (`self.energy = 0.0`, `self.frames = 0`), `_on_data` and `take_energy()`.
- [ ] **Step 4: Run all tests.** `pytest -q` → all pass.
- [ ] **Step 5: Commit** "Count each meter tap's energy, for level comparisons".

### Task 2: Planning the cuts and flagging drops

**Files:**
- Create: `skitz_effects/check.py`
- Test: `tests/test_check.py`

**Interfaces:**
- Produces:

```python
@dataclass(frozen=True)
class Stage:
    key: str      # "surround", or an effect id such as "equalizer#0"
    title: str
    kind: str     # "surround", or the effect kind
    stream: str   # node name of the stage's output stream

@dataclass
class Reading:
    peak: float = 0.0    # largest sample seen, linear
    overs: int = 0       # ticks whose peak went over 1.0
    energy: float = 0.0  # sum of squares of FL and FR over ticks where the chain's input was active
    frames: int = 0

@dataclass(frozen=True)
class Cut:
    key: str
    control: str  # the preset key cut, or "surround"
    db: float     # negative

def cut_target(kind: str) -> tuple[str, float, float] | None   # (control, lowest value, step)
def plan_cuts(stages: list[Stage], readings: dict[str, Reading], room: dict[str, float]) -> tuple[list[Cut], float]
def level_change(before: Reading, after: Reading) -> float | None   # dB; None without frames on both
def drop_flagged(stage: Stage, change: float | None, layout: str) -> bool
```

`room[key]` is how far that stage's control can still go down, in dB (positive). `plan_cuts` returns the cuts and the dB it could not apply anywhere.

- [ ] **Step 1: Write the failing tests** in `tests/test_check.py`, with `S = lambda key, kind: check.Stage(key, key, kind, key)` and `peak_db = lambda db: check.Reading(peak=10 ** (db / 20), overs=1)`:
  - `test_cut_targets`: `cut_target("equalizer") == ("output-gain", -36.0, 0.1)`, `cut_target("loudness")[0] == "volume"`, `cut_target("maximizer")[:2] == ("ceiling", -20.0)`, `cut_target("autogain")[:2] == ("target", -60.0)`, `cut_target("surround") == ("surround", -12.0, 0.5)`.
  - `test_each_over_is_cut_by_its_peak_plus_margin_minus_earlier_cuts`: stages surround, `equalizer#0`, `bass_loudness#0`; readings surround 0 dB peak (no over), eq +4.1 dB, bass +9.8 dB; ample room. Cuts are `[Cut("equalizer#0", "output-gain", -4.6), Cut("bass_loudness#0", "output-gain", -5.7)]` (`pytest.approx` on `db`), leftover 0.
  - `test_an_earlier_cut_can_cover_a_later_over`: eq +6.0, bass +3.0 → one cut, eq -6.5.
  - `test_surround_cuts_round_up_to_half_a_db`: surround +1.2 → `Cut("surround", "surround", -2.0)`.
  - `test_a_cut_past_its_range_carries_on`: eq +10 with room 4.0, bass +2 with ample room → eq -4.0, bass -6.5, leftover 0. Same with only eq in the chain → leftover `pytest.approx(6.5)`.
  - `test_the_same_effect_twice_is_cut_separately`: `equalizer#0` +2, `equalizer#1` +5 → keys `equalizer#0` (-2.5) and `equalizer#1` (-2.5).
  - `test_nothing_measured_plans_nothing`: all readings `Reading()` → `([], 0.0)`; `level_change(Reading(), Reading()) is None`; `drop_flagged(stage, None, "7.1") is False`.
  - `test_drops`: `level_change(Reading(energy=1.0, frames=10), Reading(energy=0.01, frames=10)) == pytest.approx(-20.0)`; an effect stage at -7 dB is flagged, at -5 dB not; the surround stage at -15 dB with layout "7.1" is not flagged (-9.9 headroom), at -17 dB it is.
- [ ] **Step 2: Run them and see them fail.** `pytest tests/test_check.py -v` → FAIL (module missing).
- [ ] **Step 3: Implement** the dataclasses and functions in `skitz_effects/check.py`. `cut_target` takes the lowest value from the effect's own `Param.lo` in `plugins.EFFECTS` (surround: -12.0, step 0.5); `over` is `20 * log10(peak)` when `overs > 0`. The algorithm:

```python
cut_so_far, carry = 0.0, 0.0
for stage in stages:
    needed = carry
    if readings[stage.key].overs:
        needed = max(needed, over_db + 0.5 - cut_so_far)
    if needed <= 0: continue
    needed = ceil(needed / step) * step       # with a small epsilon so 4.6 stays 4.6
    applied = min(needed, room[stage.key])
    if applied > 0: cuts.append(Cut(stage.key, control, -applied)); cut_so_far += applied
    carry = needed - applied
return cuts, carry
```

- [ ] **Step 4: Run all tests.** `pytest -q` → all pass.
- [ ] **Step 5: Commit** "Plan per-stage cuts for overs, and flag sharp level drops".

### Task 3: Applying cuts to a preset and the surround levels

**Files:**
- Modify: `skitz_effects/check.py`
- Test: `tests/test_check.py`

**Interfaces:**
- Consumes: `Cut` from Task 2; `presets.Preset` (`settings(effect_id)`, `section`, `save()`).
- Produces:

```python
def trimmed(preset: presets.Preset | None, cuts: list[Cut]) -> presets.Preset | None   # a deep copy with the cuts added
def trimmed_levels(layout: str, levels: dict, cuts: list[Cut]) -> dict                 # every channel of the layout, cut
def fold(preset: presets.Preset, cuts: list[Cut]) -> None                              # adds the cuts into the preset itself
def room(preset: presets.Preset | None, stages: list[Stage], layout: str, levels: dict) -> dict[str, float]
```

- [ ] **Step 1: Write the failing tests** (`ee_root` fixture, "Dali iO6" preset, which holds `bass_loudness#0` with `output-gain` -3.0):
  - `test_trimmed_leaves_the_preset_alone`: `t = check.trimmed(p, [Cut("bass_loudness#0", "output-gain", -2.0)])`; `t.settings("bass_loudness#0")["output-gain"] == pytest.approx(-5.0)` and `p.settings(...)["output-gain"] == -3.0`; `check.trimmed(None, cuts) is None`.
  - `test_fold_writes_into_the_preset`: after `fold`, `p.settings("bass_loudness#0")["output-gain"] == pytest.approx(-5.0)`.
  - `test_trimmed_levels`: `trimmed_levels("5.1", {"FC": 3.0}, [Cut("surround", "surround", -2.0)]) == {"FL": -2.0, "FR": -2.0, "FC": 1.0, "LFE": -2.0, "RL": -2.0, "RR": -2.0}`; without a surround cut it returns the levels unchanged.
  - `test_room`: for the Dali bass stage, room is `-3.0 - -36.0 == 33.0`; for surround with levels `{"FC": -10.0}` in "7.1", room is `2.0` (the lowest channel decides).
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement** the four functions; `trimmed` uses `copy.deepcopy`.
- [ ] **Step 4: Run all tests.** `pytest -q` → all pass.
- [ ] **Step 5: Commit** "Apply planned cuts to a preset copy, the preset, or the surround levels".

### Task 4: Session trims in the pipeline

**Files:**
- Modify: `skitz_effects/controller.py` (class `Pipeline`)

**Interfaces:**
- Consumes: `check.trimmed`, `check.trimmed_levels`, `check.fold`, `check.Cut`.
- Produces on `Pipeline`:
  - `trims: list[Cut]`, empty at start.
  - `fix(cuts: list[Cut], save: bool) -> None`: with `save=False`, adds the cuts to `trims`; with `save=True`, folds `trims + cuts` into the preset (then `_queue_save()`) and into `settings.surround_levels` (then `settings.save()`), and clears `trims`. Either way it then sends the new values live where it can and queues a rebuild only when a cut touches a convolver.
  - `stages() -> list[check.Stage]`: the running chain's stages from `steps()`, mapping each tap back to its effect id through `graph.node_name` over `preset.order`.

- [ ] **Step 1:** In `_build`, pass `check.trimmed(self.preset, self.trims)` and `check.trimmed_levels(s.layout, s.surround_levels, self.trims)` to `graph.build`. In `changed()`, compute `graph.live_controls` from the trimmed preset's settings. In `set_surround_level`, send `graph.level_controls` of the trimmed levels.
- [ ] **Step 2:** Clear `self.trims` in `load_preset` and `new_preset`.
- [ ] **Step 3:** Add `fix` and `stages` as above.
- [ ] **Step 4: Verify.** `pytest -q` → all pass. Then run the dev app (`./run-dev.sh`), and in a Python shell or a temporary debug action call `pipeline.fix([Cut("equalizer#0", "output-gain", -6.0)], False)`: the equaliser's `g_out` in `pw-dump` drops by 6 dB, the preset file is unchanged, and after `pipeline.restart()` the cut is still there. Loading another preset drops it.
- [ ] **Step 5: Commit** "Hold session-only cuts in the pipeline and apply them to every build".

### Task 5: The monitoring check

**Files:**
- Modify: `skitz_effects/check.py`
- Test: `tests/test_check.py`

**Interfaces:**
- Consumes: `levels.Tap`, `levels.TapSpec`, `Tap.take_peak()`, `Tap.take_energy()` (Task 1); `Pipeline.stages()` (Task 4); the "before" tap spec, made the way `Meters._ends` makes it for the pipeline's direction.
- Produces:

```python
class Check(GObject.Object):
    # signals: "updated" (), "aborted" (str: the reason)
    def __init__(self, pipeline): ...
    stages: list[Stage]
    before: Reading               # the chain's input
    readings: dict[str, Reading]  # by stage key
    elapsed: float                # seconds
    def start(self) -> None
    def stop(self) -> None
def tick(before: Reading, readings: dict[str, Reading], before_sample: tuple[float, float, int],
         samples: dict[str, tuple[float, float, int]]) -> None
```

`tick` is the pure part: each sample is `(peak, energy, frames)` taken from a tap since the last tick. It raises each reading's `peak`, counts an over when the sample's peak is over 1.0, and adds energy and frames to every reading (and to `before`) only when the chain's input sample is above -60 dBFS RMS.

- [ ] **Step 1: Write the failing tests:**
  - `test_tick_counts_overs_and_keeps_the_largest_peak`: two ticks with peaks 1.5 then 1.2 → `peak == 1.5`, `overs == 2`.
  - `test_tick_ignores_energy_while_the_input_is_quiet`: an input sample at -70 dBFS RMS adds no energy or frames anywhere; one at -20 dBFS adds both.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement** `tick` and `Check`. `Check.start` opens a passive `Tap` per stage (`TapSpec(stage.stream, False, False, "stereo", linked=True)`) and links it with `pw.link(stage.stream, tap.name)` once the tap's node exists, the way `Meters._sync` does, plus one for the input; it ticks every 33 ms with `GLib.timeout_add`. It listens for the pipeline's `state-changed` and `preset-changed`, and if `pipeline.stages()` no longer equals the stages it started with, it stops and emits `aborted("The effects changed during the check")`. `stop` stops and removes every tap.
- [ ] **Step 4: Run all tests.** `pytest -q` → all pass.
- [ ] **Step 5: Commit** "Monitor every stage of the chain for overs and level".

### Task 6: The dialog and its button

**Files:**
- Create: `skitz_effects/ui/check.py`
- Modify: `skitz_effects/ui/effects.py` (the top bar beside `preset_button`)

**Interfaces:**
- Consumes: `check.Check`, `plan_cuts`, `room`, `level_change`, `drop_flagged` (Tasks 2, 3, 5); `Pipeline.fix`, `Pipeline.stages` (Task 4).
- Produces: `CheckDialog(Adw.Dialog)`, constructed as `CheckDialog(pipeline)` and shown with `.present(parent)`.

- [ ] **Step 1:** Add a flat icon button, tooltip "Check for Distortion", to the right of `preset_button` in `EffectsView`. It is insensitive while no preset is loaded or the chain is not running, and opens `CheckDialog(self.pipeline)`.
- [ ] **Step 2:** Build the monitoring view: the title "Distortion Check" with the preset's name, an elapsed time, and one `Adw.ActionRow` per stage whose subtitle reads "No overs" or "Over by up to 4.1 dB, 37 times", updated on `updated`. A "Stop" button ends it. On `aborted`, show the reason with a "Run Again" button.
- [ ] **Step 3:** Build the summary: per stage, overs (as above), the level change ("-9.9 dB, headroom, expected" for the surround stage within its headroom; "Drops 23.4 dB" with a warning icon when `drop_flagged`) and the planned cut ("Output gain -4.6 dB", "Surround levels -2.0 dB", "Ceiling -1.0 dB", or "Target -1.0 LUFS, applied gradually" for Autogain). Overs at the chain's input show as one line: "Apps are sending audio over 0 dB". A leftover above 0 shows "Could not lower the preset by a further 6.5 dB". With no frames measured anywhere, show "Nothing was measured. Play some audio while the check runs." and only "Run Again" and "Close".
- [ ] **Step 4:** The bottom buttons: "Fix Settings" (`pipeline.fix(cuts, False)`), "Fix and Save Preset" (`pipeline.fix(cuts, True)`), "Cancel" (closes). After a fix, replace them with "Run Again" (starts a new `Check` in the same dialog) and "Close". With no cuts planned, show only "Run Again" and "Close".
- [ ] **Step 5: Verify in the running app.** `./run-dev.sh`, with the installed copy quit. Load a preset with an equaliser boosted so it clips, play audio, run the check: the equaliser shows overs, and the planned cut matches `plan_cuts`. Choose "Fix Settings", then "Run Again": no overs, preset file unchanged (`git diff` on a copy, or its mtime). Run it again and choose "Fix and Save Preset": the preset file's `output-gain` changes. Edit an effect during a run: the check aborts with its message.
- [ ] **Step 6: Commit** "Add a distortion check to the Effects page".
