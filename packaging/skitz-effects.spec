Name:           skitz-effects
Version:        1.0.16
Release:        1%{?dist}
Summary:        Audio effects with surround sound and HRIR downmixing
License:        GPL-3.0-or-later
Vendor:         SolarFlare Developments
Source0:        %{name}-%{version}.tar.gz
BuildArch:      noarch
Obsoletes:      soundstage <= 0.1.0

BuildRequires:  desktop-file-utils

Requires:       python3
Requires:       python3-gobject-base
Requires:       python3-numpy
Requires:       gtk4
Requires:       libadwaita
Requires:       pipewire
Requires:       pipewire-utils
Requires:       wireplumber
Requires:       pipewire-module-filter-chain-lv2
Requires:       lsp-plugins-lv2
Requires:       lv2-zam-plugins
Requires:       lv2-mdala-plugins
Recommends:     ladspa-deepfilternet

%description
Skitz Effects applies Easy Effects presets to everything you play and record,
switches presets when you change device, and plays 5.1 and 7.1 sound on any
device: surround devices get every channel, and stereo devices get a binaural
downmix through an HRIR. PipeWire's filter-chain and the LSP and ZAM plugins do
the processing.

%prep
%autosetup

%build

%install
install -d %{buildroot}%{_datadir}/%{name}
cp -a skitz_effects %{buildroot}%{_datadir}/%{name}/
install -Dm755 packaging/skitz-effects %{buildroot}%{_bindir}/skitz-effects
desktop-file-install --dir=%{buildroot}%{_datadir}/applications data/uk.co.solarflareit.SkitzEffects.desktop
cp -a data/icons %{buildroot}%{_datadir}/
install -Dm644 packaging/skitz-effects-copr.repo %{buildroot}%{_datadir}/dnf5/repos.override.d/50-skitz-effects.repo

%check
desktop-file-validate %{buildroot}%{_datadir}/applications/uk.co.solarflareit.SkitzEffects.desktop

%files
%license LICENSE
%doc README.md
%{_bindir}/skitz-effects
%{_datadir}/%{name}/
%{_datadir}/applications/uk.co.solarflareit.SkitzEffects.desktop
%{_datadir}/icons/hicolor/scalable/apps/uk.co.solarflareit.SkitzEffects.svg
%{_datadir}/icons/hicolor/symbolic/apps/uk.co.solarflareit.SkitzEffects-symbolic.svg
%{_datadir}/dnf5/repos.override.d/50-skitz-effects.repo

%changelog
* Tue Nov 10 2026 Tom <tom@solarflareit.co.uk> - 1.0.16-1
- Choosing an output device in Skitz Effects sticks instead of jumping back to the previous one.

* Tue Nov 10 2026 Tom <tom@solarflareit.co.uk> - 1.0.15-1
- Impulse responses and HRIRs can be imported from the Convolver effect, Devices → Surround and the
  setup wizard. The file is copied into the Easy Effects impulse response folder, so both apps see it.
- The Devices page lists only connected devices; settings for the others are kept.

* Tue Nov 10 2026 Tom <tom@solarflareit.co.uk> - 1.0.14-1
- Devices → Surround has Channel Levels, a level for each surround channel before the HRIR, such as
  a louder centre for dialogue or a quieter subwoofer. Changes apply while audio plays.

* Sun Nov 08 2026 Tom <tom@solarflareit.co.uk> - 1.0.13-1
- The microphone effects run at 48 kHz whatever rate the output runs at, so Deep Noise Remover,
  which supports only 48 kHz, no longer silences the microphone.
- A chain with no effects, or with effects switched off, passes audio through instead of silence.

* Sun Nov 08 2026 Tom <tom@solarflareit.co.uk> - 1.0.12-1
- Clicking a peak meter in the status bar chooses how many channels it shows (mono, stereo, 5.1 or
  7.1) and where it measures: before the effects, after the surround downmix or any effect, or at
  the final output. Both meters remember their choices.
- Each step of the effect chains now runs as a filter of its own, so the audio between steps can be
  measured. The steps still run in the one realtime process.

* Sun Nov 08 2026 Tom <tom@solarflareit.co.uk> - 1.0.11-1
- Newly added effects start with Easy Effects' own default settings, and settings missing from a
  preset read as Easy Effects would read them rather than as the control's minimum. The equalizer
  keeps its 10 octave bands.
- The Low-Pass sidechain mode saved by Easy Effects now reaches the plugin.

