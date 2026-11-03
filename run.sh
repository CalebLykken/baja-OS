#!/bin/sh
# Start the dashboard full screen on the Pi's HDMI panel, straight from the
# console (no desktop needed). Tries EGLFS (GPU) first, then the plain
# framebuffer if EGLFS can't start.
#
#   ./run.sh              # full screen
#   ./run.sh --windowed   # extra args are passed through; --windowed skips --fullscreen

cd "$(dirname "$0")" || exit 1

# Before anything of the app runs: put right an update that was cut off, or
# whose version won't start. 75 means it changed the code under this very
# script, so begin again on what's there now, once: the guard must never keep
# the dashboard from starting.
sh deploy/update-guard.sh
if [ $? -eq 75 ] && [ -z "$BAJA_GUARD_RESTARTED" ]; then
    BAJA_GUARD_RESTARTED=1 exec ./run.sh "$@"
fi

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

# The DRM card driving a connected screen (card1 on the Pi 5), if any.
connected_card() {
    local s c
    for s in /sys/class/drm/card*-*/status; do
        [ "$(cat "$s" 2>/dev/null)" = connected ] || continue
        c=$(basename "$(dirname "$s")")
        echo "${c%%-*}"
        return 0
    done
    return 1
}

# Point eglfs at the DRM card that actually drives the screen. On the Pi 5,
# card0 is the 3D-only GPU and the HDMI outputs live on card1; Qt would pick
# card0 and fail with "no screens available". Wait up to 30 s for the screen
# first: on car power the panel can wake a moment after the Pi, and starting
# without it means the slow fallback below, with no map.
card=""
if [ -z "$QT_QPA_EGLFS_KMS_CONFIG" ]; then
    waited=0
    until card=$(connected_card) || [ $waited -ge 30 ]; do
        sleep 1
        waited=$((waited + 1))
    done
    if [ -n "$card" ]; then
        cfg="${XDG_RUNTIME_DIR:-/tmp}/baja-kms.json"
        printf '{ "device": "/dev/dri/%s", "hwcursor": false }\n' "$card" > "$cfg"
        export QT_QPA_EGLFS_KMS_CONFIG="$cfg"
    else
        echo "no screen connected after 30 s" >&2
    fi
fi

if [ -n "$QT_QPA_PLATFORM" ]; then
    exec python3 main.py $FULLSCREEN "$@"
fi

# Seconds since boot, which a clock step (chrony or the GPS setting the time
# right after boot) can't move; the wall clock could make a fast eglfs crash
# look slow, or negative, and skip the fallback. Falls back to the wall clock
# only where /proc/uptime can't be read.
mono_seconds() {
    local up
    if read -r up _ < /proc/uptime 2>/dev/null && [ -n "$up" ]; then
        echo "${up%%.*}"
    else
        date +%s
    fi
}

started=$(mono_seconds)
QT_QPA_PLATFORM=eglfs python3 main.py $FULLSCREEN "$@"
status=$?
# Only a startup failure should fall back: Qt aborts (exit 134) when eglfs
# can't initialise. A crash later also aborts with 134 (PyQt turns an
# unhandled Python exception into an abort), so fall back only if it died
# within the first 10 s; otherwise exit and let systemd restart us.
# Ctrl-C/kill on eglfs exits 1 via Qt's console handler.
if [ $status -ne 134 ] || [ $(( $(mono_seconds) - started )) -gt 10 ]; then
    exit $status
fi
echo "eglfs failed (exit $status); falling back to linuxfb" >&2
if connected_card >/dev/null; then
    QT_QPA_PLATFORM=linuxfb exec python3 main.py $FULLSCREEN "$@"
fi
# No screen is connected: run the fallback, and once a screen is plugged
# in, quit so systemd restarts the dashboard on the GPU.
QT_QPA_PLATFORM=linuxfb python3 main.py $FULLSCREEN "$@" &
app=$!
while kill -0 $app 2>/dev/null; do
    if connected_card >/dev/null; then
        echo "a screen was connected; restarting on the GPU" >&2
        kill $app
        wait $app
        exit 1
    fi
    sleep 3
done
wait $app
