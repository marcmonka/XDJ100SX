#!/bin/bash
# XDJ100SX — USB sharing over network
# Run on EACH Pi: sudo bash install.sh
#
# Prerequisites (done once when setting up the OS):
#   sudo apt install usbmount
#
# What this does:
#   - Server side: when USB is plugged, usbmount hook exports it via NFS
#                  and announces it via avahi/mDNS automatically
#   - Client side: systemd service watches for the announcement and
#                  mounts the NFS share at /media/usb1 so Mixxx sees it
set -e

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

[ "$EUID" -ne 0 ] && error "Run as root: sudo bash install.sh"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── 1. Packages ───────────────────────────────────────────────────────────────
info "Installing packages..."
apt-get update -qq
apt-get install -y \
    nfs-kernel-server \
    nfs-common \
    avahi-daemon \
    avahi-utils \
    exfatprogs \
    python3

# ── 2. usbmount hooks (server side) ──────────────────────────────────────────
info "Installing usbmount hooks..."
[ -d /etc/usbmount/mount.d ]  || error "usbmount not installed. Run: sudo apt install usbmount"
install -m 755 "$SCRIPT_DIR/usbmount-hook-mount"  /etc/usbmount/mount.d/00_xdj_share
install -m 755 "$SCRIPT_DIR/usbmount-hook-umount" /etc/usbmount/umount.d/00_xdj_unshare

# ── 3. Client watch script + mount point ─────────────────────────────────────
info "Installing client watch script..."
install -m 755 "$SCRIPT_DIR/xdj-usb-client-watch.sh" /usr/local/bin/
mkdir -p /media/usb1

# ── 4. systemd client service ─────────────────────────────────────────────────
info "Installing systemd service..."
install -m 644 "$SCRIPT_DIR/xdj-usb-client.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable xdj-usb-client
systemctl restart xdj-usb-client

# ── 5. NFS + avahi + rpcbind ──────────────────────────────────────────────────
info "Enabling services..."
touch /etc/exports
systemctl enable rpcbind    && systemctl start rpcbind
systemctl enable avahi-daemon && systemctl start avahi-daemon

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
info "Done on $(hostname)!"
info ""
info "Flow:"
info "  Plug USB → usbmount mounts → NFS exported + avahi announced"
info "  Other Pi → detects avahi → mounts NFS at /media/usb1"
info "  Mixxx → Ctrl+Shift+R → Rekordbox library appears"
info ""
info "Logs: journalctl -t xdj-usb-share -t xdj-usb-client -f"
