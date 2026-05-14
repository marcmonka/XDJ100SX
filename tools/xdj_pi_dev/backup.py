from __future__ import annotations

"""
Pi image backup: manifest collection, archive verification, and full SD-card backup.

Extracted from xdj-pi-dev.py (lines 1289-1704).
"""

import sys
import tarfile
import tempfile
import time
from pathlib import Path

import os

from xdj_pi_dev._terminal import (
    _C, Step, section, ok, warn, fail,
)

_PI_USER = os.environ.get("XDJ_USER", "xdj100sx")
_H       = f"/home/{_PI_USER}"

# ─── Config files tracked by the manifest ────────────────────────────────────

_MANIFEST_FILES = [
    # Network
    "/etc/hostname", "/etc/hosts", "/etc/dhcpcd.conf",
    "/etc/network/interfaces", "/etc/resolv.conf",
    "/etc/dnsmasq.conf",
    # SSH
    f"/etc/ssh/sshd_config", f"{_H}/.ssh/authorized_keys",
    # Boot / kernel
    "/boot/config.txt", "/boot/cmdline.txt",
    # System services
    "/etc/rc.local",
    # USB automount (dev tool)
    "/usr/local/bin/usb-mount", "/usr/local/bin/usb-unmount",
    "/etc/udev/rules.d/99-usb-automount.rules",
    # Mixxx
    f"{_H}/.mixxx/mixxx.cfg",
    # User shell
    f"{_H}/.bashrc", f"{_H}/.profile",
]
_MANIFEST_DIRS = [
    f"{_H}/.mixxx/controllers",         # MIDI mappings
    "/etc/dnsmasq.d",                   # dnsmasq includes
    "/etc/systemd/system",              # custom services
    "/usr/local/bin",                   # custom scripts
    "/etc/udev/rules.d",                # udev rules
]


# ─── Manifest collection ──────────────────────────────────────────────────────

def _backup_manifest(pi_client) -> bytes:
    """SSH to Pi and collect sha256 checksums + directory listings of critical configs."""
    import datetime as _dt
    lines = [
        f"# XDJ Pi backup manifest — {_dt.datetime.now().isoformat(timespec='seconds')}",
        "# sha256sum of critical config files",
        "# Use --verify-backup <file.tar> to check integrity and compare against live Pi",
        "",
    ]
    # Checksum individual files
    files_arg = " ".join(f'"{f}"' for f in _MANIFEST_FILES)
    r = pi_client.exec(f"sha256sum {files_arg} 2>/dev/null || true")
    lines += r["stdout"].splitlines()

    # Checksum everything under key directories
    for d in _MANIFEST_DIRS:
        r2 = pi_client.exec(
            f'find {d} -type f 2>/dev/null | sort | xargs sha256sum 2>/dev/null || true'
        )
        if r2["stdout"].strip():
            lines += r2["stdout"].splitlines()

    # Installed package list (snapshot, not checksums)
    lines += ["", "# Installed packages (dpkg --get-selections)"]
    r3 = pi_client.exec("dpkg --get-selections 2>/dev/null | grep -v deinstall || true")
    lines += r3["stdout"].splitlines()

    return ("\n".join(lines) + "\n").encode()


# ─── Archive verification ─────────────────────────────────────────────────────

