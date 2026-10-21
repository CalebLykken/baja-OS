#!/bin/sh
# One-time Pi setup for Baja OS. Safe to re-run.
#
#   - Installs the packages Baja OS needs (Qt, audio, 3D, Bluetooth, boot screen)
#   - Bluetooth: shows up to phones as "Baja OS" (car audio), pairing only
#     while you press Pair phone in Settings, phone audio through PipeWire
#   - Wi-Fi keeps retrying at boot instead of giving up, with power saving off,
#     and the dashboard may join networks (the phone's hotspot), use the phone
#     over Bluetooth as a backup, and reboot or shut down the Pi (polkit)
#   - The equalizer in front of the speakers (a user PipeWire filter)
#   - gpsd for the GPS receiver (a u-blox on USB), always reading
#   - libgpiod's Python bindings, for the volume knob on the pin header
#   - Key-off shutdown: a service that powers off cleanly after key-off
#   - Quiet boot: no rainbow screen, kernel text, logos or console login
#   - Baja OS Plymouth boot screen that hands the display straight to the app
#   - Baja OS as a system service started at boot
#   - Lets this user start/stop/restart only that service without a password
#
# Undo the boot changes with deploy/quiet-boot-undo.sh. Reboot afterwards.
set -e
[ "$(id -u)" = 0 ] || exec sudo "$0" "$@"
HERE=$(cd "$(dirname "$0")" && pwd)
APP=$(dirname "$HERE")
USER_NAME=${SUDO_USER:?run this as your normal user, it will ask for sudo}
USER_ID=$(id -u "$USER_NAME")
FW=/boot/firmware

echo "== Packages"
apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
    python3-pyqt6 python3-pyqt6.qtqml python3-pyqt6.qtquick python3-pyqt6.qtmultimedia \
    python3-mutagen qml6-module-qtquick qml6-module-qtquick-layouts \
    qml6-module-qtquick-window qml6-module-qtqml-workerscript \
    pipewire pipewire-pulse wireplumber plymouth \
    fonts-urw-base35 fonts-liberation fonts-dejavu-core \
    qml6-module-qtquick3d qml6-module-qtquick3d-assetutils qt6-quick3d-assetimporters-plugin \
    bluez bluez-tools libspa-0.2-bluetooth \
    python3-pyqt6.qtwebengine qml6-module-qtwebengine python3-pyqt6.qtwebsockets \
    gpsd gpsd-clients python3-libgpiod
# The user's PipeWire session (audio) runs at boot without anyone logging in,
# with the PulseAudio-compatible socket that Qt Multimedia plays through.
loginctl enable-linger "$USER_NAME"
sudo -u "$USER_NAME" XDG_RUNTIME_DIR="/run/user/$(id -u "$USER_NAME")" \
    systemctl --user enable --now pipewire-pulse.socket 2>/dev/null || true

echo "== Bluetooth"
usermod -aG bluetooth "$USER_NAME"          # control BlueZ over D-Bus
CONF=/etc/bluetooth/main.conf
[ -f "$CONF.baja-backup" ] || cp "$CONF" "$CONF.baja-backup"
# Car audio device class; stay hidden and unpairable unless Pair phone is on.
setconf() {  # setconf KEY VALUE: set an existing or commented-out key
    if grep -qE "^#? *$1 *=" "$CONF"; then
        sed -i -E "s|^#? *$1 *=.*|$1 = $2|" "$CONF"
    else
        printf '%s = %s\n' "$1" "$2" >> "$CONF"
    fi
}
setconf Class 0x000420
setconf DiscoverableTimeout 120
setconf PairableTimeout 120
setconf AutoEnable true
systemctl restart bluetooth
bluetoothctl system-alias "Baja OS" >/dev/null 2>&1 || true
cp "$HERE/bluetooth/baja-bt-agent.service" /etc/systemd/system/
systemctl enable --now baja-bt-agent.service
WP="/home/$USER_NAME/.config/wireplumber/wireplumber.conf.d"
install -d -o "$USER_NAME" -g "$USER_NAME" "/home/$USER_NAME/.config/wireplumber" "$WP"
install -o "$USER_NAME" -g "$USER_NAME" -m 644 "$HERE/bluetooth/80-baja-bluetooth.conf" "$WP/"
install -o "$USER_NAME" -g "$USER_NAME" -m 644 "$HERE/audio/81-baja-sound-board.conf" "$WP/"
sudo -u "$USER_NAME" XDG_RUNTIME_DIR="/run/user/$USER_ID" \
    systemctl --user restart wireplumber 2>/dev/null || true

echo "== Wi-Fi"
# NetworkManager gives up after 4 failed tries by default; a brownout while
# the USB adapter starts can burn through those. 0 = retry forever.
nmcli -t -f NAME,TYPE con show | grep ':802-11-wireless$' | cut -d: -f1 |
while read -r con; do
    nmcli con modify "$con" connection.autoconnect-retries 0 802-11-wireless.powersave 2
    echo "   $con: retry forever, power saving off"
