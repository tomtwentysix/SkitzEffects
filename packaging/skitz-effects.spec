Name:           skitz-effects
Version:        1.0.2
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

%changelog
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
