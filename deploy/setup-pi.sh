#!/bin/sh
# One-time Pi setup for Baja OS. Safe to re-run.
#
#   - Installs the packages Baja OS needs (Qt, audio, 3D, Bluetooth, boot screen)
#   - Adds this user to the groups the hardware needs (screen, touch, knob,
#     OBD adapter and GPS ports, DDC/CI brightness); they apply from the next
#     login, so the reboot setup asks for covers it
#   - Bluetooth: shows up to phones as "Baja OS" (car audio), pairing only
#     while you press Pair phone in Settings, phone audio through PipeWire
#   - Wi-Fi keeps retrying at boot instead of giving up, with power saving off,
#     and the dashboard may join networks (the phone's hotspot), use the phone
#     over Bluetooth as a backup, and reboot or shut down the Pi (polkit)
#   - "Online" from NetworkManager's connectivity check: plain HTTP every 30 s
#     (a captive portal can intercept it), in baja-connectivity.conf
#   - The equalizer in front of the speakers (a user PipeWire filter)
#   - gpsd for the GPS receiver (a u-blox on USB), always reading
#   - chrony keeps the clock right: internet NTP, else the GPS time from gpsd,
#     and the Pi 5's RTC (needs a battery) or fake-hwclock for the next boot
#   - libgpiod's Python bindings, for the volume knob on the pin header
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
    gpsd gpsd-clients python3-libgpiod chrony fake-hwclock
# The user's PipeWire session (audio) runs at boot without anyone logging in,
# with the PulseAudio-compatible socket that Qt Multimedia plays through.
loginctl enable-linger "$USER_NAME"
sudo -u "$USER_NAME" XDG_RUNTIME_DIR="/run/user/$(id -u "$USER_NAME")" \
    systemctl --user enable --now pipewire-pulse.socket 2>/dev/null || true

echo "== Hardware access"
# The screen and touch (video, render, input), the OBD adapter and the GPS on
# USB serial ports (dialout), the knob through libgpiod (gpio) and DDC/CI
# brightness (i2c). The first user Raspberry Pi Imager makes is already in
# most of these; a second account isn't. usermod refuses the whole list if one
# group is missing, so only the ones this system has go in (bluetooth is
# added below).
HW_GROUPS=""
for g in video render input dialout gpio i2c; do
    if getent group "$g" >/dev/null; then
        HW_GROUPS="${HW_GROUPS:+$HW_GROUPS,}$g"
    else
        echo "   no $g group on this system, skipped"
    fi
done
if [ -n "$HW_GROUPS" ]; then
    usermod -aG "$HW_GROUPS" "$USER_NAME"
    echo "   $USER_NAME: $HW_GROUPS"
fi

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
# The dashboard is the pairing agent now; a leftover bt-agent would register too and skip its prompt.
systemctl disable --now baja-bt-agent.service 2>/dev/null || true
rm -f /etc/systemd/system/baja-bt-agent.service
systemctl daemon-reload
WP="/home/$USER_NAME/.config/wireplumber/wireplumber.conf.d"
install -d -o "$USER_NAME" -g "$USER_NAME" "/home/$USER_NAME/.config/wireplumber" "$WP"
install -o "$USER_NAME" -g "$USER_NAME" -m 644 "$HERE/bluetooth/80-baja-bluetooth.conf" "$WP/"
install -o "$USER_NAME" -g "$USER_NAME" -m 644 "$HERE/audio/81-baja-sound-board.conf" "$WP/"
sudo -u "$USER_NAME" XDG_RUNTIME_DIR="/run/user/$USER_ID" \
    systemctl --user restart wireplumber 2>/dev/null || true

echo "== Wi-Fi"
# Without a country the radio may stay off 5 GHz, where newer iPhones put
# their hotspot unless Maximize Compatibility is on. WIFI_COUNTRY to change it.
if command -v raspi-config >/dev/null; then
    raspi-config nonint do_wifi_country "${WIFI_COUNTRY:-US}" || echo "   couldn't set the Wi-Fi country"
fi
# NetworkManager gives up after 4 failed tries by default; a brownout while
# the USB adapter starts can burn through those. 0 = retry forever.
nmcli -t -f NAME,TYPE con show | grep ':802-11-wireless$' | cut -d: -f1 |
while read -r con; do
    nmcli con modify "$con" connection.autoconnect-retries 0 802-11-wireless.powersave 2
    echo "   $con: retry forever, power saving off"
done
# "Online" comes from NetworkManager's own connectivity check. Plain HTTP so a
# captive portal can intercept it; 30 s so a lost hotspot shows up quickly.
cat > /etc/NetworkManager/conf.d/baja-connectivity.conf <<CONF
[connectivity]
uri=http://nmcheck.gnome.org/check_network_status.txt
response=NetworkManager is online
interval=30
CONF
systemctl reload NetworkManager 2>/dev/null || true
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

