from __future__ import annotations

"""
Setup commands: SSH keys, DHCP server, hostname change, SSH recovery guide.

Extracted from xdj-pi-dev.py (lines 1102-1288).
"""

import subprocess
import textwrap
from pathlib import Path

import paramiko

from xdj_pi_dev._terminal import (
    _C, Step, section, ok, warn, fail,
)

# Project-specific SSH key (won't affect other SSH usage)
SSH_KEY_PATH = Path.home() / ".ssh" / "xdj_pi_ed25519"


# ─── SSH key setup ────────────────────────────────────────────────────────────

def setup_ssh_keys(pi_client) -> None:
    """
    Generate a project-specific ed25519 key pair and install it on the Pi.
    After this, the tool authenticates without a password.
    """
    section("SSH Key Setup")

    # 1. Generate key locally if not present
    if SSH_KEY_PATH.exists():
        ok(f"Key already exists: {SSH_KEY_PATH}")
    else:
        print(f"  Generating ed25519 key: {SSH_KEY_PATH}")
        r = subprocess.run(
            ["ssh-keygen", "-t", "ed25519", "-f", str(SSH_KEY_PATH),
             "-N", "", "-C", "xdj-pi-dev"],
            capture_output=True, text=True
        )
        if r.returncode != 0:
            fail(f"ssh-keygen failed: {r.stderr.strip()}")
            return
        ok(f"Key generated: {SSH_KEY_PATH}")

    pub_key = (SSH_KEY_PATH.with_suffix(".pub")).read_text().strip()

    # 2. Install on Pi
    print(f"  Installing public key on Pi ({pi_client.host})…")
    install_cmd = (
        f"mkdir -p ~/.ssh && chmod 700 ~/.ssh && "
        f"grep -qxF '{pub_key}' ~/.ssh/authorized_keys 2>/dev/null || "
        f"echo '{pub_key}' >> ~/.ssh/authorized_keys && "
        f"chmod 600 ~/.ssh/authorized_keys && echo installed"
    )
    r2 = pi_client.exec(install_cmd)
    if "installed" in r2["stdout"] or r2["rc"] == 0:
        ok("Public key installed on Pi")
    else:
        fail(f"Install failed: {r2['stderr'].strip()}")
        return

    # 3. Test key auth works before offering to disable password
    print("  Testing key auth…")
    test_ssh = paramiko.SSHClient()
    test_ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        test_ssh.connect(pi_client.host, username=pi_client.user,
                         key_filename=str(SSH_KEY_PATH),
                         look_for_keys=False, allow_agent=False, timeout=8)
        test_ssh.close()
        ok("Key auth confirmed working")
    except Exception as e:
        fail(f"Key auth test failed: {e}")
        print("  Password auth is still active. Fix the key issue before disabling it.")
        return

    # 4. Offer to disable password auth (skip prompt in TUI — no stdin available)
    from xdj_pi_dev._terminal import _tui_log_fn as _tui_fn
    if _tui_fn:
        ok("Key auth is working. Password auth left enabled (use CLI to disable).")
        return
    print()
    print("  Key auth is working. Optionally disable SSH password auth on Pi")
    print("  (more secure — only connections with this key will be accepted).")
    answer = input("  Disable password auth now? [y/N] ").strip().lower()
    if answer == "y":
        r3 = pi_client.exec(
            "sudo sed -i 's/^#*PasswordAuthentication.*/PasswordAuthentication no/' "
            "/etc/ssh/sshd_config && sudo systemctl reload ssh && echo done"
        )
        if "done" in r3["stdout"]:
            ok("Password auth disabled. Only key auth accepted.")
            print()
            print("  IMPORTANT: Keep the key file safe:")
            print(f"    {SSH_KEY_PATH}")
            print(f"    {SSH_KEY_PATH}.pub")
            print()
            print("  If you lose the key, use --restore-ssh to recover access.")
        else:
            fail(f"Could not update sshd_config: {r3['stderr'].strip()}")
    else:
        ok("Password auth left enabled (safe default)")


# ─── SSH recovery guide ───────────────────────────────────────────────────────

