#!/bin/sh
# Make the Pi boot straight into Baja OS: no rainbow screen, no kernel text
# or logos, no console login. The Baja OS Plymouth theme shows the truck
# until the app's splash takes over. Backs up the boot files first;
# deploy/quiet-boot-undo.sh puts everything back. Reboot to see it.
set -e
[ "$(id -u)" = 0 ] || exec sudo "$0" "$@"
HERE=$(cd "$(dirname "$0")" && pwd)
FW=/boot/firmware

for f in cmdline.txt config.txt; do
    [ -f "$FW/$f.baja-backup" ] || cp "$FW/$f" "$FW/$f.baja-backup"
done
[ -f /etc/baja-plymouth-theme.backup ] || plymouth-set-default-theme > /etc/baja-plymouth-theme.backup

# Kernel messages go to hidden tty3; no logo, no blinking cursor. cmdline.txt
# must stay a single line.
CMD=$(sed 's/console=tty1/console=tty3/' "$FW/cmdline.txt" | tr -d '\n')
for opt in quiet splash loglevel=3 logo.nologo vt.global_cursor_default=0; do
    case " $CMD " in *" $opt "*) ;; *) CMD="$CMD $opt" ;; esac
done
printf '%s\n' "$CMD" > "$FW/cmdline.txt"

# No rainbow test screen from the firmware.
grep -q '^disable_splash=1' "$FW/config.txt" || printf '\n[all]\ndisable_splash=1\n' >> "$FW/config.txt"

# Baja OS boot screen (rebuilding the initramfs takes a few minutes on a Pi 2).
mkdir -p /usr/share/plymouth/themes/baja
cp "$HERE"/plymouth/* /usr/share/plymouth/themes/baja/
plymouth-set-default-theme -R baja

# Keep the boot screen's last frame up until the app draws, instead of
# flashing to the console in between.
mkdir -p /etc/systemd/system/plymouth-quit.service.d
cat > /etc/systemd/system/plymouth-quit.service.d/baja-retain-splash.conf <<CONF
[Service]
ExecStart=
ExecStart=-/usr/bin/plymouth quit --retain-splash
CONF

# No login prompt on the screen. Ctrl+Alt+F2 still gives you one.
systemctl disable getty@tty1.service
systemctl daemon-reload
echo "Quiet boot installed. Reboot to see it."
