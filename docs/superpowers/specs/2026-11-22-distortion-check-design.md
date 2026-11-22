# Distortion check

## Intent

A one-click way to make a preset safe from distortion without understanding gain staging. The user
starts a check, plays something typical (a game, music) for as long as they like, stops it, and gets
a summary of where the signal went over 0 dB and where the level dropped sharply. They can then have
Skitz Effects fix the overs, for the session or saved into the preset, and run the check again.

It came out of chasing a preset that distorted through the surround downmix and lost 23 dB in Bass
Loudness's Link mode: problems that were only found by tapping every stage by hand.

## Goals

- Monitor every stage of the running chain while the user plays audio, and log, per stage, how often
  and by how much its output went over 0 dBFS.
- Flag any stage whose output is much quieter than its input.
- On request, turn down each stage that went over by enough to stop it, then offer to check again.
- Work with Easy Effects presets: fixes go into the preset's existing fields, so Easy Effects reads
  the fixed preset unchanged.

## Non-goals

- Raising any gain. A quieter result is acceptable; the user makes it up with their normal volume.
- Fixing volume drops. They are flagged only, because a drop usually has a cause (such as a setting
  like Link) that a gain boost would hide.
- Continuous automatic gain while listening. The check is something the user runs, not a process that
  keeps adjusting.
- Keeping loudness the same after a fix, for example by adding make-up gain at the limiter.

## Anti-goals

- Gain that moves on its own while the user listens. That is audible pumping, the opposite of a fix.
- Changing a stage that did not go over.
- Writing anything to the preset when the user chose Cancel or "Fix settings".

## Constraints

- Every stage of a chain is its own filter-chain, joined by streams (`graph.staged`, `graph.modules`),
  so each stage's output stream can be tapped. The meters already do this (`levels.Tap`, `TapSpec`
  with `linked=True`), and tapping needs no restart.
- Audio between stages is 32-bit float, so a stage going over 0 dB does not distort by itself. It
  distorts where it is converted for the device, or where a later effect reacts to level (limiter,
  compressor, gate). The check still treats every over as something to fix, because the user asked
  for overs at every stage and a fixed preset should stay under 0 dB throughout.
- Effect gains change live through `pw.set_controls` without a restart (`graph.live_controls`). The
  surround levels change live through `graph.level_controls`.
- Edits to a preset through `Pipeline.changed` are saved 500 ms later, so "Fix settings" cannot go
  through that path.
