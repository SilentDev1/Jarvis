#!/bin/sh
set -eu
cd "$(dirname "$0")/.."; ./scripts/stop.sh; ./scripts/start.sh

