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

if [ -n "$QT_QPA_PLATFORM" ]; then
    exec python3 main.py $FULLSCREEN "$@"
fi

QT_QPA_PLATFORM=eglfs python3 main.py $FULLSCREEN "$@" && exit 0
echo "eglfs failed; falling back to linuxfb" >&2
QT_QPA_PLATFORM=linuxfb exec python3 main.py $FULLSCREEN "$@"
