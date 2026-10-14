#!/bin/sh
# Install Spotify Soloist for the current user (no sudo): the binary, the
# service that runs it at boot as "Baja", and the daily updater.
# Run deploy/spotify/set-spotify-key.sh first, or after; it starts once the
# key exists.
set -e
HERE=$(cd "$(dirname "$0")" && pwd)
"$HERE/update-soloist.sh"
mkdir -p "$HOME/.config/systemd/user" "$HOME/.local/share/soloist" "$HOME/.cache/soloist"
cp "$HERE"/baja-soloist.service "$HERE"/baja-soloist-update.service \
   "$HERE"/baja-soloist-update.timer "$HOME/.config/systemd/user/"
systemctl --user daemon-reload
systemctl --user enable --now baja-soloist-update.timer
systemctl --user enable baja-soloist.service
if [ -f "$HOME/.config/baja-os/soloist.env" ]; then
    systemctl --user restart baja-soloist.service
    echo "Spotify player running as \"Baja\"."
else
    echo "Now run deploy/spotify/set-spotify-key.sh to add your API key."
fi