def verify_backup(pi_client, path: str) -> None:
    """Verify a backup .tar archive: test gzip integrity and display manifest."""
    import gzip as _gzip
    import io as _io

    section("Backup Verification")
    tfile = Path(path)
    if not tfile.exists():
        fail(f"File not found: {tfile}")
        return

    ok(f"Archive: {tfile}  ({tfile.stat().st_size / 1024**2:.0f} MB)")
    print()

    with Step("Opening archive"):
        try:
            tf = tarfile.open(tfile, "r")
        except Exception as e:
            raise RuntimeError(f"Cannot open tar: {e}")

    members = {m.name: m for m in tf.getmembers()}
    expected = {"mbr.bin.gz", "sfdisk.dump", "p1-boot.vfat.gz", "restore.sh"}

    ok(f"Members: {', '.join(sorted(members))}")
    missing = expected - set(members)
    if missing:
        warn(f"Unexpected missing members: {missing}")

    # Test gzip integrity of compressed parts
    gz_parts = [n for n in members if n.endswith(".gz")]
    for name in sorted(gz_parts):
        with Step(f"gzip -t  {name}"):
            data = tf.extractfile(members[name])
            if data is None:
                raise RuntimeError(f"Cannot read {name} from archive (directory entry?)")
            raw = data.read()
            try:
                with _gzip.open(_io.BytesIO(raw)) as gz:
                    gz.read()
            except OSError as _e:
                raise RuntimeError(f"Corrupt: {name}  ({_e})")
        ok(f"{name}  {len(raw) / 1024**2:.1f} MB  ✓")

    # Show sfdisk partition layout
    if "sfdisk.dump" in members:
        layout_data = tf.extractfile(members["sfdisk.dump"])
        if layout_data:
            print()
            ok("Partition layout:")
            for line in layout_data.read().decode().splitlines():
                if line.strip() and not line.startswith("#"):
                    print(f"    {line}")

    # Show manifest
    if "manifest.txt" in members:
        mdata = tf.extractfile(members["manifest.txt"])
        if mdata:
            manifest_lines = mdata.read().decode().splitlines()
            print()
            ok("Manifest (critical config checksums):")
            for line in manifest_lines:
                if line.startswith("#") or not line.strip():
                    print(f"  {_C.DIM}{line}{_C.RESET}")
                else:
                    print(f"  {line}")

            # If Pi is reachable, compare live checksums
            if pi_client._ssh:
                print()
                with Step("Comparing manifest against live Pi"):
                    live_checksums: dict[str, str] = {}
                    saved_checksums: dict[str, str] = {}
                    for line in manifest_lines:
                        if line.startswith("#") or "  " not in line:
                            continue
                        parts = line.split("  ", 1)
                        if len(parts) == 2:
                            saved_checksums[parts[1].strip()] = parts[0].strip()

                    all_files = list(saved_checksums.keys())
                    if all_files:
                        files_arg = " ".join(f'"{f}"' for f in all_files[:100])
                        r_live = pi_client.exec(f"sha256sum {files_arg} 2>/dev/null || true")
                        for line in r_live["stdout"].splitlines():
                            if "  " in line:
                                ck, fp = line.split("  ", 1)
                                live_checksums[fp.strip()] = ck.strip()

                print()
                changed, missing_live, ok_count = [], [], 0
                for fp, saved_ck in saved_checksums.items():
                    if fp not in live_checksums:
                        missing_live.append(fp)
                    elif live_checksums[fp] != saved_ck:
                        changed.append(fp)
                    else:
                        ok_count += 1

                ok(f"{ok_count} files match backup exactly")
                if changed:
                    warn(f"{len(changed)} files changed since backup:")
                    for f in changed:
                        print(f"    {_C.YELLOW}CHANGED{_C.RESET}  {f}")
                if missing_live:
                    warn(f"{len(missing_live)} files from backup not found on live Pi:")
                    for f in missing_live:
                        print(f"    {_C.RED}MISSING{_C.RESET}  {f}")
                if not changed and not missing_live:
                    ok("All config files on Pi match the backup — backup is current")
    else:
        warn("No manifest.txt in archive (backup created before verification was added)")

    tf.close()
    print()
    ok("Verification complete")


# ─── Full SD-card image backup ────────────────────────────────────────────────

