#!/bin/sh
# Builds the Skitz Effects RPM into dist/. Run from anywhere: packaging/build-rpm.sh
set -eu

project=$(cd "$(dirname "$0")/.." && pwd)
version=$(sed -n 's/^Version:[[:space:]]*//p' "$project/packaging/skitz-effects.spec")
work="$project/build"
top="$work/rpmbuild"

rm -rf "$work"
mkdir -p "$top/SOURCES" "$top/SPECS" "$project/dist"

stage="$work/skitz-effects-$version"
mkdir -p "$stage"
cp -a "$project/skitz_effects" "$project/data" "$project/packaging" "$project/README.md" "$project/LICENSE" "$stage/"
find "$stage" -name __pycache__ -type d -prune -exec rm -rf {} +
tar -C "$work" -czf "$top/SOURCES/skitz-effects-$version.tar.gz" "skitz-effects-$version"
cp "$project/packaging/skitz-effects.spec" "$top/SPECS/"

rpmbuild --define "_topdir $top" -bb "$top/SPECS/skitz-effects.spec"
cp "$top"/RPMS/noarch/skitz-effects-*.rpm "$project/dist/"
rm -rf "$work"
ls -1 "$project"/dist/skitz-effects-*.rpm
