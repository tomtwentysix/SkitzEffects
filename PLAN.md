# Skitz Effects plan

**Goal:** to the user it looks and works like Easy Effects, uses Easy Effects presets, and adds
5.1/7.1 input that is passed through to surround devices or downmixed through an HRIR on stereo
devices, all from one GNOME-native window.

**Principles**
- Skitz Effects is a manager and has no DSP of its own. PipeWire's filter-chain hosts the LV2
  plugins Easy Effects uses (LSP, ZAM) and its convolver does IRs and HRIRs. WirePlumber
  handles routing, defaults and names.
- Easy Effects presets are edited in place, so both apps keep working with the same files.
- Dependencies come from the distro package manager (`Requires:`), never bundled.
- GNOME HIG and libadwaita widgets; credited to SolarFlare Developments.

## Architecture

```
apps ─► skitz_sink (lingering null sink, 2/6/8 ch)
          └─ monitor ─► [output filter-chain: HRIR downmix? → effects] ─► hardware sink
mic ─► [input filter-chain: effects] ─► skitz_source (lingering Audio/Source/Virtual) ─► apps
```
- `pipewire.py`: live model from `pw-dump --monitor`; actions via `wpctl`/`pw-cli`.
- `controller.py`: `Controller` (PipeWire, conflicts, devices) owns two `Pipeline`s (output,
  input). Each plays through or records from the default device, which stays the real device as
  in Easy Effects, moves app streams onto Skitz Effects' nodes with `target.object` metadata while
  its chain runs (and back if it stops), loads per-device presets, and
  restarts its `pipewire -c` child on structural changes or live-updates controls via Props.
- `graph.py`: filter-chain configs; `choose_route()` picks passthrough / HRIR / plain downmix.
- `plugins.py`: Easy Effects key → LV2 port maps; `presets.py`: preset/IR/autoload files.
- `deps.py`: required packages and conflicting apps; `names.py` (new): WirePlumber rename rules.
- `ui/`: window (Output, Input, Surround, Devices), effects view, wizard.

## Milestones

### M1: Input, conflicts, renaming, packaging (done)
1. **Input tab** (`ui/window.py`): `EffectsView(controller.input)` page; the presets button and
   effects switch bind to the visible pipeline and hide on Surround/Devices; the presets popover
   uses `presets.list_presets(direction)`. `ui/wizard.py`: input preset count, import both
   `autoload_rules("output"/"input")`, a default preset per direction.
2. **Conflict banner**: `_update_banner()` priority is missing packages → running Easy Effects or
   Virtual Surround (from `Controller.conflicts`, button **Turn Off** → `Conflict.turn_off()`) →
   a stopped chain. Wizard says so when no conflicting app is running.
3. **Device renaming** (`names.py`, `ui/devices.py`): Skitz Effects owns
   `~/.config/wireplumber/wireplumber.conf.d/60-skitz-effects-devices.conf`, holding node rules
   (`node.name` → `node.description`/`node.nick`, the exact name in GNOME) plus card rules carried
   over from any rename files already in that folder, which are imported once and renamed to
   `.conf.disabled`. Rules sit under `monitor.alsa.rules`/`monitor.bluez.rules` by name prefix.
   A small relaxed SPA-JSON reader parses the files back, so the file stays the only record.
   Applying a rename restarts WirePlumber (the dialog warns that audio pauses briefly) and then
   `Controller.restart_chains()` rebuilds both chains, because their links drop with WirePlumber.
   Each device row gets an edit button → `Adw.AlertDialog` with **Rename** and **Reset Name**.
4. **RPM** (`packaging/skitz-effects.spec`, launcher), modelled on Superlion: `Requires:`
   python3-gobject-base, gtk4, libadwaita, pipewire, pipewire-utils, wireplumber,
   pipewire-module-filter-chain-lv2, lsp-plugins-lv2, lv2-zam-plugins.

### M2: Live hardening on real devices (done)
Tested on Fedora 44, PipeWire 1.6.10, WirePlumber 0.5.18, with the Dali IO6 (USB headphones),
Midas UMC22 and the user's own presets.
- Verified: both chains start and link, effects are audible and match Easy Effects, live control
  edits apply without a restart, choosing an output in GNOME Settings switches Skitz Effects and loads
  that device's preset, the HRIR places all 7.1 channels correctly (a 48 kHz HRIR on a 96 kHz
  device is resampled by the convolver), and the chain recovers from a crash and from PipeWire and
  WirePlumber restarts.
- Passive links hold up: playing wakes the device through both passive hops and it suspends a few
  seconds after playback stops; recording from `skitz_source` opens the mic, and it closes
  again afterwards. No non-passive fallback was needed.
- 7.1 passthrough (measured on an 8-channel null sink, since the HDMI display only offers stereo):
  filter-chain runs the 2-in graph once per channel pair, every channel is processed, and one Props
  update changes all four copies.
