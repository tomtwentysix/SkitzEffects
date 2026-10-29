# Cargo fetches crates during the build, so the COPR project needs internet access during builds.
%global debug_package %{nil}

Name:           ladspa-deepfilternet
Version:        0.5.6
Release:        1%{?dist}
Summary:        DeepFilterNet noise suppression as a LADSPA plugin
License:        MIT OR Apache-2.0
URL:            https://github.com/Rikorose/DeepFilterNet
Source0:        %{url}/archive/v%{version}/DeepFilterNet-%{version}.tar.gz
ExclusiveArch:  x86_64 aarch64

BuildRequires:  cargo
BuildRequires:  rust
BuildRequires:  gcc
BuildRequires:  make

%description
DeepFilterNet removes background noise from speech in real time with a small
neural network. This package provides its LADSPA plugin, with the DeepFilterNet3
model built in, for hosts such as PipeWire's filter-chain and Easy Effects.

%prep
%autosetup -n DeepFilterNet-%{version}

%build
# The 0.5.6 lockfile pins a time crate that newer Rust cannot compile.
cargo update -p time
cargo build --release -p deep-filter-ladspa

%install
install -Dpm0755 target/release/libdeep_filter_ladspa.so %{buildroot}%{_libdir}/ladspa/libdeep_filter_ladspa.so

%files
%license LICENSE-MIT LICENSE-APACHE
%doc README.md
%dir %{_libdir}/ladspa
%{_libdir}/ladspa/libdeep_filter_ladspa.so

%changelog
* Thu Oct 29 2026 SolarFlare Developments <tom@solarflareit.co.uk> - 0.5.6-1
- Initial package
