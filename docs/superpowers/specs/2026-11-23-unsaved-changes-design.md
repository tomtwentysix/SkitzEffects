# Unsaved changes

## Intent

A preset, and a device's surround levels, are written to disk only when the user deliberately saves
them. Every control shows the live value, the one actually being played, whether it came from the user
or from the Distortion Check. Today every edit autosaves half a second later, and the Distortion Check's
"Fix Settings" holds its cuts in a separate layer the controls never show, so what the user sees and
hears can differ, and experiments end up in the preset by accident.

## Goals

- Edits to a preset are live but unsaved until the user saves. A Save button on the Effects page writes
  them; the preset picker marks a preset with unsaved changes.
- Surround levels belong to the output device: each device keeps its own. Edits to them are live but
  unsaved until saved with a Save button of their own on the Surround page.
- Switching away from unsaved changes, or quitting with them, asks: save, cancel, or discard.
- A switch caused by a device change brings the window to the front, opening it from the tray if
  needed, to ask. Until the user answers, the edited preset and levels keep playing.
- The Distortion Check's buttons become Apply, Apply and Run Again, Apply and Save, and Cancel; Apply
  changes the live values like any other edit.

## Non-goals

- Crash recovery: unsaved changes are lost if the app crashes or the session ends.
- Undo history beyond discarding back to what was last saved.
- Changing how Easy Effects presets are stored on disk.

## Anti-goals

- Anything written to a preset file or to the saved surround levels without the user choosing a save.
- A control that shows a value other than the one being played.
- A prompt that hides behind other windows, or a device change that silently throws away edits.

## Constraints

- Presets are Easy Effects JSON files, read and written by `presets.Preset` (`settings()`, `save()`).
- `Pipeline.changed` queues an autosave (`_queue_save`, 500 ms), and `load_preset`, `new_preset` and
  `shutdown` flush it (`_flush_save`).
- A device change goes through `Pipeline.select_device`, which loads the device's preset from
  `state["device_presets"]` through `load_preset`. Card profile renames go through `_migrate`.
- Surround levels are one global dict, `Settings.surround_levels`, saved at once by
  `Pipeline.set_surround_level`, shown by `ui/surround.py`.
- The Distortion Check holds "Fix Settings" cuts as `Pipeline.trims`, applied through `check.trimmed`
  and `check.trimmed_levels` in `_build`, `_send_live` and `set_surround_level`.
- The app can live in the tray with no window (`app.hold_in_background`, the `show` action);
  `app.do_activate` presents the window.
- Quitting goes through the `quit` action (`app._on_quit`) or `do_shutdown`.

## Approaches

1. **A live copy and a saved snapshot** (chosen). The pipeline keeps the live preset in memory, as now,
   plus a snapshot of what is on disk, taken on load and save. Unsaved means the two differ, so editing
   a value back clears the mark. Save writes the live copy and refreshes the snapshot; discard restores
   the snapshot. Surround levels work the same way per device. The trims layer is removed.
2. **Autosave to a working file** beside the preset, promoted on save. Survives a crash, but leaves side
   files Easy Effects may see, needs housekeeping, and doubles every preset on disk.
3. **An overlay of edits on the saved preset**, as the trims are today. Every control would merge two
   sources; it is the most complex, and is what makes the controls show saved values now.

The user chose 1.

## Design

### Presets

- `Pipeline` keeps `saved`, a deep copy of the preset's data as last loaded or saved. `Pipeline.unsaved`
  is true while the live data differs from it.
- `Pipeline.changed` no longer queues a save. `_queue_save`, `_flush_save` and the save timer are
  removed. Everything that edits the preset (effect controls, adding, removing and reordering effects,
  the equaliser editor, the Distortion Check) changes only the live preset.
- `Pipeline.save_preset()` writes the live preset and refreshes the snapshot.
  `Pipeline.discard_preset()` restores the snapshot, rebuilds the chain and emits `preset-changed`, so
  every control shows the restored values.
- Creating a preset (`new_preset`) saves the new, empty preset straight away, as it does now, so it
  exists on disk to switch back to.
- Both directions follow these rules: output presets and microphone presets.
- The Mixer's per-app effects switch (`Pipeline.set_blocked`, the preset's `blocklist`) still saves at
  once: it is about routing, not sound, and has no Save button on its page. It saves through a narrow
  path that writes only the blocklist into the saved preset and updates the snapshot's blocklist the
  same way, so it neither marks the preset unsaved nor writes other unsaved edits.