* Sun Nov 08 2026 Tom <tom@solarflareit.co.uk> - 1.0.10-1
- The effects no longer slow to a crawl when a game's sound fades out. The near-silent tail reached the
  HRIR as denormal numbers, which kept the realtime chain busy until the kernel stopped it and Skitz
  fell back to a lower priority that pops under load. Every chain input now carries a tiny offset that
  keeps those numbers out of the slow range.

* Sun Nov 08 2026 Tom <tom@solarflareit.co.uk> - 1.0.9-1
- Every app plays through the one effects chain again; the separate stereo sink is gone, as
  WirePlumber sometimes failed to move a playing stream onto it.
- Stereo and mono apps play only on the front speakers, with PipeWire's upmix turned off for them.

* Fri Nov 06 2026 Tom <tom@solarflareit.co.uk> - 1.0.8-1
- The effects run at realtime priority again, as Easy Effects does, so they no longer miss cycles and
  pop while a game keeps every core busy. A chain the kernel stops for overrunning its realtime
  budget comes back at nice -11.
- A stereo stream that WirePlumber fails to move onto the stereo path is sent again, instead of
  staying upmixed on the surround chain.

* Fri Nov 06 2026 Tom <tom@solarflareit.co.uk> - 1.0.7-1
- The effects run at a raised normal priority (nice -11) instead of realtime, so they can no longer
  hold up a game's threads or be stopped by the kernel for overrunning their realtime budget.
- An effects chain restarts by itself when its device changes sample rate, instead of going silent.
- Add the Expander effect, using the LSP sidechain expander and Easy Effects' expander settings.

* Sun Nov 01 2026 Tom <tom@solarflareit.co.uk> - 1.0.6-1
- Stereo apps take their own path through the effects, without the HRIR or a surround mix; 7.1 apps
  still go through the HRIR on stereo devices.
- The HRIR convolvers use the part of the HRIR that holds its sound, spread evenly over each cycle,
  which stops the crackling and dropouts they caused.

* Sun Nov 01 2026 Tom <tom@solarflareit.co.uk> - 1.0.5-1
- An effects chain killed for overrunning its realtime budget restarts at normal priority, so the
  effects keep running when a game is alt-tabbed.
- The meters pause while the window is minimised or covered, such as by a fullscreen game.
- Removed the Disable Suspend and Sample Rate device settings.

* Sun Nov 01 2026 Tom <tom@solarflareit.co.uk> - 1.0.4-1
- The launcher always runs the installed code, whatever folder it is started from.
- Messages such as effects chain restarts reach the system journal as they happen.

* Sun Nov 01 2026 Tom <tom@solarflareit.co.uk> - 1.0.3-1
- Every app sees the surround layout: the default output is Skitz Effects' sink, named after the device it plays through.
- Streams aimed at Easy Effects, such as loopbacks set up for it, go through Skitz Effects.
- dnf checks the COPR for updates every 4 hours instead of 48.

* Sun Nov 01 2026 Tom <tom@solarflareit.co.uk> - 1.0.2-1
- Preferences: start at login, start minimised, keep running in the background, show in the system tray.
- Tray icon with Open, an effects switch and Quit (needs a StatusNotifier host, such as GNOME's AppIndicator extension).
- The Mixer shows each app's channel layout, such as Stereo, 5.1 or 7.1, and follows format changes.
- Every app's sound goes through the effects unless it is switched off in the Mixer.

* Sat Oct 31 2026 Tom <tom@solarflareit.co.uk> - 1.0.1-1
- While the chosen device is unplugged, use the same stand-in device that GNOME shows.

* Thu Oct 29 2026 Tom <tom@solarflareit.co.uk> - 1.0.0-1
- Before/after spectrum, peak meters and Pre-Gain sliders, and a graphical parametric equalizer.
- Mixer page with per-app volume and a switch to leave apps out of the effects.
- The real device stays the default, as in Easy Effects; app streams are moved through the effects.
- Devices page with per-device settings: name, preset, input channel, Disable Suspend and sample rate.
- Bass Loudness through the MDA plugins, and Deep Noise Remover through DeepFilterNet.
- Renamed from Soundstage; settings move across on first start.

* Wed Oct 28 2026 Tom <tom@solarflareit.co.uk> - 0.1.0-1
- First release: Easy Effects presets on output and input, per-device presets, 5.1 and 7.1 input with passthrough or HRIR downmixing, system-wide device names, and a setup wizard.
