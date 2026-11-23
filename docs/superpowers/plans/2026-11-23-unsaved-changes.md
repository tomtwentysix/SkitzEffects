# Unsaved Changes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Presets and per-device surround levels change live and are written only on a deliberate save, with a save, cancel or discard prompt before anything replaces unsaved changes.

**Architecture:** `Pipeline` keeps a snapshot of each saved value beside the live one: the preset's data, and for output the surround levels with the device that owns them. Autosave and the Distortion Check's trims layer go away; every edit, including the check's cuts, changes the live values. A switch that would replace unsaved values becomes a pending switch on the pipeline, which the app answers through one prompt.

**Tech Stack:** Python 3, PyGObject (GTK 4, libadwaita), PipeWire filter-chains, pytest.

**Spec:** `docs/superpowers/specs/2026-11-23-unsaved-changes-design.md`

## Global Constraints

- Nothing is written to a preset file or to the saved surround levels except by a deliberate save: the Save buttons, "Save and Switch", "Save and Quit", or the Distortion Check's "Apply and Save". The one exception is the Mixer's per-app effects switch (`set_blocked`), which writes only the blocklist.
- Every control shows the live value.
- Prompt buttons, verbatim: "Save and Switch", "Cancel", "Discard and Switch"; "Save and Quit", "Cancel", "Discard and Quit". Distortion Check summary buttons: "Apply", "Apply and Run Again", "Apply and Save", "Cancel".
- The unsaved mark is a trailing " •" on the preset picker's label.
- Cancel after a device change keeps the edited preset and levels playing on the new device; that device's preset rule and levels are not applied this time. Edited levels stay their owner's edits; the owner coming back asks nothing.
- A session end (`do_shutdown` without the quit action or a window close) discards unsaved changes.
- Code style (CLAUDE.md): no section banners, no docstrings restating names, no prose comments on UI choices; comment only what the code cannot show. UI copy formal.
- Tests never launch the app, open a display or touch the live PipeWire session; GTK widget code gets import smoke tests only.

## Review Focus

- Editing a value and then editing it back: the preset is no longer unsaved (Task 1 test).
- The Mixer's effects switch while the preset has unsaved edits: the file gains only the blocklist, the preset stays unsaved, and Discard keeps the new blocklist (Task 1 test).
- A device change to a device with no preset rule while the preset is unsaved: nothing asks and the edited preset keeps playing (Task 4 test).
- Cancel on a device change, then the levels' owner comes back: nothing asks and the edits carry on (Task 4 test).
- An old config whose output device is empty: the global surround levels are dropped, not filed under "" (Task 2 test).

---

### Task 1: Live presets with a saved snapshot

**Files:**
- Modify: `skitz_effects/controller.py` (class `Pipeline`), `skitz_effects/presets.py`
- Test: `tests/test_controller.py`, `tests/test_presets.py`

**Interfaces:**
- Produces on `Pipeline`:
  - signal `"unsaved-changed"` (no args), emitted whenever `unsaved` or `levels_unsaved` may have changed.
  - `unsaved -> bool` (property): the live preset's data differs from `self.saved`.
  - `save_preset() -> None`: writes the live preset, refreshes the snapshot, emits `unsaved-changed`.
  - `discard_preset() -> None`: restores the live preset's data from the snapshot, rebuilds the chain, emits `preset-changed` and `unsaved-changed`.
- Produces on `presets.Preset`: `save_blocklist(blocklist: list) -> None`: writes only the blocklist into the file's data on disk, leaving every other value as saved.

- [ ] **Step 1: Write the failing tests** (stub pipeline pattern in `tests/test_controller.py`, "Dali iO6" fixture):
  - `test_edits_are_live_but_unsaved`: change `bass_loudness#0` output-gain in the live preset and call `changed("bass_loudness#0")` → `unsaved` is True and the file's bytes are unchanged; `save_preset()` → file holds the new value and `unsaved` is False.
  - `test_editing_back_clears_unsaved`: change a value, `changed`, change it back, `changed` → `unsaved` is False.
  - `test_discard_restores_the_saved_preset`: remove an effect from `preset.order` and change a value, `changed(..., structural=True)`, then `discard_preset()` → order and value as saved, `unsaved` False, `preset-changed` emitted.
  - `test_loading_and_quitting_write_nothing`: an unsaved edit, then `shutdown()` → file bytes unchanged.
  - `test_the_mixer_switch_saves_only_the_blocklist`: an unsaved edit, then `set_blocked(props, True)` → the file's blocklist has the app and every other value is as saved; `unsaved` still True; `discard_preset()` keeps the app in the blocklist.
  - In `tests/test_presets.py`, `test_save_blocklist_writes_only_the_blocklist`.
