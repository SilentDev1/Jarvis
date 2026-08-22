#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
[ -f .env ] || cp .env.example .env
mkdir -p data/media logs run
echo "Setup complete. Edit .env, especially JARVIS_ADMIN_TOKEN and camera settings."

