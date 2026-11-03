#!/bin/sh
# Download the current Soloist build from Spotify and swap it in if it
# changed. Spotify's builds expire 90 days after their build date and
# mustn't be redistributed, so each Pi fetches its own; never commit it.
set -e
URL="https://soloist-builds.spotifycdn.com/soloist_release_arm64.tar.gz"
DEST="$HOME/.local/opt/soloist"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

curl -fsSL --retry 3 --retry-all-errors --connect-timeout 20 --speed-limit 1000 --speed-time 60 -o "$TMP/soloist.tar.gz" "$URL"
tar -xzf "$TMP/soloist.tar.gz" -C "$TMP"
NEW=$(find "$TMP" -type f -name soloist | head -1)
[ -n "$NEW" ] || { echo "no soloist binary in the archive" >&2; exit 1; }
chmod +x "$NEW"
"$NEW" --version >/dev/null      # refuses to run if it's broken or expired

mkdir -p "$DEST"
if [ -f "$DEST/soloist" ] && cmp -s "$NEW" "$DEST/soloist"; then
    echo "Soloist already current: $("$DEST/soloist" --version 2>&1 | head -1)"
    exit 0
fi
install -m 755 "$NEW" "$DEST/soloist.new" && mv "$DEST/soloist.new" "$DEST/soloist"
echo "Installed Soloist: $("$DEST/soloist" --version 2>&1 | head -1)"
# No restart: the timer fires mid-drive and a restart would cut off whatever
# is streaming. The running player keeps its old binary; the new one starts
# with the next boot (or install-soloist.sh / set-spotify-key.sh).