done
# The dashboard is a service, not a desktop login, so polkit needs telling
# that it may change networks (and reboot or shut down from Settings).
sed "s|@USER@|$USER_NAME|g" "$HERE/polkit/50-baja-os.rules" > /etc/polkit-1/rules.d/50-baja-os.rules
chmod 644 /etc/polkit-1/rules.d/50-baja-os.rules

echo "== GPS"
# gpsd finds the u-blox receiver by itself when it's plugged in (USBAUTO)
# and keeps reading it with no client connected (-n), so the first fix is
# ready by the time the dashboard asks.
cat > /etc/default/gpsd <<GPSD
START_DAEMON="true"
USBAUTO="true"
DEVICES=""
GPSD_OPTIONS="-n"
GPSD
systemctl enable --now gpsd.socket >/dev/null 2>&1 || true
systemctl restart gpsd >/dev/null 2>&1 || true

echo "== Sound board"
# The InnoMaker HiFi DAC HAT has no ID chip, so the Pi has to be told it's
# there (its manual's overlay; it shows up as "BossDAC"). Takes a reboot.
grep -q '^dtoverlay=allo-boss-dac-pcm512x-audio' "$FW/config.txt" ||
    printf '\n[all]\ndtoverlay=allo-boss-dac-pcm512x-audio\n' >> "$FW/config.txt"

echo "== Equalizer"
sudo -u "$USER_NAME" XDG_RUNTIME_DIR="/run/user/$USER_ID" sh "$HERE/audio/install-eq.sh"

echo "== Quiet boot"
for f in cmdline.txt config.txt; do
    [ -f "$FW/$f.baja-backup" ] || cp "$FW/$f" "$FW/$f.baja-backup"
done
# Kernel messages go to hidden tty3; no logo, no blinking cursor. Single line.
CMD=$(sed 's/console=tty1/console=tty3/' "$FW/cmdline.txt" | tr -d '\n')
for opt in quiet splash loglevel=3 logo.nologo vt.global_cursor_default=0; do
    case " $CMD " in *" $opt "*) ;; *) CMD="$CMD $opt" ;; esac
done
printf '%s\n' "$CMD" > "$FW/cmdline.txt"
grep -q '^disable_splash=1' "$FW/config.txt" || printf '\n[all]\ndisable_splash=1\n' >> "$FW/config.txt"
systemctl disable getty@tty1.service 2>/dev/null || true

echo "== Boot screen"
[ -f /etc/baja-plymouth-theme.backup ] || plymouth-set-default-theme > /etc/baja-plymouth-theme.backup
mkdir -p /usr/share/plymouth/themes/baja
cp "$HERE"/plymouth/* /usr/share/plymouth/themes/baja/
if [ "$(plymouth-set-default-theme)" != baja ] || [ "$1" = --rebuild ]; then
    echo "   rebuilding the boot image (a few minutes on a Pi 2)"
    plymouth-set-default-theme -R baja
fi
# Plymouth stays up past boot; baja-os.service takes the display from it
# (plymouth deactivate) and only then quits it, so there's no black gap.
rm -f /etc/systemd/system/plymouth-quit.service.d/baja-retain-splash.conf
systemctl mask plymouth-quit.service plymouth-quit-wait.service

echo "== Hardware watchdog"
# If the whole system hangs (not just the app), the Pi's hardware watchdog
# reboots it. systemd feeds it every few seconds.
mkdir -p /etc/systemd/system.conf.d
cat > /etc/systemd/system.conf.d/baja-watchdog.conf <<CONF
[Manager]
RuntimeWatchdogSec=15
RebootWatchdogSec=2min
CONF
systemctl daemon-reexec                    # pick up the new manager settings

echo "== Key-off shutdown"
# Watches the key on GPIO5 and powers off cleanly once it has stayed off
# (backend/ignition.py). Harmless with nothing wired: a bare pin reads as
# key on, and it never acts before it has seen the key on.
sed "s|@APP@|$APP|g" "$HERE/power/baja-ignition.service" > /etc/systemd/system/baja-ignition.service
systemctl daemon-reload
systemctl enable baja-ignition.service
systemctl restart baja-ignition.service

echo "== Baja OS service"
sed -e "s|@USER@|$USER_NAME|g" -e "s|@UID@|$USER_ID|g" -e "s|@APP@|$APP|g" \
    "$HERE/baja-os.service" > /etc/systemd/system/baja-os.service
cat > /etc/sudoers.d/baja-os <<SUDO
# Let $USER_NAME manage the Baja OS service (deploys) without a password.
$USER_NAME ALL=(root) NOPASSWD: /usr/bin/systemctl start baja-os, /usr/bin/systemctl stop baja-os, /usr/bin/systemctl restart baja-os
SUDO
chmod 440 /etc/sudoers.d/baja-os
visudo -cf /etc/sudoers.d/baja-os >/dev/null
# Retire the older per-user service so two copies never run.
sudo -u "$USER_NAME" XDG_RUNTIME_DIR="/run/user/$USER_ID" \
    systemctl --user disable --now baja-os.service 2>/dev/null || true
rm -f "/home/$USER_NAME/.config/systemd/user/baja-os.service"
systemctl daemon-reload
systemctl enable baja-os.service

echo "Done. Reboot to see the new boot (sudo reboot)."
