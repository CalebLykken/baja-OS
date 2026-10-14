#!/bin/sh
# Offline routing: Valhalla (from the pyvalhalla wheel, so no sudo) with a
# road graph built from OpenStreetMap, run as a small local service the
# dashboard asks for routes. Works with no signal. Safe to re-run; it
# rebuilds the roads from a fresh extract.
#
#   deploy/maps/install-routing.sh       # Washington: 365 MB download, ~30-60 min to build on a Pi 5
#   EXTRACT=north-america/us/oregon deploy/maps/install-routing.sh
#
# Everything goes in $BAJA_ROUTING_DIR (default ~/.local/share/baja-os/valhalla):
#   venv/            Valhalla 3.9.0 and pyosmium 4.3.1 (pinned, hash-checked)
#   osm/             the OpenStreetMap extract it was built from (kept)
#   tiles/           the road graph
#   valhalla.json    its configuration (listens on 127.0.0.1:8002 only)
set -eu

DIR="${BAJA_ROUTING_DIR:-$HOME/.local/share/baja-os/valhalla}"
EXTRACT="${EXTRACT:-north-america/us/washington}"
PORT=8002
VERSION=3.9.0

case "$(uname -s)-$(uname -m)" in
    Linux-aarch64)
        HASH=efc9a8f7098cc9d128b065a59cec386a0c6507c7eb690ef91421fbe5e57ed212
        # pyosmium for the Pi's Python 3.13, to read addresses for search
        OSMIUM="osmium==4.3.1 --hash=sha256:88687d206a3102c31ccb1792cecad2e3f4fe3204e33cb9154a39828226876249" ;;
    Darwin-arm64)
        HASH=e4ed269fc0ffd2d3e69460ca9ba0443309845b2bfdf582d8975af88c6933cd97
        OSMIUM="" ;;
    *) echo "No pinned Valhalla build for $(uname -s) $(uname -m)" >&2; exit 1 ;;
esac

mkdir -p "$DIR/osm"

# ---- Valhalla itself ------------------------------------------------------------
if ! "$DIR/venv/bin/python" -c "import valhalla" 2>/dev/null; then
    echo "Installing Valhalla $VERSION..."
    python3 -m venv "$DIR/venv"
    req=$(mktemp)
    printf 'pyvalhalla==%s --hash=sha256:%s\n' "$VERSION" "$HASH" > "$req"
    "$DIR/venv/bin/pip" install -q --only-binary=:all: --no-deps --require-hashes -r "$req"
    rm -f "$req"
fi
BIN=$("$DIR/venv/bin/python" -c "import valhalla, os; print(os.path.join(os.path.dirname(valhalla.__file__), 'bin'))")

# ---- the OpenStreetMap extract ------------------------------------------------------
name=$(basename "$EXTRACT")
pbf="$DIR/osm/$name-latest.osm.pbf"
url="https://download.geofabrik.de/$EXTRACT-latest.osm.pbf"
md5of() { if command -v md5sum >/dev/null; then md5sum "$1" | cut -d' ' -f1; else md5 -q "$1"; fi; }
want=$(curl -fsSL --retry 3 "$url.md5" | cut -d' ' -f1)
if [ -f "$pbf" ] && [ "$(md5of "$pbf")" = "$want" ]; then
    echo "Already have the latest $name roads"
else
    echo "Downloading $name roads from Geofabrik..."
    curl -fsSL --retry 3 -o "$pbf.part" "$url"
    if [ "$(md5of "$pbf.part")" != "$want" ]; then
        echo "Checksum mismatch for $url" >&2
        exit 1
    fi
    mv "$pbf.part" "$pbf"
fi

# ---- configuration ------------------------------------------------------------------
rm -rf "$DIR/tiles.new"
mkdir -p "$DIR/tiles.new"
"$DIR/venv/bin/python" - "$DIR" "$PORT" <<'EOF'
import json, sys, valhalla
d, port = sys.argv[1], sys.argv[2]
# get_config insists both paths exist; the extract setting is dropped below.
c = valhalla.get_config(tile_extract=f"{d}/tiles.new", tile_dir=f"{d}/tiles.new")
c["mjolnir"]["tile_dir"] = f"{d}/tiles"            # where the service reads them
c["mjolnir"].pop("tile_extract", None)
c["mjolnir"]["logging"] = {"type": "std_out", "color": False, "long_request": 2000.0}
c["httpd"]["service"]["listen"] = f"tcp://127.0.0.1:{port}"   # this Pi only
json.dump(c, open(f"{d}/valhalla.json", "w"), indent=1)
c["mjolnir"]["tile_dir"] = f"{d}/tiles.new"          # where this build writes them
json.dump(c, open(f"{d}/build.json", "w"), indent=1)
EOF

# ---- the road graph ---------------------------------------------------------------
echo "Building the road graph (this takes a while)..."
threads=$(( $(getconf _NPROCESSORS_ONLN) > 1 ? $(getconf _NPROCESSORS_ONLN) - 1 : 1 ))
"$BIN/valhalla_build_tiles" -c "$DIR/build.json" -j "$threads" "$pbf"
rm -f "$DIR/build.json"

# Swap the new graph in while the service is stopped.
if [ "$(uname -s)" = Linux ]; then
    systemctl --user stop baja-valhalla.service 2>/dev/null || true
fi
rm -rf "$DIR/tiles.old"
[ -d "$DIR/tiles" ] && mv "$DIR/tiles" "$DIR/tiles.old"
mv "$DIR/tiles.new" "$DIR/tiles"
rm -rf "$DIR/tiles.old"

# ---- the service ------------------------------------------------------------------
if [ "$(uname -s)" = Linux ]; then
    UNITS="$HOME/.config/systemd/user"
    mkdir -p "$UNITS"
    cat > "$UNITS/baja-valhalla.service" <<UNIT
[Unit]
Description=Baja OS offline routing (Valhalla)

[Service]
ExecStart=$BIN/valhalla_service $DIR/valhalla.json 2
Restart=on-failure
RestartSec=3
Nice=5

[Install]
WantedBy=default.target
UNIT
    systemctl --user daemon-reload
    systemctl --user enable baja-valhalla.service
    systemctl --user restart baja-valhalla.service
    echo "Routing running on 127.0.0.1:$PORT"
else
    echo "Built. Run it with: $BIN/valhalla_service $DIR/valhalla.json 2"
fi
du -sh "$DIR/tiles" | sed 's/^/Road graph: /'

# ---- street addresses for search ------------------------------------------------------
MAPS_DIR="${BAJA_MAPS_DIR:-$HOME/.local/share/baja-os/maps}"
if [ -n "$OSMIUM" ] && [ -f "$MAPS_DIR/region.json" ]; then
    if ! "$DIR/venv/bin/python" -c "import osmium" 2>/dev/null; then
        req=$(mktemp)
        printf '%s\n' "$OSMIUM" > "$req"
        "$DIR/venv/bin/pip" install -q --only-binary=:all: --no-deps --require-hashes -r "$req"
        rm -f "$req"
    fi
    echo "Indexing street addresses for search..."
    "$DIR/venv/bin/python" "$(dirname "$0")/build_addresses.py" "$pbf" "$MAPS_DIR"
    echo "Finding traffic lights and stop signs for the map..."
    "$DIR/venv/bin/python" "$(dirname "$0")/build_controls.py" "$pbf" "$MAPS_DIR"
fi
