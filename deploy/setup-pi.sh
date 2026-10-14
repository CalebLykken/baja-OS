#!/bin/sh
# One-time Pi setup for Baja OS. Safe to re-run.
#
#   - Installs the packages Baja OS needs (Qt, audio, boot screen)
#   - Wi-Fi keeps retrying at boot instead of giving up, with power saving off
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
    pipewire pipewire-pulse wireplumber plymouth
# The user's PipeWire session (audio) runs at boot without anyone logging in.
loginctl enable-linger "$USER_NAME"

echo "== Wi-Fi"
# NetworkManager gives up after 4 failed tries by default; a brownout while
# the USB adapter starts can burn through those. 0 = retry forever.
nmcli -t -f NAME,TYPE con show | grep ':802-11-wireless$' | cut -d: -f1 |
while read -r con; do
    nmcli con modify "$con" connection.autoconnect-retries 0 802-11-wireless.powersave 2
    echo "   $con: retry forever, power saving off"
done

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
