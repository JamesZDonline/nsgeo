#!/usr/bin/env bash
# Runs the plugin's QGIS tier in .venv-qgis, offscreen.
#
#   qgis_tests.sh <pytest args>        a narrower run, at once, from where you are:
#       qgis_tests.sh packages/nsgeo-qgis/tests/qgis/test_plugin_slices_dock.py
#       qgis_tests.sh packages/nsgeo-qgis/tests/qgis -m real_data
#   qgis_tests.sh full [pytest args]   the whole tier, one whole run at a time
#
# CI runs the whole tier on QGIS 3.44 and 4.2 on every push, so a whole local run
# is rarely needed (see the README's Tests section). When one is, `full` waits
# for any other `full` run on this machine, from any worktree, to finish first:
# several at once on four cores each take longer than running them in turn.
set -euo pipefail

if [[ $# -eq 0 ]]; then
    sed -n '2,8p' "$0" | sed 's/^# \{0,1\}//' >&2
    exit 2
fi

# The venvs live in the main checkout; worktrees under .worktrees/ share them.
main=$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")
python=${NSGEO_QGIS_PYTHON:-$main/.venv-qgis/bin/python}

run() {
    # exec: pytest inherits fd 9, so a `full` run holds the lock until it exits.
    QT_QPA_PLATFORM=offscreen exec "$python" -m pytest -p no:xonsh "$@"
}

if [[ $1 != full ]]; then
    run "$@"
fi
shift

top=$(git rev-parse --show-toplevel)
lock=${XDG_RUNTIME_DIR:-/tmp}/nsgeo-qgis-full-tests.lock
exec 9>>"$lock"
if ! flock -n 9; then
    echo "qgis_tests.sh: waiting for the whole run already going: $(cat "$lock")" >&2
    flock 9
fi
printf '%s, started %s\n' "$top" "$(date '+%H:%M')" >"$lock"
cd "$top"
run packages/nsgeo-qgis/tests/qgis -q "$@"