- [ ] **Step 2: Run them and see them fail.** `python3 -m pytest -q tests/test_controller.py tests/test_presets.py`
- [ ] **Step 3: Implement.** Remove `_queue_save`, `_on_save_timeout`, `_flush_save` and `_save_id`, and every call to them. The snapshot is `copy.deepcopy(preset.data)`, taken in `__init__`, `load_preset`, `new_preset` (which still saves the new preset once) and `save_preset`; `None` when there is no preset. `changed` and `set_blocked` emit `unsaved-changed`. `shutdown` no longer saves.
- [ ] **Step 4: Run all tests.** `python3 -m pytest -q` → all pass.
- [ ] **Step 5: Commit** "Keep preset edits live until they are saved".

### Task 2: Surround levels per device

**Files:**
- Modify: `skitz_effects/config.py`, `skitz_effects/controller.py`, `skitz_effects/check.py`
- Test: `tests/test_config.py` (create), `tests/test_controller.py`

**Interfaces:**
- Produces in config: `Settings.surround_levels` is removed; `settings.output["device_surround_levels"]: dict[device node.name, dict[channel, dB]]`. `config.load()` moves an old global `surround_levels` to `output["device_surround_levels"][output["device"]]` when that device is set, and drops it otherwise.
- Produces on the output `Pipeline`:
  - `levels: dict` (live levels), `levels_owner: str` (device node.name the live levels belong to).
  - `levels_unsaved -> bool` (property): `levels` differ from the owner's saved levels (a missing channel counts as 0.0).
  - `save_levels() -> None`, `discard_levels() -> None` (restores the owner's saved levels, sends them live, emits `unsaved-changed`).
  - `set_surround_level(channel, gain)` changes only `levels` and emits `unsaved-changed`.
  - While the levels are not unsaved, a device change makes `levels_owner` the new device and loads its saved levels.
- `_build` uses `self.levels`; `check.room` and the Distortion Check read `pipeline.levels`.

- [ ] **Step 1: Write the failing tests:**
  - `test_old_global_levels_move_to_the_current_device` and `test_old_global_levels_without_a_device_are_dropped` (write a config file to a temporary `CONFIG_PATH` with `monkeypatch`).
  - `test_levels_are_live_until_saved`: `set_surround_level("FC", -3.0)` → `levels_unsaved` True and `settings.save` not called; `save_levels()` → `output["device_surround_levels"][owner]["FC"] == -3.0`.
  - `test_unedited_levels_follow_the_device`: saved levels for devices "a" and "b"; a device change from "a" to "b" (call the method `select_device` uses; stub what it needs) → `levels_owner == "b"` and `levels` are b's.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.** Replace every use of `settings.surround_levels` (controller, `ui/surround.py` reads `controller.output.levels`, `ui/check.py`).
- [ ] **Step 4: Run all tests.** → all pass.
- [ ] **Step 5: Commit** "Keep surround levels per device, live until saved".

### Task 3: The Distortion Check applies to the live values

**Files:**
- Modify: `skitz_effects/controller.py`, `skitz_effects/check.py`, `skitz_effects/ui/check.py`
- Test: `tests/test_controller.py`, `tests/test_check.py`, `tests/test_check_ui.py`

**Interfaces:**
- Consumes: `save_preset`, `save_levels` (Tasks 1, 2).
- Produces: `Pipeline.apply_cuts(cuts: list[check.Cut]) -> None` replaces `fix`: folds effect cuts into the live preset (`check.fold`), applies a surround cut to `levels` (`check.trimmed_levels`), sends live controls or rebuilds for a convolver, emits `unsaved-changed`. Cuts for effects not in `preset.order` are ignored, as `fix` does now. `Pipeline.trims` and `check.trimmed` are removed.

- [ ] **Step 1: Rewrite the tests:** the trims tests in `tests/test_controller.py` become `test_apply_cuts_changes_the_live_preset` (file unchanged, `unsaved` True, live value lowered), `test_apply_cuts_lowers_the_live_levels`, and `test_apply_cuts_ignores_effects_the_preset_lacks`; remove `check.trimmed` tests from `tests/test_check.py`.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement**, and in `ui/check.py` replace the summary buttons with "Apply" (apply, close), "Apply and Run Again" (apply, then `_run`), "Apply and Save" (apply, `save_preset()`, and `save_levels()` when a cut has control "surround"), "Cancel". Room comes from `check.room(pipeline.preset, stages, layout, pipeline.levels)`.
- [ ] **Step 4: Run all tests** and `python3 -c "import skitz_effects.ui.check"`. → all pass.
- [ ] **Step 5: Commit** "Apply the Distortion Check's cuts to the live values".

### Task 4: Pending switches

**Files:**
- Modify: `skitz_effects/controller.py`
- Test: `tests/test_controller.py`

**Interfaces:**
- Produces on `Pipeline`:
  - `pending -> Pending | None`, where `Pending` is a dataclass in controller.py: `preset: str | None` (a preset to load), `new: bool` (create it instead), `device: str | None` (the device whose rule and levels wait).
  - signal `"switch-pending"` (no args), emitted when `pending` is set.
  - `load_preset(name)` and `new_preset(name)` set `pending` instead of switching while `unsaved`; otherwise unchanged.
  - A device change (`select_device`) still sets `state["device"]` and routes audio at once. When the device's preset rule would replace an unsaved preset, or (output) the levels are unsaved and the new device is not their owner, it sets `pending` with `device` set instead of applying the rule and levels. A second device change in the same direction replaces `pending`.
  - `resolve(choice: str) -> None` with `"save"`, `"cancel"` or `"discard"`: save or discard what is unsaved (preset and/or levels), then carry out the switch, or with `"cancel"` drop it. Clears `pending`.

- [ ] **Step 1: Write the failing tests** (stub pipeline, stubbed `devices()`):
  - `test_switching_from_unsaved_waits` → `pending.preset == "HS8"`, preset unchanged, `switch-pending` emitted.
  - `test_resolve_save_discard_cancel` (one each): save writes the edit then loads HS8; discard loads HS8 with the file unchanged; cancel keeps the edited preset.
  - `test_a_device_with_no_rule_does_not_ask`.
  - `test_cancel_on_a_device_change_keeps_the_edits`, then `test_the_owner_coming_back_asks_nothing`: edited levels owned by "a", change to "b", cancel; change back to "a" → no `pending`, levels still the edits, `levels_owner == "a"`.
  - `test_a_second_device_change_replaces_the_pending_one`.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run all tests.** → all pass.
- [ ] **Step 5: Commit** "Wait for an answer before switching away from unsaved changes".

### Task 5: Save buttons, the prompt, and quitting

**Files:**
- Create: `skitz_effects/ui/unsaved.py`
- Modify: `skitz_effects/ui/effects.py`, `skitz_effects/ui/surround.py`, `skitz_effects/ui/window.py`, `skitz_effects/app.py`
- Test: `tests/test_unsaved_ui.py` (create)

**Interfaces:**
- Consumes: Tasks 1, 2 and 4.
- Produces in `ui/unsaved.py`: `prompt_text(pipelines, quitting: bool) -> tuple[str, str]` (pure: the heading and body naming what is unsaved, e.g. the preset "Dali iO6" and the surround levels of "Dali IO6 Analog Stereo"), and `ask(window, pipelines, quitting: bool, done: Callable[[str], None])`, which shows an `Adw.AlertDialog` with the buttons from Global Constraints and calls `done` with "save", "cancel" or "discard".

- [ ] **Step 1: Write the failing tests** for `prompt_text` with stub pipelines: preset only, levels only, both, both directions, quitting wording.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement:**
  - Effects page: a Save button beside the preset picker, sensitive only while `unsaved`; the picker label gets " •" while unsaved; both refresh on `unsaved-changed`.
  - Surround group: a Save button in its header, sensitive only while `levels_unsaved`, independent of the route.
  - App: on any pipeline's `switch-pending`, present the window (creating it from the tray if needed, as `do_activate` does) and `ask` once for every pipeline with `pending`, resolving each with the answer. A `switch-pending` while the prompt is open closes it and asks again for the current set.
  - Quitting: the `quit` action, and the window's `close-request` when `run_in_background` is off, ask with `quitting=True` while any pipeline is unsaved: save or discard everything then quit, or cancel. `do_shutdown` discards.
- [ ] **Step 4: Run all tests** and `python3 -c "import skitz_effects.ui.unsaved, skitz_effects.ui.effects, skitz_effects.ui.surround, skitz_effects.ui.window, skitz_effects.app"`. → all pass.
- [ ] **Step 5: Commit** "Ask before switching or quitting with unsaved changes".
