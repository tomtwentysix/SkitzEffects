Name:           skitz-effects
Version:        0.1.0
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
* Wed Oct 28 2026 Tom <tom@solarflareit.co.uk> - 0.1.0-1
- First release: Easy Effects presets on output and input, per-device presets, 5.1 and 7.1 input with passthrough or HRIR downmixing, system-wide device names, and a setup wizard.
