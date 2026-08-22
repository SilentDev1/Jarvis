#!/bin/sh
set -eu
cd "$(dirname "$0")/.."; . .venv/bin/activate; python -m pytest -q

