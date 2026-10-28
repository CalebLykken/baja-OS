#!/bin/sh
# Download the offline base map: an OpenStreetMap extract from Protomaps'
# daily world build, plus the label fonts and point-of-interest icons. After
# this the map needs no internet. Safe to re-run; it replaces the extract
# with a fresh one. It builds the new one in $MAPS_DIR/.new and renames it into
# place at the end (swap-in.sh), so the map can stay open while it runs.
#
#   deploy/maps/install-map.sh                      # Seattle area (~130 MB)
#   REGION="Washington" BBOX=-124.85,45.54,-116.91,49.01 deploy/maps/install-map.sh
#
# Files go in $BAJA_MAPS_DIR (default ~/.local/share/baja-os/maps):
#   basemap.pmtiles   the map tiles
#   region.json       what's in it (shown on the Maps page)
#   places.sqlite     names and positions for the offline search
#   fonts/, sprites/  label glyphs and icons
set -eu

MAPS_DIR="${BAJA_MAPS_DIR:-$HOME/.local/share/baja-os/maps}"
REGION="${REGION:-Seattle area}"
# Tacoma to Everett, Bremerton to North Bend.
BBOX="${BBOX:--122.70,47.10,-121.70,48.10}"
MAXZOOM="${MAXZOOM:-15}"

PMTILES_VERSION=1.31.2
ASSETS_COMMIT=028c18f713baecad011301ff7a69acc39bcc2ae7
ASSETS_SHA256=57e40e8c512bd8042d0a3a251f19d0d1c8523ad963c666c3c6643bada4dc92d0

sha256() { if command -v sha256sum >/dev/null; then sha256sum "$1"; else shasum -a 256 "$1"; fi | cut -d' ' -f1; }
fetch() {  # url, file, expected sha256
    curl -fsSL --retry 3 -o "$2" "$1"
    got=$(sha256 "$2")
    if [ "$got" != "$3" ]; then
        echo "Checksum mismatch for $1 (got $got)" >&2
        exit 1
    fi
}

# Build next to the live files, not in /tmp: that's a RAM disk on the Pi (a
# big region's extract is a gigabyte of RAM), and moving from another disk
# is a copy, so the dashboard would read a half-written map. On the same
# disk the swap at the end is a few renames. TMPDIR too, so the tools that
# make temp files (pmtiles, sqlite) use it.
mkdir -p "$MAPS_DIR"
work="$MAPS_DIR/.new"
rm -rf "$work"
mkdir "$work"
trap 'rm -rf "$work"' EXIT
trap 'exit 1' HUP INT TERM
export TMPDIR="$work"

# ---- the pmtiles tool, for cutting the extract out of the world build ----
case "$(uname -s)-$(uname -m)" in
    Linux-aarch64)
        asset="go-pmtiles_${PMTILES_VERSION}_Linux_arm64.tar.gz"
        sum=f8bd47e7ea866863489cad588fbaf2f31f42e5821f7a03f009b3769f05801cb1 ;;
    Linux-x86_64)
        asset="go-pmtiles_${PMTILES_VERSION}_Linux_x86_64.tar.gz"
        sum=3ed7dbf4ec2e6dfe5e25b6f70d1ffc932729f93c86db353bf514dd71010a312f ;;
    Darwin-arm64)
        asset="go-pmtiles-${PMTILES_VERSION}_Darwin_arm64.zip"
        sum=40528f7f616fcbf91207cd48c8fc023d213f6d86c0cbf1f748732803d1880f3d ;;
    Darwin-x86_64)
        asset="go-pmtiles-${PMTILES_VERSION}_Darwin_x86_64.zip"
        sum=1f0dc02eee6c58312dd6c509faee1b5c32f0596568af1bf51f1b034e7a88a65b ;;
    *) echo "No pmtiles build for $(uname -s) $(uname -m)" >&2; exit 1 ;;
esac
echo "Getting the pmtiles tool ($PMTILES_VERSION)..."
fetch "https://github.com/protomaps/go-pmtiles/releases/download/v${PMTILES_VERSION}/${asset}" "$work/$asset" "$sum"
case "$asset" in
    *.zip) unzip -q "$work/$asset" pmtiles -d "$work" ;;
    *)     tar -xzf "$work/$asset" -C "$work" pmtiles ;;
esac

# ---- the extract: only the tiles inside BBOX are downloaded ----
build=$(curl -fsSL --retry 3 https://build-metadata.protomaps.dev/builds.json \
        | python3 -c 'import json, sys; print(json.load(sys.stdin)[-1]["key"])')
echo "Cutting \"$REGION\" ($BBOX, zoom 0-$MAXZOOM) from build $build..."
"$work/pmtiles" extract "https://build.protomaps.com/$build" "$work/basemap.pmtiles" \
    --bbox="$BBOX" --maxzoom="$MAXZOOM" --download-threads=4
"$work/pmtiles" verify "$work/basemap.pmtiles"

# ---- fonts and icons ----
echo "Getting fonts and icons..."
fetch "https://codeload.github.com/protomaps/basemaps-assets/tar.gz/$ASSETS_COMMIT" "$work/assets.tgz" "$ASSETS_SHA256"
top="basemaps-assets-$ASSETS_COMMIT"
tar -xzf "$work/assets.tgz" -C "$work" \
    "$top/fonts/Noto Sans Regular" "$top/fonts/Noto Sans Medium" "$top/fonts/Noto Sans Italic" \
    "$top/fonts/OFL.txt" "$top/sprites/v4"

mv "$work/$top/fonts" "$work/$top/sprites" "$work/"
python3 - "$work/region.json" "$REGION" "$BBOX" "$build" "$MAXZOOM" <<'EOF'
import json, sys
path, region, bbox, build, maxzoom = sys.argv[1:]
json.dump({"region": region, "bbox": [float(v) for v in bbox.split(",")],
           "build": build.removesuffix(".pmtiles"), "maxzoom": int(maxzoom)},
          open(path, "w"), indent=2)
EOF

# The offline place search reads names out of the new map.
echo "Indexing places for search..."
APP=$(cd "$(dirname "$0")/../.." && pwd)
(cd "$APP" && python3 -m backend.places build "$work")

# All built: now put it in place (swap-in.sh says how). Until here the live
# map hasn't been touched, so a download that fails leaves it as it was.
sh "$APP/deploy/maps/swap-in.sh" "$work" "$MAPS_DIR"

echo "Done: $(du -sh "$MAPS_DIR/basemap.pmtiles" | cut -f1) map of $REGION in $MAPS_DIR"