### Surround levels

- `Settings.surround_levels` becomes per device: `Settings.output["device_surround_levels"]` maps an
  output device's `node.name` to its levels, alongside `device_presets`.
- Moving existing settings across: on first load, the old global levels become those of the output
  device in use (`output["device"]`), and the global key is dropped. Other devices start at 0 dB.
- The output pipeline keeps the live levels, the device they belong to (their owner), and a snapshot of
  that device's saved levels. Changing a level on the Devices page or through the Distortion Check
  changes only the live levels.
- Edited levels stay the owner's edits until saved or discarded, even while another device plays them
  after a Cancel: Save writes them to the owner, and the unsaved mark compares against the owner's
  saved levels. When the owner comes back with the edits still live, nothing asks; the edits simply
  carry on with their own device. When the levels are not edited, the owner follows the current
  device.
- The surround levels live in `SurroundGroup` (`ui/surround.py`) on the Devices page. That group gets
  its own Save button in its header, sensitive only while the levels are unsaved, which writes the
  levels into the app settings. Save stays usable while the level rows are greyed out because the
  route is not the HRIR downmix, so unsaved levels can always be saved. (Builder's call on placement
  within the header.)

### Marking unsaved changes

- The preset picker's label gets a trailing " •" while the preset is unsaved, and the Effects page's
  Save button, beside the picker, is sensitive only then.
- The surround group's Save button does the same for the levels.

### Switching with unsaved changes

Any switch away from unsaved changes asks first. That covers choosing another preset, creating a
preset, a device change that loads the device's preset, and a device change that brings in another
device's surround levels.

- The prompt is one `Adw.AlertDialog` covering everything unsaved that the switch would replace (the
  preset, the levels, or both), with **Save and Switch**, **Cancel** and **Discard and Switch**.
- **Save and Switch** saves what is unsaved, then switches.
- **Cancel** keeps everything as it is: the edited preset and levels stay live. After a device change
  this means the new device plays the edited preset and levels, and its own preset rule and levels are
  not applied this time.
- **Discard and Switch** drops the edits, then switches.
- A device change still routes audio to the new device at once. Only the preset and levels wait for the
  answer, and until then the edited ones keep playing.
- When a device change asks, the window is presented, and opened first if the app is only in the tray,
  as the tray's show action does.
- A pending switch is tracked per pipeline. When both directions are waiting at once, for example a USB
  headset changing the output and the microphone together, one prompt covers both, and its answer
  applies to both.
- If another device change arrives in the same direction while the prompt is open, that direction's
  earlier switch is answered as Cancel and the prompt asks again for the newest. (Builder's call how to
  replace the open dialog.)

### Quitting

- Quitting with unsaved changes asks the same way: **Save and Quit**, **Cancel**, **Discard and Quit**,
  bringing the window forward if needed.
- Closing the window when the app does not run in the background ends the app, so it is quitting and
  asks the same way, through the window's `close-request`. With background running on, closing the
  window only hides it, keeping the unsaved changes live.
- When the session ends (logout or shutdown, through `do_shutdown` without the quit action or a window
  close), nothing can wait for an answer, so unsaved changes are discarded.

### The Distortion Check

- The summary's buttons become **Apply** (apply the cuts to the live values and close), **Apply and Run
  Again** (apply, then start a new check in the same dialog), **Apply and Save** (apply, then save the
  preset and, if the surround levels were cut, the current device's levels), and **Cancel**.
- Applied cuts change the live preset and live levels through the same paths as any edit, so the
  controls show them and the unsaved marks appear.
- `Pipeline.trims`, `Pipeline.fix`'s trims handling, `check.trimmed` and `check.trimmed_levels`'s uses
  for trims, and the related tests are removed or rewritten for the live values. `check.fold` stays as
  the way cuts are added to the live preset.
- The room for planning cuts is measured from the live values.

## Left to the builder

- How the alert dialog is shown over the window and replaced when a second device change arrives.
- The exact wording of the prompt's body text, in the app's formal style.
- How `unsaved` is computed cheaply (a dict comparison after each change is fine at this size).
- Tests: the pure parts (snapshot comparison, saving, discarding, the per-device levels and their
  migration, the switch decision) get tests with stub pipelines in the existing patterns; the dialogs
  get import smoke tests only.
