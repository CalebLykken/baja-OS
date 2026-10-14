#!/usr/bin/env python3
"""Baja carputer dashboard: entry point.

Runs the QML interface with mock vehicle and media data so the UI can be
built and tested before real OBD-II and audio hardware is wired in.

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

from backend.bluetooth import BluetoothAudio
from backend.display import Display
from backend.eq import Equalizer
from backend.hub import MediaHub
from backend.maps import DEFAULT_DATA_DIR, MapService
from backend.media import MediaPlayer
from backend.network import Network
from backend.settings import Settings
from backend.spotify import SpotifyPlayer
from backend.system import SystemInfo
from backend.systemd import Watchdog
from backend.vehicle import VehicleData
from backend.wifi import Wifi

ROOT = Path(__file__).resolve().parent


def parse_args():
    parser = argparse.ArgumentParser(description="Baja carputer dashboard")
    parser.add_argument("--fullscreen", action="store_true",
                        help="fill the whole screen (use this on the Pi)")
    parser.add_argument("--style", default=None,
                        choices=["amber", "cluster", "trail", "rally"],
                        help="UI style for this run (default: the one last picked in Settings)")
    parser.add_argument("--no-splash", action="store_true",
                        help="skip the startup animation")
    parser.add_argument("--music-dir", default="~/Music",
                        help="folder of audio files to play (demo playlist if empty)")
    parser.add_argument("--maps-dir", default=str(DEFAULT_DATA_DIR),
                        help="offline map data from deploy/maps/install-map.sh")
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


def init_web_engine():
    """Qt WebEngine (for the map) must be set up before the app object
    exists. Returns False if it isn't installed; the Maps page says so."""
    try:
        from PyQt6.QtWebEngineQuick import QtWebEngineQuick
    except ImportError as e:
        print(f"Maps: Qt WebEngine unavailable ({e})")
        return False
    QtWebEngineQuick.initialize()
    return True


def main():
    args = parse_args()
    # Qt's event loop never hands control back to Python's Ctrl-C handler, so
    # let SIGINT kill the process directly (matters when started over SSH).
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    web_engine = init_web_engine()
    app = QGuiApplication(sys.argv)
    app.setApplicationName("Baja Carputer")

    # Backends live in Python; QML only displays them. Swap the mock classes
    # for real ones (OBD-II reader, audio player) without touching the UI.
    vehicle = VehicleData()
    settings = Settings()
    # Local music, the phone (Bluetooth) and Spotify behind one `media` object.
    bluetooth = BluetoothAudio()
    spotify = SpotifyPlayer()
    local = make_media_player(args.music_dir)
    media = MediaHub(local, bluetooth, spotify,
                     volume=settings.get_int("volume", 40),
                     max_volume=settings.get_int("maxVolume", 100))
    media.volumeChanged.connect(lambda: settings.set("volume", media.local_volume))
    media.maxVolumeChanged.connect(lambda: settings.set("maxVolume", media.maxVolume))
    display = Display()
    network = Network()
    maps = MapService(args.maps_dir, web_engine)
    eq = Equalizer(settings)
    wifi = Wifi(settings)
    system = SystemInfo()

    engine = QQmlApplicationEngine()
    ctx = engine.rootContext()
    ctx.setContextProperty("vehicle", vehicle)
    ctx.setContextProperty("media", media)
    ctx.setContextProperty("bluetooth", bluetooth)
    ctx.setContextProperty("spotify", spotify)
    ctx.setContextProperty("display", display)
    ctx.setContextProperty("network", network)
    ctx.setContextProperty("maps", maps)
    ctx.setContextProperty("eq", eq)
    ctx.setContextProperty("wifi", wifi)
    ctx.setContextProperty("system", system)
    ctx.setContextProperty("demoMode", True)
    ctx.setContextProperty("settings", settings)
    ctx.setContextProperty("startStyle", args.style or "")
    ctx.setContextProperty("showSplash", not args.no_splash
                           and str(settings.get("splash", "true")) == "true")

    engine.load(QUrl.fromLocalFile(str(ROOT / "qml" / "Main.qml")))
    if not engine.rootObjects():
        print("Failed to load the QML interface; see errors above.", file=sys.stderr)
        return 1

    window = engine.rootObjects()[0]
    if args.fullscreen:
        window.showFullScreen()

    vehicle.start()
    media.start()
    maps.start()
    eq.start()
    wifi.start()
    system.start()
    network.start()
    # Tell systemd we're up, then keep its watchdog fed from the UI thread.
    watchdog = Watchdog()
    watchdog.start()
    code = app.exec()
    # Background threads (Spotify, Bluetooth, art) can still signal while
    # Python tears objects down; a signal into a deleted object would abort.
    for obj in (vehicle, local, bluetooth, spotify, media, display, network, maps, eq, wifi, system):
        obj.blockSignals(True)
    # Tear down the QML before the backends so bindings don't read null on exit.
    del engine
    return code


if __name__ == "__main__":
    sys.exit(main())
