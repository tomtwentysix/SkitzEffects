#!/bin/sh
# Builds the Soundstage RPM into dist/. Run from anywhere: packaging/build-rpm.sh
set -eu

project=$(cd "$(dirname "$0")/.." && pwd)
version=$(sed -n 's/^Version:[[:space:]]*//p' "$project/packaging/soundstage.spec")
work="$project/build"
top="$work/rpmbuild"

rm -rf "$work"
mkdir -p "$top/SOURCES" "$top/SPECS" "$project/dist"

stage="$work/soundstage-$version"
mkdir -p "$stage"
cp -a "$project/soundstage" "$project/data" "$project/packaging" "$project/README.md" "$project/LICENSE" "$stage/"
find "$stage" -name __pycache__ -type d -prune -exec rm -rf {} +
tar -C "$work" -czf "$top/SOURCES/soundstage-$version.tar.gz" "soundstage-$version"
cp "$project/packaging/soundstage.spec" "$top/SPECS/"

rpmbuild --define "_topdir $top" -bb "$top/SPECS/soundstage.spec"
cp "$top"/RPMS/noarch/soundstage-*.rpm "$project/dist/"
rm -rf "$work"
ls -1 "$project"/dist/soundstage-*.rpm
