#!/bin/sh
# Start the dashboard full screen on the Pi's HDMI panel, straight from the
# console (no desktop needed). Tries EGLFS (GPU) first, then the plain
# framebuffer if EGLFS can't start.
#
#   ./run.sh              # full screen
#   ./run.sh --windowed   # extra args are passed through; --windowed skips --fullscreen

cd "$(dirname "$0")" || exit 1

FULLSCREEN="--fullscreen"
if [ "$1" = "--windowed" ]; then
    FULLSCREEN=""
    shift
fi

export QT_QPA_EGLFS_HIDECURSOR=1
export QT_QPA_EGLFS_ALWAYS_SET_MODE=1
# The Waveshare 8" EDID claims a 1210x680 mm panel; give Qt the real size.
export QT_QPA_EGLFS_PHYSICAL_WIDTH=172
export QT_QPA_EGLFS_PHYSICAL_HEIGHT=108

# Point eglfs at the DRM card that actually drives the screen. On the Pi 5,
# card0 is the 3D-only GPU and the HDMI outputs live on card1; Qt would pick
# card0 and fail with "no screens available".
if [ -z "$QT_QPA_EGLFS_KMS_CONFIG" ]; then
    for status in /sys/class/drm/card*-*/status; do
        [ "$(cat "$status" 2>/dev/null)" = connected ] || continue
        card=$(basename "$(dirname "$status")")
        card=${card%%-*}
        cfg="${XDG_RUNTIME_DIR:-/tmp}/baja-kms.json"
        printf '{ "device": "/dev/dri/%s", "hwcursor": false }\n' "$card" > "$cfg"
        export QT_QPA_EGLFS_KMS_CONFIG="$cfg"
        break
    done
fi

if [ -n "$QT_QPA_PLATFORM" ]; then
    exec python3 main.py $FULLSCREEN "$@"
fi

started=$(date +%s)
QT_QPA_PLATFORM=eglfs python3 main.py $FULLSCREEN "$@"
status=$?
# Only a startup failure should fall back: Qt aborts (exit 134) when eglfs
# can't initialise. A crash later also aborts with 134 (PyQt turns an
# unhandled Python exception into an abort), so fall back only if it died
# within the first 10 s; otherwise exit and let systemd restart us.
# Ctrl-C/kill on eglfs exits 1 via Qt's console handler.
if [ $status -ne 134 ] || [ $(( $(date +%s) - started )) -gt 10 ]; then
    exit $status
fi
echo "eglfs failed (exit $status); falling back to linuxfb" >&2
QT_QPA_PLATFORM=linuxfb exec python3 main.py $FULLSCREEN "$@"
