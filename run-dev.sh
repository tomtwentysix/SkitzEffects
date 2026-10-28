#!/bin/sh
# Runs Soundstage from this checkout as a separate app with its own settings,
# so the installed copy is left alone.
cd "$(dirname "$0")" && SOUNDSTAGE_DEVEL=1 exec python3 -m soundstage "$@"
