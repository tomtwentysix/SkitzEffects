Name:           soundstage
Version:        0.1.0
Release:        1%{?dist}
Summary:        Audio effects with surround sound and HRIR downmixing
License:        GPL-3.0-or-later
Vendor:         SolarFlare Developments
Source0:        %{name}-%{version}.tar.gz
BuildArch:      noarch

BuildRequires:  desktop-file-utils

Requires:       python3
Requires:       python3-gobject-base
Requires:       gtk4
Requires:       libadwaita
Requires:       pipewire
Requires:       pipewire-utils
Requires:       wireplumber
Requires:       pipewire-module-filter-chain-lv2
Requires:       lsp-plugins-lv2
Requires:       lv2-zam-plugins
Requires:       lv2-mdala-plugins

%description
Soundstage applies Easy Effects presets to everything you play and record,
switches presets when you change device, and plays 5.1 and 7.1 sound on any
device: surround devices get every channel, and stereo devices get a binaural
downmix through an HRIR. PipeWire's filter-chain and the LSP and ZAM plugins do
the processing.

%prep
%autosetup

%build

%install
install -d %{buildroot}%{_datadir}/%{name}
cp -a soundstage %{buildroot}%{_datadir}/%{name}/
install -Dm755 packaging/soundstage %{buildroot}%{_bindir}/soundstage
desktop-file-install --dir=%{buildroot}%{_datadir}/applications data/uk.co.solarflareit.Soundstage.desktop
cp -a data/icons %{buildroot}%{_datadir}/

%check
desktop-file-validate %{buildroot}%{_datadir}/applications/uk.co.solarflareit.Soundstage.desktop

%files
%license LICENSE
%doc README.md
%{_bindir}/soundstage
%{_datadir}/%{name}/
%{_datadir}/applications/uk.co.solarflareit.Soundstage.desktop
%{_datadir}/icons/hicolor/scalable/apps/uk.co.solarflareit.Soundstage.svg
%{_datadir}/icons/hicolor/symbolic/apps/uk.co.solarflareit.Soundstage-symbolic.svg

%changelog
* Wed Oct 28 2026 Tom <tom@solarflareit.co.uk> - 0.1.0-1
- First release: Easy Effects presets on output and input, per-device presets, 5.1 and 7.1 input with passthrough or HRIR downmixing, system-wide device names, and a setup wizard.
