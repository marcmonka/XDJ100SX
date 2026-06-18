#!/bin/bash
# XDJ100SX — Script 1: Shutdown helper
# Monitors GPIO pin 3 (physical pin 5). When the pin goes LOW,
# closes Mixxx gracefully and shuts down the Pi.
#
# Usage: sudo bash install-shutdown.sh

set -e

RED='\033[0;31m'; GREEN='\033[0;32m'; NC='\033[0m'
info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

[ "$EUID" -ne 0 ] && error "Run as root: sudo bash install-shutdown.sh"

USER_HOME="/home/xdj100sx"

# ── 1. Dependencies ───────────────────────────────────────────────────────────
info "Installing dependencies..."
apt-get update -qq
apt-get install -y python3-gpiozero wmctrl

# ── 2. Shutdown script ────────────────────────────────────────────────────────
info "Creating shutdown script..."
cat > "$USER_HOME/shutdown_script.py" << 'PYEOF'
#!/usr/bin/env python3
import os
import time
from gpiozero import Button

switch = Button(3, pull_up=True)

try:
    while True:
        if not switch.is_pressed:
            # Turn screen off
            os.system("vcgencmd display_power 0")
            # Close Mixxx gracefully (works with both mixxx and mixxx-cdj)
            os.system("sudo -u xdj100sx env DISPLAY=:0 XAUTHORITY=/home/xdj100sx/.Xauthority wmctrl -c Mixxx")
            # Wait until Mixxx is closed (max 20 seconds)
            for _ in range(20):
                if os.system("pgrep -x mixxx-cdj > /dev/null 2>&1") != 0 and \
                   os.system("pgrep -x mixxx > /dev/null 2>&1") != 0:
                    break
                time.sleep(1)
            os.system("poweroff")
            break
        time.sleep(1)
except Exception as e:
    print(f"Error: {e}")
PYEOF

chown xdj100sx:xdj100sx "$USER_HOME/shutdown_script.py"
chmod 755 "$USER_HOME/shutdown_script.py"

# ── 3. systemd service ────────────────────────────────────────────────────────
info "Creating systemd service..."
cat > /etc/systemd/system/shutdown-helper.service << 'SVCEOF'
[Unit]
Description=Script close Mixxx + Shutdown
After=multi-user.target

[Service]
Type=simple
ExecStart=/usr/bin/python3 /home/xdj100sx/shutdown_script.py
Restart=always
User=root
Environment=DISPLAY=:0

[Install]
WantedBy=graphical.target
SVCEOF

# ── 4. Enable and start ───────────────────────────────────────────────────────
info "Enabling service..."
systemctl daemon-reload
systemctl enable shutdown-helper.service
systemctl start shutdown-helper.service

echo ""
info "Done! shutdown-helper.service is running."
info "Connect a button between GPIO pin 3 (physical pin 5) and GND."
info "Press it to close Mixxx and shut down the Pi."
