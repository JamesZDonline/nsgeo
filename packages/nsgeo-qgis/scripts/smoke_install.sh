#!/usr/bin/env bash
# Install a built nsgeo_qgis zip into a real QGIS profile and run the smoke
# probe under xvfb. Meant for a QGIS container (CI, or in_qgis_docker.sh).
#
#   packages/nsgeo-qgis/scripts/smoke_install.sh dist/nsgeo_qgis-0.1.0.zip
#
# Exits with QGIS's status: 0 only when every probe check is true.
set -euo pipefail

if [ "$#" -ne 1 ]; then
    echo "usage: $0 ZIP" >&2
    exit 2
fi
zip=$(realpath "$1")
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

if ! command -v xvfb-run >/dev/null 2>&1; then
    apt-get update -qq
    apt-get install -y -qq xvfb xauth
fi

major=$(python3 -c 'from qgis.core import Qgis; print(Qgis.QGIS_VERSION_INT // 10000)')
plugins="$HOME/.local/share/QGIS/QGIS$major/profiles/default/python/plugins"
mkdir -p "$plugins"
rm -rf "${plugins:?}/nsgeo_qgis"
python3 -m zipfile -e "$zip" "$plugins"

# QGIS refuses to start on the offscreen platform without an X server, so the
# probe runs against xvfb's display instead.
unset QT_QPA_PLATFORM
export NSGEO_SMOKE_OUT=/tmp/nsgeo-smoke.json
rm -f "$NSGEO_SMOKE_OUT"

status=0
timeout 300 xvfb-run -a qgis --nologo --code "$here/smoke_probe.py" || status=$?

if [ -f "$NSGEO_SMOKE_OUT" ]; then
    cat "$NSGEO_SMOKE_OUT"
    echo
else
    echo "smoke probe wrote no result (QGIS exit status $status)" >&2
    [ "$status" -ne 0 ] || status=1
fi
exit "$status"
