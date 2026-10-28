# Soundstage

Audio effects for PipeWire, laid out like Easy Effects and using its presets, with
5.1 and 7.1 input. Surround devices receive every channel; stereo devices get a
binaural downmix through a 14-channel HeSuVi HRIR.

Soundstage does no audio processing of its own. PipeWire's filter-chain hosts the
LSP and ZAM LV2 plugins that Easy Effects uses, and its convolver handles impulse
responses and the HRIR.

## Requirements

- PipeWire with WirePlumber, `pipewire-utils` and `pipewire-module-filter-chain-lv2`
- `lsp-plugins-lv2` and `lv2-zam-plugins`
- GTK 4, libadwaita and PyGObject

The setup wizard installs any missing packages.

## Running from a checkout

    ./run-dev.sh

## Effects not yet available

Bass Enhancer, Exciter, Bass Loudness and Crossfeed need Calf, MDA and bs2b LV2
plugins, which Fedora does not package. Their settings stay in the preset.
