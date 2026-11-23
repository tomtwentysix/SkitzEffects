# Skitz Effects

Audio effects for PipeWire, for both playback and microphones, with 5.1 and 7.1
input. It is compatible with Easy Effects presets. Surround devices receive
every channel; stereo devices get a binaural downmix through a 14-channel HeSuVi
HRIR. Devices can be renamed system-wide from the Devices page.

Skitz Effects does no audio processing of its own. PipeWire's filter-chain hosts the
LSP, ZAM, MDA and Calf LV2 plugins, its convolver handles impulse responses and the
HRIR, and its biquad filters run Crossfeed.

## Installing

On Fedora, install from [COPR](https://copr.fedorainfracloud.org/coprs/solartw/skitz-effects/).
Updates then arrive with your other system updates.

```bash
sudo dnf copr enable solartw/skitz-effects
```

```bash
sudo dnf install skitz-effects
```

The package pulls in PipeWire's filter-chain LV2 host and the LSP, ZAM and MDA plugins.
Bass Enhancer, Exciter, Stereo Tools, Reverberation and Deesser use the Calf plugins
(`lv2-calf-plugins`), and Deep Noise Remover uses DeepFilterNet's LADSPA plugin, which
comes from the same COPR. Both are installed by default and can be removed.

## Running from a checkout

    ./run-dev.sh

## Building the RPM

    packaging/build-rpm.sh
