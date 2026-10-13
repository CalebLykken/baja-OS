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

- `qml/Main.qml` + `qml/pages/` (Home, Music, Maps, Gauges, Settings), shared `NowPlaying` component
- `run.sh` (eglfs, falls back to linuxfb), `README.md`, `requirements.txt`, `.gitignore`
- Offscreen screenshots of every page in `docs/`; fixed Gauge painting at zero size and a teardown-order warning on exit
- Repo: https://github.com/CalebLykken/baja-OS (private)

## Still to do
1. Run `./run.sh` on the Pi 2 and fix anything that differs from the Mac (fonts/glyphs, eglfs)
