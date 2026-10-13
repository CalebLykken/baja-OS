#!/usr/bin/env python3
"""Baja carputer dashboard: entry point.

Runs the QML interface with mock vehicle and media data so the UI can be
built and tested before real OBD-II, CarPlay and audio hardware is wired in.

    python3 main.py               # 1280x800 window (Mac / desktop)
    python3 main.py --fullscreen  # full screen (the Pi in the car)
"""

import argparse
import os
import sys
from pathlib import Path

from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtQml import QQmlApplicationEngine

from backend.media import MediaPlayer
from backend.vehicle import VehicleData

ROOT = Path(__file__).resolve().parent


def parse_args():
    parser = argparse.ArgumentParser(description="Baja carputer dashboard")
    parser.add_argument("--fullscreen", action="store_true",
                        help="fill the whole screen (use this on the Pi)")
    return parser.parse_known_args()[0]


def main():
    args = parse_args()

    app = QGuiApplication(sys.argv)
    app.setApplicationName("Baja Carputer")

    # Backends live in Python; QML only displays them. Swap the mock classes
    # for real ones (OBD-II reader, audio player) without touching the UI.
    vehicle = VehicleData()
    media = MediaPlayer()

    engine = QQmlApplicationEngine()
    ctx = engine.rootContext()
    ctx.setContextProperty("vehicle", vehicle)
    ctx.setContextProperty("media", media)
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
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
