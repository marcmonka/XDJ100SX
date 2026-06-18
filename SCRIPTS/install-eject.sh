#!/bin/bash
# XDJ100SX — Script 2: USB Safe Eject
# Listens for the BACK button held 3 seconds on the controller
# to safely unmount and eject the USB drive.
#
# Usage: sudo bash install-eject.sh

set -e

RED='\033[0;31m'; GREEN='\033[0;32m'; NC='\033[0m'
info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

[ "$EUID" -ne 0 ] && error "Run as root: sudo bash install-eject.sh"

VENV="/home/xdj100sx/venv-xdj"

# ── 1. Dependencies ───────────────────────────────────────────────────────────
info "Installing dependencies..."
apt-get update -qq
apt-get install -y python3-pip python3-venv

# ── 2. Python virtualenv + packages ──────────────────────────────────────────
info "Creating Python virtualenv..."
sudo -u xdj100sx python3 -m venv "$VENV"
sudo -u xdj100sx "$VENV/bin/pip" install --quiet mido python-rtmidi

# ── 3. Eject script ───────────────────────────────────────────────────────────
info "Creating eject script..."
cat > /usr/local/bin/xdj-eject.py << 'PYEOF'
#!/usr/bin/env python3
"""
XDJ-100SX USB Safe Eject Service
Listens for BACK held 3 seconds on the controller to safely eject the USB drive.
Run as a systemd service alongside Mixxx.
"""

import mido
import subprocess
import time
import threading
import sys

# USB block device to eject — run `lsblk` to find the correct one
USB_DEVICE = "/dev/sda1"

# USB mount point set by automount
MOUNT_POINT = "/media/usb0"

# MIDI note matching the XML mapping
NOTE_BACK = 0x3F  # BACK button (note_on 0x90, midino 0x3F)

# Seconds BACK must be held before ejecting
HOLD_SECONDS = 3.0

eject_timer = None


def do_eject():
    print("[eject] Syncing...", flush=True)
    subprocess.run(["sync"])

    print("[eject] Unmounting USB...", flush=True)
    r1 = subprocess.run(
        ["sudo", "umount", "-l", MOUNT_POINT],
        capture_output=True, text=True
    )
    # Ignore "not mounted" — automount may have already unmounted it
    if r1.returncode != 0 and "not mounted" not in r1.stderr:
        print("[eject] Unmount error:", r1.stderr.strip(), flush=True)
        return

    print("[eject] Waiting for device to release...", flush=True)
    time.sleep(2)

    print("[eject] Powering off...", flush=True)
    r2 = subprocess.run(
        ["sudo", "udisksctl", "power-off", "-b", "/dev/sda"],
        capture_output=True, text=True
    )
    if r2.returncode == 0:
        print("[eject] Done - safe to unplug.", flush=True)
    else:
        print("[eject] Error:", r2.stderr.strip(), flush=True)


def on_message(msg):
    global eject_timer

    if msg.type not in ("note_on", "note_off"):
        return

    velocity = getattr(msg, "velocity", 0)
    pressed  = (msg.type == "note_on" and velocity == 127)

    # BACK held -> start countdown
    if msg.note == NOTE_BACK and pressed:
        print(f"[eject] BACK held - hold {HOLD_SECONDS}s to eject...", flush=True)
        eject_timer = threading.Timer(HOLD_SECONDS, do_eject)
        eject_timer.start()

    # BACK released before countdown ends -> cancel
    elif msg.note == NOTE_BACK and not pressed:
        if eject_timer is not None:
            eject_timer.cancel()
            eject_timer = None
            print("[eject] Cancelled.", flush=True)


def find_port(keyword="XDJ"):
    """Return the first input port whose name contains keyword."""
    names = mido.get_input_names()
    for name in names:
        if keyword.upper() in name.upper():
            return name
    return None


def main():
    port_name = find_port("XDJ")

    if port_name is None:
        # List available ports to help with debugging
        print("[eject] XDJ port not found. Available ports:", flush=True)
        for p in mido.get_input_names():
            print("  -", p, flush=True)
        sys.exit(1)

    print(f"[eject] Listening on: {port_name}", flush=True)
    print(f"[eject] Hold BACK for {HOLD_SECONDS}s to eject {USB_DEVICE}", flush=True)

    with mido.open_input(port_name) as port:
        for msg in port:
            on_message(msg)


if __name__ == "__main__":
    main()
PYEOF

chmod 755 /usr/local/bin/xdj-eject.py

# ── 4. sudoers — allow passwordless umount + udisksctl ───────────────────────
info "Configuring sudoers..."
cat > /etc/sudoers.d/xdj-eject << 'SUDOEOF'
xdj100sx ALL=(ALL) NOPASSWD: /bin/umount -l /media/usb0, /usr/bin/udisksctl power-off -b /dev/sda
SUDOEOF
chmod 440 /etc/sudoers.d/xdj-eject

# ── 5. systemd service ────────────────────────────────────────────────────────
info "Creating systemd service..."
cat > /etc/systemd/system/xdj-eject.service << 'SVCEOF'
[Unit]
Description=XDJ USB Eject Service
After=sound.target

[Service]
ExecStart=/home/xdj100sx/venv-xdj/bin/python3 /usr/local/bin/xdj-eject.py
Restart=always
User=xdj100sx

[Install]
WantedBy=multi-user.target
SVCEOF

# ── 6. Enable and start ───────────────────────────────────────────────────────
info "Enabling service..."
systemctl daemon-reload
systemctl enable xdj-eject.service
systemctl restart xdj-eject.service

echo ""
info "Done! xdj-eject.service is running."
info "Hold the BACK button on the controller for 3 seconds to eject the USB."
info ""
info "Logs: journalctl -u xdj-eject -f"
