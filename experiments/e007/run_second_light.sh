#!/usr/bin/env bash
set -euo pipefail

# Historical entry point retained for compatibility; the old single-cell
# Second Light dispatch is superseded by the guarded matched A-D pilot.
exec bash "$(dirname "$0")/run_factorial_pilot.sh" "$@"
