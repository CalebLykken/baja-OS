#!/bin/sh
# Store the Spotify app's ID and secret on the Pi (never in git), so the
# dashboard can search. Make the app at https://developer.spotify.com/dashboard,
# ticking "Web API"; any redirect URI will do, since search has no sign-in.
set -e
mkdir -p "$HOME/.config/baja-os"
printf 'Paste the Client ID: '
read -r ID
printf 'Paste the Client secret (input hidden): '
stty -echo; read -r SECRET; stty echo; echo
[ -n "$ID" ] && [ -n "$SECRET" ] || { echo "Both are needed." >&2; exit 1; }
umask 077
printf 'SPOTIFY_CLIENT_ID=%s\nSPOTIFY_CLIENT_SECRET=%s\n' "$ID" "$SECRET" > "$HOME/.config/baja-os/spotify-search.env"
echo "Saved to ~/.config/baja-os/spotify-search.env. Search is ready: no restart needed."
