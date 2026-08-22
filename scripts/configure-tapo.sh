#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
exec "${PYTHON:-python3}" scripts/configure_tapo.py

