#!/bin/sh
# Undo the boot changes from deploy/setup-pi.sh: original boot files,
# Plymouth theme and quit behaviour, and console login. The Baja OS service
# stays installed; `sudo systemctl disable baja-os` stops it starting at boot.
set -e
[ "$(id -u)" = 0 ] || exec sudo "$0" "$@"
FW=/boot/firmware
for f in cmdline.txt config.txt; do
    [ -f "$FW/$f.baja-backup" ] && mv "$FW/$f.baja-backup" "$FW/$f"
done
theme=$(cat /etc/baja-plymouth-theme.backup 2>/dev/null || echo pix)
plymouth-set-default-theme -R "$theme"
rm -f /etc/baja-plymouth-theme.backup /etc/systemd/system/plymouth-quit.service.d/baja-retain-splash.conf
systemctl unmask plymouth-quit.service plymouth-quit-wait.service
systemctl enable getty@tty1.service
systemctl daemon-reload
echo "Original boot restored. Reboot to see it."
