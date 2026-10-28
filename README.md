# Soundstage

Audio effects for PipeWire, laid out like Easy Effects and using its presets, for
both playback and microphones, with 5.1 and 7.1 input. Surround devices receive
every channel; stereo devices get a binaural downmix through a 14-channel HeSuVi
HRIR. Devices can be renamed system-wide from the Devices page.

Soundstage does no audio processing of its own. PipeWire's filter-chain hosts the
LSP and ZAM LV2 plugins that Easy Effects uses, and its convolver handles impulse
responses and the HRIR.

## Requirements

- PipeWire with WirePlumber, `pipewire-utils` and `pipewire-module-filter-chain-lv2`
- `lsp-plugins-lv2` and `lv2-zam-plugins`
- GTK 4, libadwaita and PyGObject

The RPM depends on all of these. When running from a checkout, the setup wizard
installs any that are missing.

## Running from a checkout

    ./run-dev.sh

## Building the RPM

    packaging/build-rpm.sh

## Effects not yet available

Crossfeed needs the bs2b LV2 plugin, which Fedora does not package, and the Calf
effects (Bass Enhancer, Exciter and others) are not mapped yet. Their settings stay
in the preset.
