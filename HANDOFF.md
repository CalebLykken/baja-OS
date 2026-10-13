# Handoff: Baja carputer dashboard (work in progress)

Starter touchscreen dashboard for a Raspberry Pi carputer in a 2005 Subaru Baja Turbo.
Python + PyQt6 backend, QML front end, mock data for now.

## Target hardware
- Screen: Waveshare 8" HDMI capacitive touch, 1280x800, mounted **landscape**
- Test board now: Raspberry Pi 2 (Raspberry Pi OS 13 "trixie", 32-bit, console mode, no desktop)
- Final board: Raspberry Pi 5
- On the Pi 2, PySide6 is NOT packaged, so this uses **PyQt6** from apt:
  `python3-pyqt6 python3-pyqt6.qtqml python3-pyqt6.qtquick qml6-module-qtquick qml6-module-qtquick-layouts qml6-module-qtquick-window qml6-module-qtqml-workerscript`
- Avoid QtQuick.Controls and QtQuick.Shapes (keep the dependency list small); custom components only.

## Done
- `main.py`: entry point, `--fullscreen` flag, exposes `vehicle`, `media`, `demoMode` context properties
- `backend/vehicle.py`: simulated drive (rpm, speed, boost psi, coolant F, intake F, voltage, gear), 5 Hz
- `backend/media.py`: fake playlist with play/pause/next/previous/playIndex, volume + volumeUp/volumeDown (for the future dash knob)
- `qml/components/`: Theme (singleton, amber accent), Card, NavButton, IconButton, ProgressBar, Readout, Gauge (Canvas arc), StatusBar; registered in `qmldir`

## Still to do
1. `qml/Main.qml`: 1280x800 Window, `Theme.bg`; left nav rail (~112 px) of NavButtons
   (Home, Music, Maps, Gauges, Settings) + right column with StatusBar on top and a
   StackLayout of pages. Import `"components"` and `"pages"`.
2. `qml/pages/` (each page can emit `navigate(int)`):
   - HomePage: large now-playing card (art placeholder, title/artist, progress, prev/play/next),
     a Maps/CarPlay placeholder tile, and a row of Readouts (boost, coolant, volts)
   - MusicPage: now playing + tappable queue list (`media.queue`, `media.playIndex(i)`) + volume bar
   - MapsPage: placeholder where CarPlay (Carlinkit dongle) will render later
   - GaugesPage: 3x2 Gauges: RPM 0-7000 warn>6000, Speed 0-120 mph, Boost -20..20 psi warn>15,
     Coolant 100-260 F warn>230, Intake 0-200 F warn>150, Battery 10-16 V warn<12 or >15
   - SettingsPage: placeholders (brightness, units, about)
3. `run.sh` for the Pi: `QT_QPA_PLATFORM=eglfs`, `QT_QPA_EGLFS_HIDECURSOR=1`, `python3 main.py --fullscreen`
   (fallback `QT_QPA_PLATFORM=linuxfb` if eglfs fails)
4. `README.md` (Mac setup with `pip install PyQt6`, Pi setup with apt, running, deploying), `requirements.txt`, `.gitignore`
5. Test: run offscreen (`QT_QPA_PLATFORM=offscreen`), grab a screenshot of each page, fix layout issues
6. `git init`, commit, create a GitHub repo `baja-carputer` (`gh repo create baja-carputer --private --source . --push`)
7. Clone/copy onto the Pi over SSH and run `./run.sh`
