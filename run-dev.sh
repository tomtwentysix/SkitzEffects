#!/bin/sh
# Runs Skitz Effects from this checkout as a separate app with its own settings,
# so the installed copy is left alone.
cd "$(dirname "$0")" && SKITZ_DEVEL=1 exec python3 -m skitz_effects "$@"
