#!/usr/bin/env python3
"""Baja carputer dashboard: entry point.

Runs the QML interface with mock vehicle and media data so the UI can be
built and tested before real OBD-II, CarPlay and audio hardware is wired in.

    python3 main.py               # 1280x800 window (Mac / desktop)
    python3 main.py --fullscreen  # full screen (the Pi in the car)
    python3 main.py --music-dir ~/Music  # play real files (default ~/Music)
"""

import argparse
import os
import signal
import sys
from pathlib import Path

# Qt's FFmpeg backend dumps every file's full tag block to the console. Must be
# set before Qt loads, so it lives above the PyQt imports.
os.environ.setdefault("QT_LOGGING_RULES", "qt.multimedia.ffmpeg*=false")

from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtQml import QQmlApplicationEngine

from backend.display import Display
from backend.media import MediaPlayer
from backend.vehicle import VehicleData

ROOT = Path(__file__).resolve().parent


def parse_args():
    parser = argparse.ArgumentParser(description="Baja carputer dashboard")
    parser.add_argument("--fullscreen", action="store_true",
                        help="fill the whole screen (use this on the Pi)")
    parser.add_argument("--music-dir", default="~/Music",
                        help="folder of audio files to play (demo playlist if empty)")
    return parser.parse_known_args()[0]


def make_media_player(music_dir):
    """Real player over music_dir if it has audio files, else the demo one."""
    try:
        from backend.library import LibraryPlayer, scan
    except ImportError as e:  # QtMultimedia or mutagen not installed
        print(f"Music: real playback unavailable ({e}); using demo playlist")
        return MediaPlayer()
    tracks = scan(music_dir)
    if not tracks:
        print(f"Music: no audio files in {music_dir}; using demo playlist")
        return MediaPlayer()
    print(f"Music: {len(tracks)} track(s) from {music_dir}")
    return LibraryPlayer(tracks)


def main():
    args = parse_args()
    # Qt's event loop never hands control back to Python's Ctrl-C handler, so
    # let SIGINT kill the process directly (matters when started over SSH).
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    app = QGuiApplication(sys.argv)
    app.setApplicationName("Baja Carputer")

    # Backends live in Python; QML only displays them. Swap the mock classes
    # for real ones (OBD-II reader, audio player) without touching the UI.
    vehicle = VehicleData()
    media = make_media_player(args.music_dir)
    display = Display()

    engine = QQmlApplicationEngine()
    ctx = engine.rootContext()
    ctx.setContextProperty("vehicle", vehicle)
    ctx.setContextProperty("media", media)
    ctx.setContextProperty("display", display)
    ctx.setContextProperty("demoMode", True)

    engine.load(QUrl.fromLocalFile(str(ROOT / "qml" / "Main.qml")))
    if not engine.rootObjects():
        print("Failed to load the QML interface; see errors above.", file=sys.stderr)
        return 1

    window = engine.rootObjects()[0]
    if args.fullscreen:
        window.showFullScreen()

    vehicle.start()
    media.start()
    code = app.exec()
    # Tear down the QML before the backends so bindings don't read null on exit.
    del engine
    return code


if __name__ == "__main__":
    sys.exit(main())
