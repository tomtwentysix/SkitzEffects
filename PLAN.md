# Soundstage plan

**Goal:** to the user it looks and works like Easy Effects, uses Easy Effects presets, and adds
5.1/7.1 input that is passed through to surround devices or downmixed through an HRIR on stereo
devices, all from one GNOME-native window.

**Principles**
- Soundstage is a manager and has no DSP of its own. PipeWire's filter-chain hosts the LV2
  plugins Easy Effects uses (LSP, ZAM) and its convolver does IRs and HRIRs. WirePlumber
  handles routing, defaults and names.
- Easy Effects presets are edited in place, so both apps keep working with the same files.
- Dependencies come from the distro package manager (`Requires:`), never bundled.
- GNOME HIG and libadwaita widgets; credited to SolarFlare Developments.

## Architecture

```
apps ─► soundstage_sink (lingering null sink, 2/6/8 ch)
          └─ monitor ─► [output filter-chain: HRIR downmix? → effects] ─► hardware sink
mic ─► [input filter-chain: effects] ─► soundstage_source (lingering Audio/Source/Virtual) ─► apps
```
- `pipewire.py`: live model from `pw-dump --monitor`; actions via `wpctl`/`pw-cli`.
- `controller.py`: `Controller` (PipeWire, conflicts, devices) owns two `Pipeline`s (output,
  input). Each follows the default device, takes the default back, loads per-device presets, and
  restarts its `pipewire -c` child on structural changes or live-updates controls via Props.
- `graph.py`: filter-chain configs; `choose_route()` picks passthrough / HRIR / plain downmix.
- `plugins.py`: Easy Effects key → LV2 port maps; `presets.py`: preset/IR/autoload files.
- `deps.py`: required packages and conflicting apps; `names.py` (new): WirePlumber rename rules.
- `ui/`: window (Output, Input, Surround, Devices), effects view, wizard.

## Milestones

### M1: Input, conflicts, renaming, packaging (in progress)
1. **Input tab** (`ui/window.py`): `EffectsView(controller.input)` page; the presets button and
   effects switch bind to the visible pipeline and hide on Surround/Devices; the presets popover
   uses `presets.list_presets(direction)`. `ui/wizard.py`: input preset count, import both
   `autoload_rules("output"/"input")`, a default preset per direction.
2. **Conflict banner**: `_update_banner()` priority is missing packages → running Easy Effects or
   Virtual Surround (from `Controller.conflicts`, button **Turn Off** → `Conflict.turn_off()`) →
   a stopped chain. Wizard says so when no conflicting app is running.
3. **Device renaming** (`names.py`, `ui/devices.py`): Soundstage owns
   `~/.config/wireplumber/wireplumber.conf.d/60-soundstage-device-names.conf`, holding node rules
   (`node.name` → `node.description`/`node.nick`, the exact name in GNOME) plus card rules carried
   over from any rename files already in that folder, which are imported once and renamed to
   `.conf.disabled`. Rules sit under `monitor.alsa.rules`/`monitor.bluez.rules` by name prefix.
   A small relaxed SPA-JSON reader parses the files back, so the file stays the only record.
   Applying a rename restarts WirePlumber (the dialog warns that audio pauses briefly) and then
   `Controller.restart_chains()` rebuilds both chains, because their links drop with WirePlumber.
   Each device row gets an edit button → `Adw.AlertDialog` with **Rename** and **Reset Name**.
4. **RPM** (`packaging/soundstage.spec`, launcher), modelled on Superlion: `Requires:`
   python3-gobject-base, gtk4, libadwaita, pipewire, pipewire-utils, wireplumber,
   pipewire-module-filter-chain-lv2, lsp-plugins-lv2, lv2-zam-plugins.

### M2: Live hardening on real devices
- Install the plugin packages and test on real devices: chain start, effects audible, live control
  edits, device switching from GNOME, Bluetooth, PipeWire and WirePlumber restarts, chain crash
  recovery.
- Verify the assumptions the design rests on: two passive hops still wake the device when apps play,
  and the mic stays closed when nothing records. Filter-chain should copy the stereo graph per
  channel pair on surround passthrough, and Props updates should reach every copy. Sample-rate
  changes must not break the HRIR convolver.
- `tests/` with pytest for the pure parts: `choose_route`, preset → controls mapping, graph output,
  SPA-JSON reader, preset loading in both formats.

### M3: Easy Effects parity
- Presets: rename, delete, duplicate, import/export, Easy Effects community preset folders.
- Effects list: drag-and-drop reorder (replacing the up/down buttons).
- Apps view: playing/recording apps with per-app exclude (Easy Effects' `blocklist` key).
- Level meters and latency readout (source to be decided: LSP meter ports, or a lightweight
  `pw-record` peak reader).
- More effects with packaged plugins: filter, delay, expander, multiband gate (LSP), and echo
  cancellation on input via PipeWire's own echo-cancel module.

### M4: Surround polish
- Per-device downmix override: USB headsets that report 7.1 can be set to always use the HRIR,
  while the global setting stays the default.
- Speaker test: play a tone on each channel through the chain.
- HRIR library management: import WAVs into Soundstage's IR folder and show the channel count.

### M5: Release
- App icon (PNG sizes, symbolic), metainfo, screenshots, README, COPR repo like Superlion's.

### M6: Flatpak
- Flatpak using the Flathub LinuxAudio extensions for Calf, MDA and bs2b, which enables Bass Enhancer,
  Exciter, Bass Loudness and Crossfeed. Bundle filter-chain and lilv inside the sandbox.

## Risks and open questions
- Passive-link behaviour and graph duplication (M2) are the biggest unknowns; if either fails,
  the fallback is non-passive playback, at the cost of keeping devices awake.
- Easy Effects 8 may change its preset keys (for example, IR paths); `plugins.py` mappings may need
  per-version aliases.
- WirePlumber restart on rename is disruptive; there's no runtime API to change a node's description.

## Verification for M1
- `py_compile` everything. Build output and input configs from the real presets and run each
  briefly with `pipewire -c` against nonexistent targets, so audio is unaffected.
- Parse an existing rename file, generate the new file somewhere temporary, and parse it back.
- Headless UI check under Broadway with a private `XDG_RUNTIME_DIR`: Input tab, header binding
  when switching pages, the conflict banner with a simulated node, and the rename dialog.
- WirePlumber restarts and real renames wait for M2.
