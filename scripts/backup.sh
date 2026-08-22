#!/bin/sh
set -eu
cd "$(dirname "$0")/.."; stamp=$(date +%Y%m%d-%H%M%S); out="backups/jarvis-home-$stamp.tar.gz"; mkdir -p backups
items="data"
[ -d config ] && items="$items config"
tar -czf "$out" $items
echo "$out (secrets in .env intentionally excluded)"