- Fixed: duplicate virtual devices and a `wpctl` storm (actions repeated while still in flight);
  the input chain could never link (WirePlumber will not link a playback stream to a source, so the
  controller links it with `pw-link --passive`); a chain process with no nodes left counted as
  running; Popen and GLib both reaping the chain; Skitz Effects following WirePlumber's transient
  defaults and vanishing devices during a WirePlumber restart (it now follows the configured
  default and keeps the chosen device through a 5 second grace period); a stale object model
  after a PipeWire restart.
- Added: Bass Loudness through MDA (`lv2-mdala-plugins`, now required), with builtin gain nodes
  for the preset's input and output gain. Device Settings replaces the rename dialog. Its Disable
  Suspend and Sample Rate rules were later removed: pinning one device to 96 kHz under a 48 kHz
  graph made the HRIR chain fall behind, and the user's own startup script handles the Dali.
- `tests/` (pytest): `choose_route`, preset → controls mapping from real presets, graph output,
  the SPA-JSON reader and device rules, and preset loading in both Easy Effects formats.
- Not tested: Bluetooth devices, and surround passthrough on physical 8-channel hardware.
- Afterwards, at the user's request, Skitz Effects stopped taking the default device: GNOME now shows
  the real device and app streams are moved instead. Switching from GNOME and quitting were
  re-tested; PipeWire and WirePlumber restarts were not re-run after this change.
- Inputs can record one chosen channel to both sides (Device Settings → Channel).

### M3: Easy Effects parity
- Presets: rename, delete, duplicate, import/export, Easy Effects community preset folders.
- Effects list: drag-and-drop reorder (replacing the up/down buttons).
- Done: Mixer page (Easy Effects' Players and Recorders): each app's volume and mute, and a switch
  that leaves it out of the effects through the preset's `blocklist` key.
- Done: before/after spectrum at the top of the Output and Input pages (curves or bars), a status
  bar with output and mic peak meters and Output/Mic Pre-Gain sliders (`skitz_sink` and the
  mic's own volume), and a graphical parametric EQ. Levels come from `pw-record` taps in
  `levels.py`; they are passive, so metering never wakes a device or opens the mic, except that
  the Input page opens the mic while it is shown.
- Latency readout.
- Deep Noise Remover (DeepFilterNet's LADSPA plugin) on input. Fedora does not package it, so
  github.com/tomtwentysix/ladspa-deepfilternet-rpm builds it in the same COPR, with a weekly
  workflow that follows upstream releases; Skitz Effects `Recommends:` it.
- Done: Devices page redesign. Sections are In Use, Surround (moved here from its own page),
  Outputs and Inputs; each device opens a settings window (name, preset, channel). Inputs are picked by device and named after the card; Channel picks the card's
  input profile (stereo, input 1, input 2, mono mix), and Skitz Effects follows the renamed node.
- Done: the header's menu picks the device for the page shown; presets moved to the top of the
  effects sidebar.
- More effects with packaged plugins: filter, delay, expander, multiband gate (LSP), the Calf
  effects (`lv2-calf-plugins`: bass enhancer, exciter, stereo tools, reverb, deesser), and echo
  cancellation on input via PipeWire's own echo-cancel module.

### M4: Surround polish
- Per-device downmix override: USB headsets that report 7.1 can be set to always use the HRIR,
  while the global setting stays the default.
- Speaker test: play a tone on each channel through the chain.
- HRIR library management: import WAVs into Skitz Effects' IR folder and show the channel count.

### M5: Release
- App icon (PNG sizes, symbolic), metainfo, screenshots, README, COPR repo like Superlion's.

### M6: Flatpak
- Flatpak using the Flathub LinuxAudio extensions for LSP, ZAM, Calf, MDA and bs2b; bs2b also
  enables Crossfeed, which Fedora cannot. Bundle filter-chain and lilv inside the sandbox.

## Risks and open questions
- Easy Effects 8 may change its preset keys (for example, IR paths); `plugins.py` mappings may need
  per-version aliases.
- WirePlumber restart on rename is disruptive; there's no runtime API to change a node's description.
- When Skitz Effects' sink comes back after a WirePlumber restart, apps play straight to the device for
  a fraction of a second before WirePlumber restores the default.

## Verification for M1
- `py_compile` everything. Build output and input configs from the real presets and run each
  briefly with `pipewire -c` against nonexistent targets, so audio is unaffected.
- Parse an existing rename file, generate the new file somewhere temporary, and parse it back.
- Headless UI check under Broadway with a private `XDG_RUNTIME_DIR`: Input tab, header binding
  when switching pages, the conflict banner with a simulated node, and the rename dialog.
- WirePlumber restarts and real renames wait for M2.