def backup_pi_image(pi_client, output_path: str | None = None, log_fn=None) -> str | None:
    """Back up the Pi SD card using only used filesystem blocks.

    Creates a .tar archive containing:
      mbr.bin.gz      — first 1 MiB of disk (MBR + partition table bootstrap code)
      sfdisk.dump     — partition layout (sfdisk text format)
      p1-boot.vfat.gz — FAT32 boot partition (~256 MB, full)
      p2-root.img.gz  — root partition: e2image -r if available (reads used blocks only),
                        otherwise sequential dd (empty space compresses away with gzip)
      restore.sh      — restoration script

    Sequential block reads keep SD card at full speed (~20-40 MB/s).
    tar is NOT used — it causes random seeks which drop SD throughput to ~1-3 MB/s.

    Restore on a fresh card (Linux):
        tar xf backup.tar
        sudo bash restore.sh /dev/sdX        # or /dev/mmcblkX for a card reader
    """
    import datetime

    section("Pi Image Backup")

    # ── Detect disk ──────────────────────────────────────────────────────────
    with Step("Detecting SD card"):
        r = pi_client.exec(
            "test -b /dev/mmcblk0 && echo mmcblk0 || "
            "lsblk -ndo NAME,TYPE,TRAN 2>/dev/null | "
            "awk '$2==\"disk\" && $3!=\"usb\"{print $1}' | head -1"
        )
        disk = r["stdout"].strip()
        if not disk:
            raise RuntimeError("No suitable disk device found on Pi")
        disk_dev = f"/dev/{disk}"
        boot_dev = f"{disk_dev}p1"
        root_dev = f"{disk_dev}p2"

    ok(f"Disk: {disk_dev}   Boot: {boot_dev}   Root: {root_dev}")

    # ── Report sizes ─────────────────────────────────────────────────────────
    r_used = pi_client.exec(
        f"df -BM --output=used {root_dev} 2>/dev/null | tail -1 | tr -d ' M' || echo 0"
    )
    r_disk = pi_client.exec(f"sudo blockdev --getsize64 {disk_dev} 2>/dev/null || echo 0")
    disk_gb = int(r_disk["stdout"].strip() or 0) / 1024**3
    used_mb = int(r_used["stdout"].strip() or 0)
    if disk_gb:
        ok(f"Disk: {disk_gb:.1f} GB total,  root used: ~{used_mb} MB  (archive size ~ used data)")

    # ── Get partition table ───────────────────────────────────────────────────
    r_sfdisk = pi_client.exec(f"sudo sfdisk --dump {disk_dev} 2>/dev/null || echo ''")
    sfdisk_dump = r_sfdisk["stdout"].encode()

    # ── Output path ───────────────────────────────────────────────────────────
    if not output_path:
        ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        output_path = str(Path.cwd() / f"xdj-pi-backup-{ts}.tar")
    out = Path(output_path)
    if out.suffix != ".tar":
        out = out.with_suffix(".tar")

    warn(f"Output: {out}")
    warn("Root is archived via tar (used files only) — no extra tools needed on Pi")
    print()

    # ── Streaming helper ──────────────────────────────────────────────────────
    def _stream(label: str, cmd: str, dest: Path) -> int:
        transport = pi_client._ssh.get_transport()
        assert transport
        ch = transport.open_session()
        ch.exec_command(cmd)
        received = 0
        cancelled = False
        last_log = 0.0
        try:
            with open(dest, "wb") as fout:
                while True:
                    if ch.recv_ready():
                        chunk = ch.recv(131072)
                        if not chunk:
                            break
                        fout.write(chunk)
                        received += len(chunk)
                        if log_fn:
                            now = time.monotonic()
                            if now - last_log >= 3.0:
                                log_fn("info", f"{label}: {received / 1024**2:.0f} MB received…")
                                last_log = now
                        else:
                            sys.stdout.write(
                                f"\r  {_C.CYAN}↓{_C.RESET}  {label:<36}  {received / 1024**2:6.1f} MB"
                            )
                            sys.stdout.flush()
                    elif ch.exit_status_ready() and not ch.recv_ready():
                        break
                    else:
                        time.sleep(0.05)
        except KeyboardInterrupt:
            cancelled = True
        finally:
            ch.close()
        if cancelled:
            raise KeyboardInterrupt
        done_msg = f"{label}: done — {received / 1024**2:.0f} MB"
        if log_fn:
            log_fn("ok", done_msg)
        else:
            print(f"\r  {_C.GREEN}✓{_C.RESET}  {label:<36}  {received / 1024**2:.1f} MB")
        return received

    # ── Choose fastest available compressor ──────────────────────────────────
    # pigz = parallel gzip (uses all cores); fall back to gzip -1 (fast, single-core).
    # Both beat the default gzip -6 by 2-4x on a Pi 4.
    r_pigz = pi_client.exec("which pigz 2>/dev/null || echo ''")
    if r_pigz["stdout"].strip():
        GZIP = "pigz -1"
        ok("Compressor: pigz -1 (parallel gzip)")
    else:
        GZIP = "gzip -1"
        ok("Compressor: gzip -1 (fast mode; install pigz on Pi for extra speed)")

    # ── Stop Mixxx to free CPU during compression ─────────────────────────────
    mixxx_was_running = False
    r_mx = pi_client.exec("pgrep -x mixxx || echo ''")
    if r_mx["stdout"].strip():
        mixxx_was_running = True
        pi_client.exec("sudo pkill -x mixxx 2>/dev/null || true")
        if log_fn:
            log_fn("info", "Mixxx stopped — will restart after backup")
        else:
            warn("Mixxx stopped — will restart after backup")
        time.sleep(1)

    # ── Choose root backup strategy ───────────────────────────────────────────
    # e2image -r reads ONLY used blocks from disk (fast: ~14 GB reads instead of 59 GB).
    # It zero-fills unused blocks in the output stream; those zeros compress to nothing.
    # Fall back to sequential dd of the partition — much faster than tar (sequential
    # SD reads at 20-40 MB/s vs tar's random seeks at 1-3 MB/s).
    e2image_bin = ""
    for candidate in ("/sbin/e2image", "/usr/sbin/e2image", "/bin/e2image"):
        r_e2 = pi_client.exec(f"test -x {candidate} && echo found || echo ''")
        if "found" in r_e2["stdout"]:
            e2image_bin = candidate
            break

    if e2image_bin:
        root_cmd   = f"sudo {e2image_bin} -r {root_dev} - 2>/dev/null | {GZIP}"
        root_file  = "p2-root.img.gz"
        root_label = "Root ext4 (used blocks via e2image)"
        root_restore = 'gunzip -c p2-root.img.gz | dd of="$ROOT" bs=4M'
        ok("Root strategy: e2image -r (reads used blocks only) — fastest")
    else:
        root_cmd   = f"sudo dd if={root_dev} bs=4M 2>/dev/null | {GZIP}"
        root_file  = "p2-root.img.gz"
        root_label = "Root partition (sequential dd — zeros compress away)"
        root_restore = 'gunzip -c p2-root.img.gz | dd of="$ROOT" bs=4M'
        ok("Root strategy: sequential dd + gzip (e2image not found; zeros compress fine)")

    restore_sh = (
        "#!/bin/bash\n"
        "# XDJ Pi Image Restore\n"
        "# Usage: sudo bash restore.sh /dev/sdX\n"
        "set -e\n"
        "\n"
        'DEV="${1:?Usage: sudo bash restore.sh /dev/sdX}"\n'
        'if ! test -b "$DEV"; then echo "Error: $DEV is not a block device" >&2; exit 1; fi\n'
        "\n"
        'if [[ "$DEV" == *mmcblk* ]] || [[ "$DEV" == *nvme* ]]; then\n'
        '    BOOT="${DEV}p1"; ROOT="${DEV}p2"\n'
        "else\n"
        '    BOOT="${DEV}1"; ROOT="${DEV}2"\n'
        "fi\n"
        "\n"
        'echo "==> Restoring partition table"\n'
        'sfdisk "$DEV" < sfdisk.dump\n'
        "sleep 2; partprobe \"$DEV\" 2>/dev/null || true; sleep 1\n"
        "\n"
        'echo "==> Restoring MBR"\n'
        'gunzip -c mbr.bin.gz | dd of="$DEV" bs=1M count=1 conv=notrunc\n'
        "\n"
        'echo "==> Restoring boot partition"\n'
        'gunzip -c p1-boot.vfat.gz | dd of="$BOOT" bs=4M\n'
        "\n"
        'echo "==> Restoring root partition (this takes several minutes)"\n'
        f"{root_restore}\n"
        "\n"
        'echo "==> Checking + resizing root filesystem"\n'
        'e2fsck -f "$ROOT" || true\n'
        'resize2fs "$ROOT"\n'
        "\n"
        'echo "==> Done. You can now boot from $DEV"\n'
    ).encode()

    cancelled = False
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        try:
            _stream("MBR (1 MiB)",           f"sudo dd if={disk_dev} bs=1M count=1 2>/dev/null | {GZIP}", tmp / "mbr.bin.gz")
            _stream("Boot partition (FAT32)", f"sudo dd if={boot_dev} bs=4M 2>/dev/null | {GZIP}",         tmp / "p1-boot.vfat.gz")
            _stream(root_label,               root_cmd,                                                     tmp / root_file)
        except KeyboardInterrupt:
            cancelled = True

        if cancelled:
            if mixxx_was_running:
                pi_client.exec(f"sudo -u {_PI_USER} DISPLAY=:0 mixxx --settingsPath {_H}/.mixxx &", timeout=5)
            warn("Cancelled — no output written")
            return None

        print()
        with Step("Building manifest"):
            manifest_txt = _backup_manifest(pi_client)
            (tmp / "manifest.txt").write_bytes(manifest_txt)

        with Step("Writing archive"):
            (tmp / "restore.sh").write_bytes(restore_sh)
            (tmp / "sfdisk.dump").write_bytes(sfdisk_dump)
            with tarfile.open(out, "w") as tar:
                for name in ("mbr.bin.gz", "sfdisk.dump", "p1-boot.vfat.gz", root_file, "restore.sh", "manifest.txt"):
                    ti = tarfile.TarInfo(name=name)
                    src = tmp / name
                    ti.size = src.stat().st_size
                    if name == "restore.sh":
                        ti.mode = 0o755
                    with open(src, "rb") as fh:
                        tar.addfile(ti, fh)

    if mixxx_was_running:
        pi_client.exec(f"sudo -u {_PI_USER} DISPLAY=:0 mixxx --settingsPath {_H}/.mixxx &", timeout=5)
        if log_fn:
            log_fn("info", "Mixxx restarted")
        else:
            ok("Mixxx restarted")

    size_mb = out.stat().st_size / 1024**2
    summary = f"Backup complete — {size_mb:.0f} MB  →  {out}"
    if log_fn:
        log_fn("ok", summary)
        log_fn("info", "Restore (Linux):  tar xf <backup>.tar && sudo bash restore.sh /dev/sdX")
    else:
        print()
        ok(summary)
        ok("Restore (Linux):  tar xf <backup>.tar && sudo bash restore.sh /dev/sdX")
    return str(out)
