# Baja OS

Touchscreen dashboard for a Raspberry Pi carputer in a 2005 Subaru Baja Turbo.
Python + PyQt6 backend, QML front end. Music comes from Spotify (the official
Soloist player), a phone over Bluetooth, or files on the Pi; the map is
OpenStreetMap stored on the Pi, so it works with no signal. Vehicle data is
simulated for now (the **DEMO DATA** badge in the status bar) until the OBD-II
adapter is wired in. The plan is in [docs/ROADMAP.md](docs/ROADMAP.md) and the
look in [docs/DESIGN.md](docs/DESIGN.md).

![Home](docs/home.png)

| Music | Gauges |
|---|---|
| ![Music](docs/music.png) | ![Gauges](docs/gauges.png) |

## Hardware

- Waveshare 8" HDMI capacitive touch, 1280x800, landscape
- Raspberry Pi 5, 8 GB (Raspberry Pi OS Lite 13 "trixie", 64-bit, console only)

## Layout

```
main.py              entry point; hands the backends to QML
run.sh               Pi launcher (EGLFS, falls back to linuxfb)
backend/vehicle.py   simulated drive: rpm, speed, boost, coolant, intake, volts, gear
backend/hub.py       one `media` object over local files, the phone and Spotify
backend/library.py   plays real files from --music-dir (default ~/Music)
backend/bluetooth.py phone audio over Bluetooth (BlueZ, AVRCP)
backend/spotify.py   Spotify Connect through Soloist's local API
backend/maps.py      local web server for the offline map
backend/eq.py        the 5-band equalizer (a PipeWire filter, set live)
backend/wifi.py      Wi-Fi networks and Bluetooth tethering (NetworkManager)
backend/system.py    temperature, fan, power warnings, restart and power
backend/display.py   screen brightness over DDC/CI (software dim fallback)
qml/Main.qml         window: nav rail + status bar + pages
qml/pages/           Home, Music, Maps, Gauges, Truck, Settings
qml/components/      Theme, Card, Gauge, NowPlaying, Readout, ...
web/map/             the map page: MapLibre GL JS + PMTiles (vendored)
deploy/              Pi setup, service, Spotify and map installers
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
sudo apt install python3-pyqt6.qtmultimedia python3-mutagen python3-pyqt6 python3-pyqt6.qtqml python3-pyqt6.qtquick qml6-module-qtquick qml6-module-qtquick-layouts qml6-module-qtquick-window qml6-module-qtqml-workerscript
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

## Music

Put audio files (mp3, m4a, flac, ogg, wav) in `~/Music` on the Pi, or pass
`--music-dir`. Title, artist and embedded cover art come from the file tags.
With no files there, the Music page plays the demo playlist. Audio goes to the
default PipeWire output (the Pi's 3.5 mm jack).

## Equalizer

Five bands (bass, low mid, mid, presence, treble) with presets, on the Music
page (the equalizer key) and in Settings > Sound. PipeWire does the filtering
in front of the speakers, so it applies to Spotify, the phone and local files
alike. `setup-pi.sh` installs it; on its own:

```bash
./deploy/audio/install-eq.sh            # no sudo; --remove takes it out again
```

## Wi-Fi and the phone's hotspot

Settings > Wi-Fi lists nearby networks; tap one and type its password on the
on-screen keyboard. For an iPhone hotspot, turn on Personal Hotspot and keep
that screen open while you join. Networks joined this way retry forever, so
the Pi picks the hotspot up by itself whenever the phone is in the truck. If
there's no Wi-Fi for a minute, it uses the paired phone over Bluetooth instead
(Settings > Wi-Fi > Phone as backup). Joining networks, rebooting and shutting
down from the dashboard need the polkit rule that `setup-pi.sh` installs.

## Offline map

```bash
./deploy/maps/install-map.sh   # Seattle area, about 130 MB; safe to re-run to update
```

This cuts the Seattle area (Tacoma to Everett, Bremerton to North Bend) out of
Protomaps' daily OpenStreetMap build, with the label fonts and icons, into
`~/.local/share/baja-os/maps`. After that the map needs no internet. Set
`REGION` and `BBOX` for a different area (the script shows how). The map is
MapLibre GL JS in Qt WebEngine, coloured from the current style, and starts the
first time the Maps page opens.

To work on the map in a desktop browser:

```bash
python3 -m backend.maps --port 8765    # then open http://127.0.0.1:8765/
```

## Pi setup (boot, Wi-Fi, service)

```bash
./deploy/setup-pi.sh          # asks for sudo once; safe to re-run; reboot afterwards
./deploy/quiet-boot-undo.sh   # puts the original boot screen and console back
```

`setup-pi.sh` makes Wi-Fi keep retrying at boot (power saving off), hides the
rainbow screen, kernel text, logos and console login, installs the Baja OS
boot screen, and installs `baja-os.service`, which takes the display straight
from the boot screen so the truck stays up until the dashboard appears. It
also lets your user restart that one service without a password:

```bash
sudo systemctl restart baja-os
journalctl -u baja-os -f
```

Ctrl+Alt+F2 still gives you a text login on the Pi itself.

Style, volume and units are saved to `~/.config/baja-os/baja-os.conf` and
restored on the next start. `--style` overrides the saved style for one run.

## Deploying updates

From the Mac:

```bash
./deploy/push.sh        # copies to baja.local, stamps the version, restarts
```

Or on the Pi: `git pull && sudo systemctl restart baja-os`.

## Next steps

See [docs/ROADMAP.md](docs/ROADMAP.md).
