#!/usr/bin/env bash
# Run a command inside a QGIS Docker image against a throwaway copy of this
# worktree.
#
#   packages/nsgeo-qgis/scripts/in_qgis_docker.sh IMAGE CMD...
#   packages/nsgeo-qgis/scripts/in_qgis_docker.sh qgis/qgis:4.2 \
#       python3 -m pytest packages/nsgeo-qgis/tests -q -p no:cacheprovider
#
# The worktree is mounted read-only at /src and copied to /work (minus the
# virtualenvs), so nothing the tests write reaches the checkout. Directories
# that the real-data symlinks under packages/nsgeo-core/tests/data/local point
# into are mounted read-only at the same absolute path, so the links resolve.
# Exits with CMD's status.
set -euo pipefail

if [ "$#" -lt 2 ]; then
    echo "usage: $0 IMAGE CMD..." >&2
    exit 2
fi
image=$1
shift

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)

mounts=(-v "$root:/src:ro")
seen=()
for link in "$root"/packages/nsgeo-core/tests/data/local/*; do
    [ -L "$link" ] || continue
    target=$(readlink -f "$link")
    dir=$(dirname "$target")
    case " ${seen[*]:-} " in *" $dir "*) continue ;; esac
    seen+=("$dir")
    mounts+=(-v "$dir:$dir:ro")
done

exec docker run --rm \
    -e QT_QPA_PLATFORM=offscreen \
    -e QGIS_PREFIX_PATH=/usr \
    -e PYTHONDONTWRITEBYTECODE=1 \
    -e LANG=C.UTF-8 \
    "${mounts[@]}" \
    "$image" bash -c '
        set -euo pipefail
        mkdir /work
        shopt -s dotglob
        for entry in /src/*; do
            case "${entry##*/}" in .venv | .venv-qgis) continue ;; esac
            cp -a "$entry" /work/
        done
        cd /work
        python3 -m pip install -q --break-system-packages --root-user-action=ignore pytest
        exec "$@"
    ' bash "$@"
