#!/bin/sh
# Undo deploy/quiet-boot.sh: restore the original boot files, Plymouth theme
# and console login.
set -e
[ "$(id -u)" = 0 ] || exec sudo "$0" "$@"
FW=/boot/firmware
for f in cmdline.txt config.txt; do
    [ -f "$FW/$f.baja-backup" ] && mv "$FW/$f.baja-backup" "$FW/$f"
done
theme=$(cat /etc/baja-plymouth-theme.backup 2>/dev/null || echo pix)
plymouth-set-default-theme -R "$theme"
rm -f /etc/baja-plymouth-theme.backup /etc/systemd/system/plymouth-quit.service.d/baja-retain-splash.conf
systemctl enable getty@tty1.service
systemctl daemon-reload
echo "Original boot restored. Reboot to see it."
