#!/bin/sh
# Undo the boot changes from deploy/setup-pi.sh: its quiet-boot options in
# cmdline.txt and config.txt, Plymouth theme and quit behaviour, and console
# login. Only setup's quiet-boot lines come out of the two boot files;
# everything else there stays: the sound board overlay, and any edit made
# since setup (an overlay, a dtparam, a tweak). The Baja OS
# service stays installed; `sudo systemctl disable baja-os` stops it starting
# at boot.
set -e
[ "$(id -u)" = 0 ] || exec sudo "$0" "$@"
FW=/boot/firmware
# The options setup adds to cmdline.txt (it also moves console=tty1 to tty3).
QUIET="quiet splash loglevel=3 logo.nologo vt.global_cursor_default=0"
trap 'rm -f "$FW/cmdline.txt.baja-new" "$FW/config.txt.baja-new"' EXIT

# Setup's first run kept a copy of each file (*.baja-backup). The copies only
# say what was there before setup, e.g. the `quiet splash` that desktop images
# ship, which stays. With no copy there is nothing to go by (setup never ran,
# or this already did and removed them), so that file is left alone: a second
# run must not take out options that were there all along.
if [ -f "$FW/cmdline.txt.baja-backup" ]; then
    # One line, setup's options out, console=tty3 back to tty1. Written to a
    # temp file and moved in, so a failure never leaves half a cmdline.txt.
    CMD=$(awk -v quiet="$QUIET" -v bak="$FW/cmdline.txt.baja-backup" '
        BEGIN { n = split(quiet, q, " "); for (i = 1; i <= n; i++) mine[q[i]] = 1 }
        FILENAME == bak { for (i = 1; i <= NF; i++) had[$i] = 1; next }
        {
            for (i = 1; i <= NF; i++) {
                t = $i
                if ((t in mine) && !(t in had)) continue
                if (t == "console=tty3" && !(t in had)) t = "console=tty1"
                out = (out == "" ? t : out " " t)
            }
        }
        END { print out }
    ' "$FW/cmdline.txt.baja-backup" "$FW/cmdline.txt")
    if [ -n "$CMD" ]; then
        printf '%s\n' "$CMD" > "$FW/cmdline.txt.baja-new"
        mv "$FW/cmdline.txt.baja-new" "$FW/cmdline.txt"
        echo "   cmdline.txt: setup's options out, console=tty1 back"
    else
        echo "   cmdline.txt would be empty, left alone"
    fi
else
    echo "   no cmdline.txt.baja-backup, cmdline.txt left alone"
fi

if [ -f "$FW/config.txt.baja-backup" ]; then
    # Setup appends "[all]" and disable_splash=1, unless it was there already.
    if ! grep -q '^disable_splash=1' "$FW/config.txt.baja-backup"; then
        # Only that line goes. Setup's "[all]" goes with it (and the blank
        # line setup put before it) when nothing comes after it any more; if
        # something does, those lines belong to that section and it stays.
        awk '
            function blank(s) { gsub(/[ \t\r]/, "", s); return s == "" }
            { line[NR] = $0 }
            END {
                for (i = 1; i <= NR; i++) {
                    t = line[i]
                    sub(/[ \t\r]+$/, "", t)
                    if (t == "disable_splash=1") { cut = m + 0; found = 1; continue }
                    keep[++m] = line[i]
                }
                if (found && cut >= 1) {
                    t = keep[cut]
                    sub(/[ \t\r]+$/, "", t)
                    empty = (t == "[all]")
                    for (i = cut + 1; i <= m; i++) if (!blank(keep[i])) empty = 0
                    if (empty) {
                        skip[cut] = 1
                        if (cut > 1 && blank(keep[cut - 1])) skip[cut - 1] = 1
                    }
                }
                for (i = 1; i <= m; i++) if (!(i in skip)) print keep[i]
            }
        ' "$FW/config.txt" > "$FW/config.txt.baja-new"
        mv "$FW/config.txt.baja-new" "$FW/config.txt"
        echo "   config.txt: disable_splash=1 out"
    fi
else
    echo "   no config.txt.baja-backup, config.txt left alone"
fi
rm -f "$FW/cmdline.txt.baja-backup" "$FW/config.txt.baja-backup"

theme=$(cat /etc/baja-plymouth-theme.backup 2>/dev/null || echo pix)
plymouth-set-default-theme -R "$theme"
rm -f /etc/baja-plymouth-theme.backup /etc/systemd/system/plymouth-quit.service.d/baja-retain-splash.conf
systemctl unmask plymouth-quit.service plymouth-quit-wait.service
systemctl enable getty@tty1.service
systemctl daemon-reload
echo "Boot changes undone. Reboot to see the original boot."
