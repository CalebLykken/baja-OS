#!/bin/sh
# Store your Spotify Soloist API key on the Pi (never in git). Get the key
# at https://developer.spotify.com/dashboard/soloist (needs Premium).
set -e
mkdir -p "$HOME/.config/baja-os"
printf 'Paste your Spotify Soloist API key (input hidden): '
stty -echo; read -r KEY; stty echo; echo
[ -n "$KEY" ] || { echo "No key entered." >&2; exit 1; }
umask 077
printf 'SOLOIST_KEY=%s\nSOLOIST_NAME=Baja\n' "$KEY" > "$HOME/.config/baja-os/soloist.env"
echo "Saved to ~/.config/baja-os/soloist.env"
systemctl --user restart baja-soloist.service 2>/dev/null && echo "Spotify player restarted." || true
