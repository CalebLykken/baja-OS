#!/bin/sh
# Copy this checkout to the Pi and restart the dashboard.
#
#   deploy/push.sh                 # to baja.local
#   deploy/push.sh pi@10.0.0.202   # anywhere else
#
# Stamps the version (commit and date, "+ changes" if uncommitted) so
# Settings > System shows what's running.
set -eu
HOST="${1:-$(id -un)@baja.local}"
cd "$(dirname "$0")/.."

version=$(git log -1 --format='%h, %cd' --date=format:'%-d %b %Y')
git diff --quiet HEAD -- . 2>/dev/null || version="$version + changes"

rsync -a --delete-after \
    --exclude .git --exclude docs --exclude __pycache__ --exclude .claude \
    --exclude .venv --exclude venv --exclude .version \
    ./ "$HOST:baja-OS/"
ssh "$HOST" "printf '%s\n' '$version' > ~/baja-OS/.version && sudo -n systemctl restart baja-os && sleep 4 && systemctl is-active baja-os"
echo "Pushed $version to $HOST"
