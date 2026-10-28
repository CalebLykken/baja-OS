#!/bin/sh
# Put a finished map build in place. install-map.sh builds in
# $MAPS_DIR/.new, on the same disk as the live files, so every step here is a
# rename: the dashboard reads the old file or the new one, never half of
# one. (From another disk `mv` copies, and the copy is read half done.)
#
#   deploy/maps/swap-in.sh NEW_DIR MAPS_DIR
#
# Whatever NEW_DIR holds of these goes in, in this order:
#   fonts/ sprites/    swapped as folders: the old one is renamed aside, the
#                      new one renamed in, then the old one deleted
#   places.sqlite      the search index
#   region.json        what the map covers
#   basemap.pmtiles    last: the dashboard counts the map as installed once
#                      this exists, so a first install is never seen half
#                      done, and the new tiles arrive after what draws them
set -eu

new=${1:?folder with the new build}
live=${2:?live maps folder}

swap_dir() {
    [ -d "$new/$1" ] || return 0
    rm -rf "$live/$1.old"
    if [ -d "$live/$1" ]; then mv "$live/$1" "$live/$1.old"; fi
    if ! mv "$new/$1" "$live/$1"; then
        if [ -d "$live/$1.old" ]; then mv "$live/$1.old" "$live/$1"; fi
        echo "Couldn't move $1 into place" >&2
        exit 1
    fi
    rm -rf "$live/$1.old"
}

swap_file() {
    [ -f "$new/$1" ] || return 0
    mv -f "$new/$1" "$live/$1"
}

swap_dir fonts
swap_dir sprites
swap_file places.sqlite
swap_file region.json
swap_file basemap.pmtiles