def restore_ssh() -> None:
    """Print step-by-step SSH recovery instructions — no network connection required."""
    section("SSH Recovery Guide")
    print(textwrap.dedent("""
    If you're locked out of the Pi (lost key, disabled password auth accidentally):

    ── Option A: Physical console ─────────────────────────────────────────────
    1. Connect a keyboard and HDMI monitor to the Pi.
    2. Press Ctrl+Alt+F2 to switch to tty2 (away from Mixxx on tty1).
    3. Log in: username xdj100sx, password xdj100sx
    4. Re-enable password auth:
         sudo nano /etc/ssh/sshd_config
         → Change: PasswordAuthentication no → yes
         sudo systemctl reload ssh
    5. Press Ctrl+Alt+F1 to return to Mixxx.

    ── Option B: Edit the SD card on another machine ──────────────────────────
    1. Power off the Pi. Remove the SD card.
    2. Mount the SD card on your machine (Linux/macOS native; Windows use DiskGenius or WSL).
    3. Edit: /etc/ssh/sshd_config
         → PasswordAuthentication yes
    4. Reinstall SD card, power on Pi.

    ── Option C: Install a new key without password auth ──────────────────────
    If you have a different SSH key that still works:
    1. ssh -i /path/to/other/key xdj100sx@<pi-ip>
    2. Then run --setup-ssh-keys to install the project key.

    ── Recovering the Pi IP if unknown ────────────────────────────────────────
    On the Pi console:    ip addr show eth0
    From this machine:    python3 xdj-pi-dev.py --discover
    """))


# ─── Pi DHCP setup ───────────────────────────────────────────────────────────

def setup_pi_dhcp(pi_client) -> None:
    """
    Configure the Pi to act as a DHCP server on eth0.
    After this, any machine plugged directly into the Pi gets an IP automatically
    — no manual network alias setup needed.
    """
    section("Pi DHCP Server Setup")
    print("  This installs dnsmasq on the Pi and configures it to auto-assign")
    print("  IP addresses to machines connected via direct cable.")
    print("  Pi's own IP stays at 192.168.10.2.")
    print()

    # Install dnsmasq
    print("  Installing dnsmasq…")
    r = pi_client.exec("sudo apt-get install -y dnsmasq 2>&1 | tail -3", timeout=120)
    if r["rc"] != 0:
        fail(f"apt-get failed: {r['stderr'].strip()}")
        return
    ok("dnsmasq installed")

    # Write config
    conf = textwrap.dedent("""\
        # XDJ direct-cable DHCP — managed by xdj-pi-dev.py
        interface=eth0
        bind-interfaces
        dhcp-range=192.168.10.100,192.168.10.200,255.255.255.0,12h
        # No gateway, no DNS — pure IP assignment for direct cable
        dhcp-option=3
        dhcp-option=6
    """)
    r2 = pi_client.exec(
        f"sudo mkdir -p /etc/dnsmasq.d && echo '{conf}' | sudo tee /etc/dnsmasq.d/xdj-direct.conf > /dev/null && echo ok"
    )
    if "ok" not in r2["stdout"]:
        fail(f"Could not write dnsmasq config: {r2['stderr'].strip()}")
        return
    ok("dnsmasq config written (/etc/dnsmasq.d/xdj-direct.conf)")

    # Enable and restart
    r3 = pi_client.exec(
        "sudo systemctl enable dnsmasq && sudo systemctl restart dnsmasq && echo ok"
    )
    if "ok" not in r3["stdout"]:
        fail(f"dnsmasq restart failed: {r3['stderr'].strip()}")
        return
    ok("dnsmasq running and enabled on boot")

    print()
    print("  Done. Next time you plug in via direct cable:")
    print("  • Your machine will get an IP in 192.168.10.100–200 automatically")
    print("  • No manual network config needed")
    print("  • XDJ100SX.local still works too")


# ─── Hostname change ──────────────────────────────────────────────────────────

def set_hostname(pi_client, new_hostname: str) -> None:
    """Change the Pi's hostname and restart avahi so mDNS updates immediately."""
    section(f"Set Hostname → {new_hostname}")

    old = pi_client.exec("hostname").get("stdout", "").strip()
    print(f"  Current hostname: {old}")

    r = pi_client.exec(
        f"sudo hostnamectl set-hostname {new_hostname} && "
        f"sudo sed -i 's/{old}/{new_hostname}/g' /etc/hosts && "
        f"sudo systemctl restart avahi-daemon 2>/dev/null; echo ok"
    )
    if "ok" in r["stdout"]:
        ok(f"Hostname changed to: {new_hostname}")
        print(f"  New mDNS address: {new_hostname}.local")
    else:
        fail(f"Failed: {r['stderr'].strip()}")