echo "== Clock"
# chrony replaces systemd-timesyncd (apt removes or masks it; make sure it's
# off either way). chrony also clears the kernel's unsynchronized flag, so
# `timedatectl show -p NTPSynchronized` (baja-soloist.service waits on it)
# still says yes once chrony has a source, GPS included.
systemctl disable --now systemd-timesyncd >/dev/null 2>&1 || true
# Debian's chrony.conf reads /etc/chrony/conf.d; add the line if this one
# lacks it, so the GPS source below is always picked up.
install -d /etc/chrony/conf.d
if ! grep -qE '^(confdir|include) +/etc/chrony/conf\.d' /etc/chrony/chrony.conf; then
    printf '\nconfdir /etc/chrony/conf.d\n' >> /etc/chrony/chrony.conf
fi
install -m 644 "$HERE/chrony/baja-gps.conf" /etc/chrony/conf.d/baja-gps.conf
# With no RTC battery the clock at boot is the last saved time, or the image's
# build date; fake-hwclock saves the time periodically so a boot with no RTC
# battery starts close, not at the build date.
# The Pi 5 RTC battery: charging is off by default. Only for the rechargeable
# ML-2020 cell; it must stay off for a non-rechargeable one, since charging a
# CR2032 is unsafe. Hardware decision: to enable, remove the leading # and reboot.
grep -q 'rtc_bbat_vchg' "$FW/config.txt" ||
    printf '\n[all]\n# dtparam=rtc_bbat_vchg=3000000\n' >> "$FW/config.txt"
systemctl enable chrony >/dev/null 2>&1 || true
systemctl restart chrony || echo "   chrony didn't start: see journalctl -u chrony"

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
# Kernel messages go to hidden tty3; no logo, no blinking cursor, and no
# systemd "[  OK  ]" / "[FAILED]" lines or udev chatter on screen, even when a
# service fails. plymouth.ignore-serial-consoles: with the serial console on
# the cmdline (Pi OS Lite adds it) Plymouth otherwise falls back to its text
# splash. Single line.
CMD=$(sed 's/console=tty1/console=tty3/' "$FW/cmdline.txt" | tr -d '\n')
for opt in quiet splash loglevel=3 logo.nologo vt.global_cursor_default=0 \
    systemd.show_status=false rd.systemd.show_status=false \
    udev.log_level=3 rd.udev.log_level=3 plymouth.ignore-serial-consoles; do
    case " $CMD " in *" $opt "*) ;; *) CMD="$CMD $opt" ;; esac
done
printf '%s\n' "$CMD" > "$FW/cmdline.txt"
grep -q '^disable_splash=1' "$FW/config.txt" || printf '\n[all]\ndisable_splash=1\n' >> "$FW/config.txt"
systemctl disable getty@tty1.service 2>/dev/null || true
# The Pi 4/5 bootloader draws its own diagnostics screen on HDMI before Linux
# starts (the raspberry, board, serial, MAC and boot-mode lines). DISABLE_HDMI
# turns it off; the kernel and the boot screen still use HDMI as normal.
# Written to the EEPROM on the next reboot. Older Pis have no EEPROM.
if command -v rpi-eeprom-config >/dev/null 2>&1 && eeprom=$(rpi-eeprom-config 2>/dev/null); then
    if ! printf '%s\n' "$eeprom" | grep -q '^DISABLE_HDMI=1'; then
        tmp=$(mktemp)
        printf '%s\n' "$eeprom" | grep -v '^DISABLE_HDMI=' > "$tmp"
        echo DISABLE_HDMI=1 >> "$tmp"
        if rpi-eeprom-config --apply "$tmp" >/dev/null; then
            touch /etc/baja-eeprom-hdmi.added
            echo "   bootloader screen off from the next reboot"
        else
            echo "   couldn't update the bootloader config; its screen stays"
        fi
        rm -f "$tmp"
    fi
fi

echo "== Boot screen"
[ -f /etc/baja-plymouth-theme.backup ] || plymouth-set-default-theme > /etc/baja-plymouth-theme.backup
mkdir -p /usr/share/plymouth/themes/baja
# The boot image (initramfs) carries its own copy of the theme, so a changed
# truck or script only shows after a rebuild: do one whenever a file differs.
theme_changed=""
for f in "$HERE"/plymouth/*; do
    cmp -s "$f" "/usr/share/plymouth/themes/baja/$(basename "$f")" || theme_changed=1
done
cp "$HERE"/plymouth/* /usr/share/plymouth/themes/baja/
if [ "$(plymouth-set-default-theme)" != baja ] || [ -n "$theme_changed" ] || [ "$1" = --rebuild ]; then
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

# Key-off shutdown now runs in the dashboard (backend/ignition.py, through
# the OBD adapter); take out the old GPIO service if an earlier run added it.
if [ -f /etc/systemd/system/baja-ignition.service ]; then
    systemctl disable --now baja-ignition.service 2>/dev/null || true
    rm -f /etc/systemd/system/baja-ignition.service
    systemctl daemon-reload
fi

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