- Taps record at 48 kHz, the same as the graph (`clock.allowed-rates` is 48000 on the user's system).

## Approaches

1. **Turn down each stage that clips** (chosen). Go through the stages in chain order. Each stage that
   went over is turned down by its worst over plus a margin, minus any cuts already made earlier in
   the chain. It only touches what the log blamed, the summary reads line for line, and it uses the
   presets' existing gain fields.
2. **One cut at the start of the chain.** A single cut before the first stage, by the worst over
   anywhere. Simplest, and it keeps every stage's settings, but it cuts more than needed and feeds a
   quieter signal into the limiter and compressors, which changes how the preset sounds, not just how
   loud it is.
3. **Continuous automatic gain** was ruled out: the user wants a check they run, not gain that moves.

The user chose 1.

## Design

### Where it lives

A "Check for distortion" button on the Effects page, for the pipeline that page shows. It opens a
dialog that holds the whole flow. It works for the output and the input (microphone) chains alike,
since both are built from the same stages. (Builder's call: Output only first is acceptable if the
input chain needs extra work.)

### Monitoring

The dialog taps, for the pipeline's current chain:

- the chain's input: the sink monitor for the output chain, the device for the input chain, as the
  "before" tap does today;
- each step's output stream, from `Pipeline.steps()`, linked as the meters link them.

For each tap it keeps, over the whole run:

- the number of blocks whose sample peak on any channel went over 1.0, and the largest peak;
- the sum of squares and sample count, for blocks where that stage's input was above -60 dBFS, so
  silence and quiet passages do not count towards a drop.

While monitoring, the dialog shows each stage with its current state, updated a few times a second:

```
 Distortion check · Dali iO6              [ Stop ]
 ● Monitoring… 1:42
   Surround Downmix   ok
   Equalizer          over by up to 4.1 dB  (37 times)
   Bass Loudness      over by up to 9.8 dB  (212 times)
   Limiter            ok
```

If the chain is rebuilt during the run (the user changed the preset, the device or the route), the
taps no longer match the stages. The check stops and says so, with a Run again button.

### Summary

After Stop, the dialog lists every stage with:

- **Overs:** the largest over in dB and how many times it happened, or "ok".
- **Level change:** the stage's output level against its input level over the run. A drop of more
  than 6 dB is flagged. The surround downmix's built-in headroom (`HRIR_HEADROOM`) is expected and is
  subtracted before comparing, and is shown as "headroom, expected".
- **Planned fix:** the control that would be cut, and by how much, if any.

```
   Surround Downmix   ok · -9.9 dB (headroom, expected)
   Equalizer          over by up to 4.1 dB (37 times)   → output gain -4.6 dB
   Bass Loudness      ⚠ drops 23.4 dB                    → none (flagged only)
   Limiter            ok
```

Overs at the chain's input (an app already sending over 0 dB) are shown as information. They do not
distort until a stage passes them on, and that stage's own over is then fixed.

At the bottom: **Fix settings**, **Fix and save preset**, **Cancel**. With nothing to fix, only
**Close** and **Run again**.

### Working out the cuts

Each stage's cut is made on the gain at the end of that stage, after its processing, so the cut lowers
that stage's output peak by exactly the cut whatever the stage does. Cutting the input instead would
not work for a limiter, whose output peak is set by its threshold and output gain, and would change how
hard a compressor or gate works, not just how loud the result is. (This differs from the "input gain"
in the approach as first described; it is the same per-stage approach, made on the other side of each
stage.)

Stages are taken in chain order. For each stage, with `over` its largest peak above 0 dB in dB and
`cut_so_far` the total of cuts made at earlier stages:

```
needed = over + 0.5 - cut_so_far
if needed > 0: cut this stage by needed; cut_so_far += needed
```

The 0.5 dB margin keeps peaks a little short of full scale on the next run. Cuts are rounded up to the
control's step (0.1 dB for effects, 0.5 dB for surround levels), so a stage is never cut by less than
it needs. "Run again" is how the user confirms the fix, since a later stage that reacts to level (a
compressor after a cut) can change its own output.

Where a stage's cut goes:

| Stage | Control cut |
|-------|-------------|
| Surround Downmix | every channel's surround level, by the same amount |
| Equaliser, limiter, compressor, expander, gate, multiband compressor, Bass Loudness, Deep Noise Remover, convolver | the effect's `output-gain` |
| Loudness | `volume` |
| Maximizer | `ceiling` |
| Autogain | `target`. Autogain settles on its target over a few seconds, so the cut takes effect gradually; the summary notes this. |

Every stage can be fixed, so an over never passes on unfixed to be blamed on a later stage.

**Limits.** When a cut does not fit in a control's range (effect output gains stop at -36 dB, surround
levels at -12 dB, and a channel may already be near its limit), as much as fits is applied there and
the rest is carried to the next stage's cut. If the chain ends with some cut still unapplied, the
summary says by how much the preset could not be fixed.

### Applying

- **Fix settings** applies the cuts without writing the preset or the app settings. They are held by
  the pipeline as temporary trims on top of the preset's own values and the surround levels, which
  `graph.build` and the live controls both include. So they survive the chain's own restarts (a rate
  change, lost streams, a crash, a structural edit) and also reach the convolver, which can only change
  through a rebuild. They are dropped when another preset is loaded, the preset is reloaded, or Skitz
  Effects quits. A later edit in the UI saves only what the user edited, never the trims.
- **Fix and save preset** folds the cuts into the preset's values and saves it, and saves the new
  surround levels into the app settings, so they apply the way any edit does. Any temporary trims from
  an earlier "Fix settings" are folded in too.
- **Cancel** changes nothing.

After either fix, the summary offers **Run again**, which starts a new check on the fixed chain.

## Left to the builder

- How the dialog is built from Adwaita widgets, and its wording, within the flow above.
- How often the live view updates, and the block size used for counting overs.
- Whether the check reuses `levels.Meters` or runs its own `levels.Tap` instances.
- Tests: the cut calculation and the drop calculation are plain functions and should be tested with
  made-up stage readings; the taps and dialog need no tests beyond the existing patterns.
