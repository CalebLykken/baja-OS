#!/bin/sh
# Install and start the Baja OS boot service for the current user.
set -e
cd "$(dirname "$0")/.."
loginctl enable-linger "$USER"      # run user services at boot without a login
mkdir -p ~/.config/systemd/user
cp deploy/baja-os.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now baja-os.service
systemctl --user --no-pager status baja-os.service | head -5
