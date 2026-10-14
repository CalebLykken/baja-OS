#!/bin/sh
# Install the Baja OS equalizer for this user (no sudo): the PipeWire config
# and a user service that runs it at boot, in front of the speakers. Safe to
# re-run. Remove with: install-eq.sh --remove
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
CONF="$HOME/.config/pipewire"
UNITS="$HOME/.config/systemd/user"

if [ "${1:-}" = "--remove" ]; then
    systemctl --user disable --now baja-eq.service 2>/dev/null || true
    rm -f "$UNITS/baja-eq.service" "$CONF/baja-eq.conf"
    systemctl --user daemon-reload
    echo "Equalizer removed; audio goes straight to the output."
    exit 0
fi

mkdir -p "$CONF" "$UNITS"
cp "$HERE/baja-eq.conf" "$CONF/baja-eq.conf"
cp "$HERE/baja-eq.service" "$UNITS/baja-eq.service"
systemctl --user daemon-reload
systemctl --user enable baja-eq.service
systemctl --user restart baja-eq.service
echo "Equalizer running (the dashboard sets its bands)."
