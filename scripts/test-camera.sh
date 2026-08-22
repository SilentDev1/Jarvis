#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
[ -x .venv/bin/python ] || { echo "FAIL Python environment missing; run setup.sh"; exit 1; }
exec .venv/bin/python scripts/test_camera_live.py

