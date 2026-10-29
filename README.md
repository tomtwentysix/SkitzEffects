# Skitz Effects

Audio effects for PipeWire, laid out like Easy Effects and using its presets, for
both playback and microphones, with 5.1 and 7.1 input. Surround devices receive
every channel; stereo devices get a binaural downmix through a 14-channel HeSuVi
HRIR. Devices can be renamed system-wide from the Devices page.

Skitz Effects does no audio processing of its own. PipeWire's filter-chain hosts the
LSP and ZAM LV2 plugins that Easy Effects uses, and its convolver handles impulse
responses and the HRIR.

Skitz Effects is not affiliated with Easy Effects or its developers.

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
Deep Noise Remover uses DeepFilterNet's LADSPA plugin, which comes from the same COPR.

## Running from a checkout

    ./run-dev.sh

## Building the RPM

    packaging/build-rpm.sh

## Effects not yet available

Crossfeed needs the bs2b LV2 plugin, which Fedora does not package, and the Calf
effects (Bass Enhancer, Exciter and others) are not mapped yet. Their settings stay
in the preset.
