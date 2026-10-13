# Baja OS

Touchscreen dashboard for a Raspberry Pi carputer in a 2005 Subaru Baja Turbo.
Python + PyQt6 backend, QML front end. Vehicle and media data are simulated for
now (the **DEMO DATA** badge in the status bar), so the UI can be built before
the OBD-II adapter, CarPlay dongle and audio are wired in.

![Home](docs/home.png)

| Music | Gauges |
|---|---|
| ![Music](docs/music.png) | ![Gauges](docs/gauges.png) |

## Hardware

- Waveshare 8" HDMI capacitive touch, 1280x800, landscape
- Raspberry Pi 2 for testing (Raspberry Pi OS 13 "trixie", 32-bit, console only); Raspberry Pi 5 in the car

## Layout

```
main.py              entry point; exposes `vehicle`, `media`, `demoMode` to QML
run.sh               Pi launcher (EGLFS, falls back to linuxfb)
backend/vehicle.py   simulated drive: rpm, speed, boost, coolant, intake, volts, gear
backend/media.py     fake playlist with transport + volume controls
backend/display.py   screen brightness over DDC/CI (software dim fallback)
qml/Main.qml         window: nav rail + status bar + pages
qml/pages/           Home, Music, Maps (CarPlay placeholder), Gauges, Settings
qml/components/      Theme, Card, Gauge, NowPlaying, Readout, ...
```

The UI uses only QtQuick and QtQuick.Layouts (no Controls or Shapes) to keep
the Pi's dependency list small.

## Run on a Mac

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python main.py
```

## Run on the Pi

PySide6 isn't packaged for the 32-bit Pi, so install PyQt6 from apt:

```bash
sudo apt install python3-pyqt6 python3-pyqt6.qtqml python3-pyqt6.qtquick qml6-module-qtquick qml6-module-qtquick-layouts qml6-module-qtquick-window qml6-module-qtqml-workerscript
```

Then from the console (not over a desktop session):

```bash
git clone https://github.com/CalebLykken/baja-OS.git
cd baja-OS
./run.sh
```

`run.sh` tries `QT_QPA_PLATFORM=eglfs` and falls back to `linuxfb`. Set
`QT_QPA_PLATFORM` yourself to force one. Over SSH the app still draws on the
HDMI panel; press Ctrl-C in the SSH session to quit. Your user needs to be in
the `video`, `render` and `input` groups for the display and touch to work.

## Deploying updates

```bash
git pull && ./run.sh
```

## Next steps

- Swap `VehicleData._tick` for real OBD-II PID reads (same property names, QML unchanged)
- Real audio backend in `MediaPlayer`; wire `volumeUp`/`volumeDown` to the dash knob
- CarPlay via the Carlinkit dongle on the Maps page
- Start on boot (systemd unit)
