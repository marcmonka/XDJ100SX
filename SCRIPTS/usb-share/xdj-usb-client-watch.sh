#!/bin/bash
# Runs as a systemd service. Watches for XDJ-USB NFS shares announced via avahi
# and mounts them at /media/usb1 so Mixxx sees the Rekordbox library automatically.
#
# usb0 = local physical USB
# usb1 = network USB from the other Pi (this script)

MOUNT="/media/usb1"
mkdir -p "$MOUNT"

log() { logger -t xdj-usb-client "$1"; echo "[$(date '+%H:%M:%S')] $1"; }

do_mount() {
    local address="$1" path="$2"
    if mountpoint -q "$MOUNT"; then
        log "Already mounted at $MOUNT, skipping"
        return 0
    fi
    log "Mounting NFS $address:$path → $MOUNT"
    mount -t nfs "$address:$path" "$MOUNT" \
          -o ro,soft,timeo=100,retrans=2,vers=3,nolock 2>/dev/null \
        || mount -t nfs "$address:$path" "$MOUNT" \
                 -o ro,soft,timeo=100,retrans=2
    log "Mounted OK — Mixxx will see Rekordbox library at $MOUNT"
}

do_unmount() {
    mountpoint -q "$MOUNT" || return 0
    log "Unmounting $MOUNT"
    umount -l "$MOUNT"
}

MY_IP=$(hostname -I | awk '{print $1}')
log "Client watcher started (my IP: $MY_IP)"

avahi-browse -r -p _xdj-usb._tcp 2>/dev/null | \
while IFS=';' read -r action iface proto name type domain hostname address port txt; do
    case "$action" in
        '=')
            [ "$address" = "$MY_IP" ] && continue
            nfs_path=$(echo "$txt" | tr -d '"' | tr ';' '\n' \
                       | grep '^path=' | cut -d= -f2 | head -1)
            [ -z "$nfs_path" ] && nfs_path="/media/usb0"
            do_mount "$address" "$nfs_path"
            ;;
        '-')
            do_unmount
            ;;
    esac
done
