#!/usr/bin/env python3
"""Baja carputer dashboard: entry point.

Runs the QML interface with mock vehicle and media data so the UI can be
built and tested before real OBD-II and audio hardware is wired in.

    python3 main.py               # 1280x800 window (Mac / desktop)
    python3 main.py --fullscreen  # full screen (the Pi in the car)
    python3 main.py --music-dir ~/Music  # play real files (default ~/Music)
"""

import argparse
import json
import os
import signal
import sys
import threading
import traceback
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
from backend.gps import Gps
from backend.ignition import KeyOff
from backend.roadinfo import RoadInfo
from backend.routing import Router
from backend.voice import Voice
from backend.hub import MediaHub
from backend.maps import DEFAULT_DATA_DIR, MapService
from backend.knob import Knob
from backend.obd import ObdReader
from backend.media import MediaPlayer
from backend.network import Network
from backend.phone import PhoneSend
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
    demo = parser.add_mutually_exclusive_group()
    demo.add_argument("--demo", dest="demo", action="store_true", default=None,
                      help="always fill in made-up data where real data is missing")
    demo.add_argument("--no-demo", dest="demo", action="store_false",
                      help="never show made-up data (the truck)")
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


_errors = 0


def log_exception(exc_type, exc, tb):
    """Log an uncaught error and carry on. Without its own sys.excepthook,
    PyQt aborts the whole dashboard (exit 134) when an exception escapes a
    slot, a timer or a property QML reads."""
    global _errors
    _errors += 1
    print(f"Uncaught error #{_errors}:", file=sys.stderr)
    traceback.print_exception(exc_type, exc, tb)
    sys.stderr.flush()


def log_thread_exception(args):
    """Log a worker thread that died, with its name."""
    if args.exc_type is SystemExit:
        return
    name = args.thread.name if args.thread else "?"
    print(f"Thread {name} stopped on an error:", file=sys.stderr)
    traceback.print_exception(args.exc_type, args.exc_value, args.exc_traceback)
    sys.stderr.flush()


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
    sys.excepthook = log_exception
    threading.excepthook = log_thread_exception
    # Qt's event loop never hands control back to Python's Ctrl-C handler, so
    # let SIGINT kill the process directly (matters when started over SSH).
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    web_engine = init_web_engine()
    app = QGuiApplication(sys.argv)
    app.setApplicationName("Baja Carputer")

    # Backends live in Python; QML only displays them. Swap the mock classes
    # for real ones (OBD-II reader, audio player) without touching the UI.
    settings = Settings()
    vehicle = VehicleData(settings, demo=args.demo)
    # Real engine data from the OBD-II adapter whenever the car answers.
    obd = ObdReader()
    obd.reading.connect(vehicle.apply_obd)
    obd.lost.connect(vehicle.lost_obd)
    obd.voltage.connect(vehicle.apply_voltage)
    # Local music, the phone (Bluetooth) and Spotify behind one `media` object.
    bluetooth = BluetoothAudio()
    spotify = SpotifyPlayer()
    # Spotify albums and playlists played here, kept between runs.
    try:
        spotify.load_recents(json.loads(str(settings.get("spotifyRecents", "[]"))))
    except ValueError:
        pass
    spotify.recentsChanged.connect(lambda: settings.set("spotifyRecents", json.dumps(spotify.recents)))
    local = make_media_player(args.music_dir)
    # It picks up where music was before a restart, and saves that as it goes.
    media = MediaHub(local, bluetooth, spotify,
                     volume=settings.get_int("volume", 40),
                     max_volume=settings.get_int("maxVolume", 100), settings=settings)
    media.volumeChanged.connect(lambda: settings.set("volume", media.local_volume))
    media.maxVolumeChanged.connect(lambda: settings.set("maxVolume", media.maxVolume))
    # The dash knob: turn for volume, press to play or pause.
    knob = Knob()
    knob.turned.connect(lambda step: media.volumeUp() if step > 0 else media.volumeDown())
    knob.pressed.connect(media.togglePlay)
    # Day/night brightness follows the sun where the truck is (Seattle
    # until the GPS has a position).
    display = Display(settings, location=lambda: (gps.lat, gps.lon) if gps.hasFix else (47.6062, -122.3321))
    network = Network()
    maps = MapService(args.maps_dir, web_engine)
    eq = Equalizer(settings)
    phone = PhoneSend(args.maps_dir)
    wifi = Wifi(settings)
    system = SystemInfo()
    # A simulated drive around Seattle while there's no GPS receiver and no
    # engine data (a Mac, or a Pi on the bench).
    gps = Gps(vehicle, demo=True)
    routing = Router(gps, settings)
    road = RoadInfo(gps)
    voice = Voice(settings)
    routing.speak.connect(voice.say)
    # Shut down cleanly once the truck is turned off (the car stops
    # answering the OBD adapter), inside the power relay's hold time.
    key_off = KeyOff(obd, gps, settings, power_off=system.powerOff)
    system.powerFailed.connect(key_off.power_failed)

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
    ctx.setContextProperty("keyOff", key_off)
    ctx.setContextProperty("gps", gps)
    ctx.setContextProperty("routing", routing)
    ctx.setContextProperty("road", road)
    ctx.setContextProperty("voice", voice)
    ctx.setContextProperty("phone", phone)
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
    gps.start()
    routing.start()
    road.start()
    display.start()
    phone.start()
    network.start()
    knob.start()
    obd.start()
    key_off.start()
    # Tell systemd we're up, then keep its watchdog fed from the UI thread.
    watchdog = Watchdog()
    watchdog.start()
    code = app.exec()
    # Background threads (Spotify, Bluetooth, art) can still signal while
    # Python tears objects down; a signal into a deleted object would abort.
    for obj in (vehicle, local, bluetooth, spotify, media, display, network, maps, eq, wifi, system, gps, routing, voice, phone, road, knob, obd, key_off):
        obj.blockSignals(True)
    # Tear down the QML before the backends so bindings don't read null on exit.
    del engine
    return code


if __name__ == "__main__":
    sys.exit(main())
