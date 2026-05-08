#!/usr/bin/env python3
"""
XDJ-100SX Pi Developer Tool  v3
=================================
CLI developer tool + MCP server for Claude Code.
Works on macOS, Linux, and Windows.

AUTHORS
-------
  Marc Monka <marc.monka@gmail.com>
      Creator of the XDJ-100SX — original concept, firmware, Mixxx skin, and
      hardware adaptation of the Pioneer DJ CDJ-100S. Uses the original CDJ-100S
      PCB with added microcontroller (Teensy) to interface controls with a
      Raspberry Pi running Mixxx.
      https://github.com/marcmonka

  Jeancarlo Cardoso de Faria Filho (jaianlab) <jaianlabworks@gmail.com>
      Raspberry Pi Pico port (replacing Teensy), MCP server, multi-unit
      discovery, developer tooling, and Pi setup automation.
      https://github.com/jaianlab

CREDITS & NOTICES
-----------------
  Mixxx  <https://mixxx.org>
      Free, open-source DJ software powering the XDJ-100SX skin and MIDI
      mapping on the Pi. Mixxx is a project of the Mixxx Development Team
      and contributors, licensed under GPLv2+. This tool interacts with
      Mixxx but is not part of the Mixxx project.

  Pioneer DJ
      The CDJ-100S enclosure and PCB used in this project are products of
      Pioneer DJ Co., Ltd. The XDJ-100SX is an independent community project
      and is not affiliated with, endorsed by, or sponsored by Pioneer DJ.
      All Pioneer DJ trademarks and product names belong to their respective owners.

  Raspberry Pi
      Pi hardware and software trademarks are the property of Raspberry Pi Ltd.
      This tool targets Raspberry Pi hardware but is not affiliated with
      Raspberry Pi Ltd.

FIRST RUN:
  python3 xdj-pi-dev.py --check           # diagnose connection + environment
  python3 xdj-pi-dev.py --status          # Pi + Mixxx live status

CONNECTION (tried in order):
  1. --host flag
  2. XDJ_HOST environment variable
  3. XDJ100SX.local  (mDNS — works with any network topology)
  4. 192.168.10.2    (static IP fallback)

  Direct cable — one-time client setup:
    macOS:    sudo ifconfig en0 alias 192.168.10.1 255.255.255.0
    Linux:    sudo ip addr add 192.168.10.1/24 dev eth0
    Windows:  netsh interface ip set address "Ethernet" static 192.168.10.1 255.255.255.0

  Or run --setup-pi-dhcp once (on Pi) so the client gets an IP automatically —
  no manual configuration needed after that.

SETUP COMMANDS:
  python3 xdj-pi-dev.py --check                   # pre-flight: deps, connection, Mixxx
  python3 xdj-pi-dev.py --setup-pi-dhcp           # configure Pi to auto-assign IPs (do once)
  python3 xdj-pi-dev.py --setup-ssh-keys          # set up key-based SSH auth (more secure)
  python3 xdj-pi-dev.py --set-hostname NAME       # rename Pi (e.g. xdj-unit2 for multi-unit)
  python3 xdj-pi-dev.py --backup-image            # backup SD card to .tar archive (used blocks only)
  python3 xdj-pi-dev.py --backup-image backup.tar # backup to a specific path
  python3 xdj-pi-dev.py --restore-ssh             # recovery guide if SSH is locked out

SKIN DEVELOPMENT:
  python3 xdj-pi-dev.py --screenshot              # grab screen, open in viewer
  python3 xdj-pi-dev.py --screenshot --panel ks   # navigate to keyshift first
  python3 xdj-pi-dev.py --restart                 # restart Mixxx
  python3 xdj-pi-dev.py --push                    # push all skin files to Pi
  python3 xdj-pi-dev.py --push "*.qss"            # push only matching files
  python3 xdj-pi-dev.py --pull                    # pull skin files from Pi to repo
  python3 xdj-pi-dev.py --push-midi               # push MIDI mapping to Pi
  python3 xdj-pi-dev.py --pull-midi               # pull MIDI mapping from Pi
  python3 xdj-pi-dev.py --midi-mon                # stream live MIDI messages (Ctrl-C to stop)
  python3 xdj-pi-dev.py --watch [--panel PANEL]   # watch, auto-push, screenshot on save

PICO FIRMWARE:
  python3 xdj-pi-dev.py --setup-pico-cli          # install arduino-cli on Pi (one-time)
  python3 xdj-pi-dev.py --pico-compile            # compile firmware on Pi (stops/restarts Mixxx)
  python3 xdj-pi-dev.py --pico-compile --pico-bootloader  # compile + flash in one step
  python3 xdj-pi-dev.py --pico-bootloader         # reset Pico to bootloader via MIDI
  python3 xdj-pi-dev.py --pico-flash FILE.uf2     # flash a local .uf2 via Pi
  python3 xdj-pi-dev.py --analyze                 # live GPIO signal analyzer (curses dashboard)

OTHER:
  python3 xdj-pi-dev.py --discover                # find all Pi units on the network
  python3 xdj-pi-dev.py --cmd 'CMD'               # run arbitrary SSH command
  python3 xdj-pi-dev.py --host 192.168.1.42       # target a specific IP/hostname

PANEL NAMES (--panel):
  hotcue | hc    beatloop | bl    keyshift | ks    beatjump | bj    stems | st

MCP SERVER (Claude Code):
  Add to ~/.claude.json under "mcpServers":
    "xdj-pi": {
      "command": "python3",
      "args": ["/absolute/path/to/tools/xdj-pi-dev.py"]
    }
  Run with no arguments to start in MCP server mode.

DEPENDENCIES:
  pip install paramiko
  pip install watchdog          # optional — faster file watching (falls back to polling)
"""

from __future__ import annotations

import argparse
import base64
import concurrent.futures
import fnmatch
import itertools
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
from pathlib import Path

# ─── Dependency check ─────────────────────────────────────────────────────────

try:
    import paramiko
except ImportError:
    print("Missing dependency: paramiko")
    print("Run:  pip install paramiko")
    sys.exit(1)

# ─── Configuration ────────────────────────────────────────────────────────────

_DEFAULT_HOSTS = ["XDJ100SX.local", "192.168.10.2"]
_TOOL_ABOUT = (__doc__ or "").split("FIRST RUN")[0].strip()

PI_USER      = os.environ.get("XDJ_USER", "xdj100sx")
PI_PASS      = os.environ.get("XDJ_PASS", "xdj100sx")
PI_SKIN      = f"/home/{PI_USER}/.mixxx/skins/XDJ100SX"
PI_MIXXX_ENV = f"DISPLAY=:0 XAUTHORITY=/home/{PI_USER}/.Xauthority"
PI_PICO_PORT = "/dev/ttyACM0"

# SSH key generated by --setup-ssh-keys (project-specific, won't affect other SSH usage)
SSH_KEY_PATH = Path.home() / ".ssh" / "xdj_pi_ed25519"

REPO_ROOT = Path(__file__).resolve().parent.parent
REPO_SKIN = REPO_ROOT / "mixxx" / "SKIN" / "XDJ100SX"

PANELS = {
    "hotcue":   (368, 57), "hc":  (368, 57),
    "beatloop": (464, 57), "bl":  (464, 57),
    "keyshift": (560, 57), "ks":  (560, 57),
    "beatjump": (656, 57), "bj":  (656, 57),
    "stems":    (752, 57), "st":  (752, 57),
}

FILE_PANEL = {
    "hotcues.xml":  "hotcue",
    "beatloop.xml": "beatloop",
    "keyshift.xml": "keyshift",
    "beatjump.xml": "beatjump",
    "stems.xml":    "stems",
}

REPO_MIDI    = REPO_ROOT / "mixxx" / "MIDI"
PI_MIDI_DIR  = f"/home/{PI_USER}/.mixxx/controllers"
MIDI_FILES   = ["XDJ100SX.midi.xml", "XDJ100SX.js"]


# ─── Terminal UI ──────────────────────────────────────────────────────────────

from xdj_pi_dev._terminal import _C, _COLOR, Step, section, ok, warn, fail, _log_line  # noqa: F401
from xdj_pi_dev.messages import MSG
from xdj_pi_dev.config import is_pico_board, get_board
import itertools as _itertools  # used by Step spinner (re-exported via _terminal)
# _tui_log_fn is managed in _terminal; expose it here for legacy callers
import xdj_pi_dev._terminal as _term
def _set_tui_log_fn(fn) -> None: _term._tui_log_fn = fn  # noqa: ANN001

# ─── Platform helpers ─────────────────────────────────────────────────────────

def open_image(path: Path) -> None:
    """Open an image in the default viewer — macOS, Linux, Windows."""
    s = str(path)
    if sys.platform == "darwin":
        subprocess.run(["open", s], check=False)
    elif sys.platform == "win32":
        os.startfile(s)
    else:
        subprocess.run(["xdg-open", s], check=False)


def tmp_path(name: str) -> Path:
    return Path(tempfile.gettempdir()) / name


# ─── Network helpers ──────────────────────────────────────────────────────────

def _port_open(host: str, port: int = 22, timeout: float = 2.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (socket.timeout, OSError):
        return False


def resolve_host(candidates: list[str]) -> str | None:
    """Return the first candidate with port 22 reachable."""
    for host in candidates:
        if _port_open(host):
            return host
    return None


def discover_units(extra_hosts: list[str] | None = None, subnet: str = "192.168.10") -> list[tuple[str, str]]:
    """
    Scan for Pi units: mDNS names first, then subnet sweep.
    Returns list of (host, hostname) tuples for reachable units.
    """
    candidates: list[str] = list(extra_hosts or [])
    candidates += ["XDJ100SX.local"] + [f"XDJ100SX-{i}.local" for i in range(1, 9)]
    candidates += [f"{subnet}.{i}" for i in range(1, 255)]

    def check(host: str) -> tuple[str, str] | None:
        if not _port_open(host, timeout=0.4):
            return None
        try:
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(host, username=PI_USER, password=PI_PASS,
                        timeout=3, allow_agent=False, look_for_keys=False)
            _, out, _ = ssh.exec_command("hostname", timeout=3)
            hostname = out.read().decode().strip()
            ssh.close()
            return (host, hostname)
        except Exception:
            return None

    print("Scanning… (this takes a few seconds)")
    found: list[tuple[str, str]] = []
    seen: set[str] = set()
    with concurrent.futures.ThreadPoolExecutor(max_workers=60) as pool:
        for r in pool.map(check, candidates):
            if r and r[0] not in seen:
                seen.add(r[0])
                found.append(r)
    return found


def direct_cable_instructions() -> str:
    """Platform-specific instructions for setting up the direct-cable network."""
    if sys.platform == "darwin":
        iface = "en0  (or en5/en6 if using a USB-C adapter — check: ifconfig | grep -B1 'inet 192')"
        cmd   = "sudo ifconfig en0 alias 192.168.10.1 255.255.255.0"
        note  = "Re-run after each Mac reboot (not persistent)."
    elif sys.platform == "win32":
        iface = "Ethernet (the interface connected to the Pi)"
        cmd   = 'netsh interface ip set address "Ethernet" static 192.168.10.1 255.255.255.0'
        note  = "Replace 'Ethernet' with the exact interface name from: ipconfig /all"
    else:
        iface = "eth0 (or enp3s0 / ens3 — check: ip link)"
        cmd   = "sudo ip addr add 192.168.10.1/24 dev eth0"
        note  = "To make it persistent: add to /etc/network/interfaces or create a NetworkManager connection."
    return (
        f"Interface: {iface}\n"
        f"Command:   {cmd}\n"
        f"Note:      {note}"
    )


# ─── Pi SSH/SFTP client ───────────────────────────────────────────────────────

class PiClient:
    def __init__(self, host: str, user: str, password: str):
        self.host     = host
        self.user     = user
        self.password = password
        self._ssh:  paramiko.SSHClient | None = None
        self._sftp: paramiko.SFTPClient | None = None

    def _alive(self) -> bool:
        try:
            t = self._ssh and self._ssh.get_transport()
            return bool(t and t.is_active())
        except Exception:
            return False

    def _connect(self) -> None:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        # Try project key first if it exists, then fall back to password
        if SSH_KEY_PATH.exists():
            try:
                ssh.connect(
                    self.host, username=self.user,
                    key_filename=str(SSH_KEY_PATH),
                    look_for_keys=False, allow_agent=False, timeout=10,
                )
                self._ssh  = ssh
                self._sftp = ssh.open_sftp()
                return
            except paramiko.AuthenticationException:
                pass

        ssh.connect(
            self.host, username=self.user, password=self.password,
            look_for_keys=False, allow_agent=False, timeout=10,
        )
        self._ssh  = ssh
        self._sftp = ssh.open_sftp()

    def _ok(self) -> None:
        if not self._alive():
            self._connect()

    def exec(self, command: str, timeout: int = 30) -> dict:
        self._ok()
        assert self._ssh
        _, stdout, stderr = self._ssh.exec_command(command, timeout=timeout)
        out = stdout.read().decode(errors="replace")
        err = stderr.read().decode(errors="replace")
        rc  = stdout.channel.recv_exit_status()
        return {"stdout": out, "stderr": err, "rc": rc}

    def read_text(self, path: str) -> str:
        self._ok()
        assert self._sftp
        with self._sftp.open(path, "rb") as f:
            return f.read().decode(errors="replace")

    def read_bytes(self, path: str) -> bytes:
        self._ok()
        assert self._sftp
        with self._sftp.open(path, "rb") as f:
            return f.read()

    def write_text(self, path: str, content: str | bytes) -> None:
        self.write_bytes(path, content.encode() if isinstance(content, str) else content)

    def write_bytes(self, path: str, data: bytes) -> None:
        self._ok()
        assert self._sftp
        with self._sftp.open(path, "wb") as f:
            f.write(data)

    def listdir(self, path: str) -> list[str]:
        self._ok()
        assert self._sftp
        return sorted(self._sftp.listdir(path))

    def exec_stream(self, command: str, timeout: int = 600) -> int:
        """
        Run command and feed each line through _log_line() as it arrives.
        Returns the exit code.
        """
        self._ok()
        assert self._ssh
        transport = self._ssh.get_transport()
        assert transport
        channel = transport.open_session()
        channel.set_combine_stderr(True)
        channel.exec_command(command)

        buf = b""
        while True:
            if channel.recv_ready():
                buf += channel.recv(4096)
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    _log_line(line.decode(errors="replace").rstrip())
            elif channel.exit_status_ready() and not channel.recv_ready():
                break
            else:
                time.sleep(0.05)

        if buf.strip():
            _log_line(buf.decode(errors="replace").rstrip())

        return channel.recv_exit_status()


# Module-level client — set by init_client(); None until first successful connection
pi: PiClient | None = None


def init_client(host_override: str | None = None) -> str:
    """Resolve target host, create the module-level PiClient, return host used."""
    global pi, PI_USER, PI_PASS
    from xdj_pi_dev.config import get_ssh_user, get_ssh_pass
    PI_USER = get_ssh_user()
    PI_PASS = get_ssh_pass()

    if host_override:
        candidates = [host_override]
    else:
        env = os.environ.get("XDJ_HOST")
        candidates = [env] if env else _DEFAULT_HOSTS

    host = resolve_host(candidates)
    if not host:
        tried = ", ".join(candidates)
        msg = MSG["cant_reach_pi_detail"].format(
            tried=tried,
            instructions=textwrap.indent(direct_cable_instructions(), "  "),
        )
        # Raise so TUI worker catches it — sys.exit kills the whole TUI process
        raise ConnectionError(msg)

    pi = PiClient(host, PI_USER, PI_PASS)
    return host


# ─── Panel navigation ─────────────────────────────────────────────────────────

def navigate_panel(panel_key: str) -> None:
    key = panel_key.lower().strip()
    coords = PANELS.get(key)
    if not coords:
        return
    x, y = coords
    pi.exec(f"{PI_MIXXX_ENV} xdotool mousemove {x} {y} click 1", timeout=5)
    time.sleep(0.4)


# ─── Actions ──────────────────────────────────────────────────────────────────

def restart_mixxx(panel: str | None = None) -> str:
    pi.exec("killall mixxx 2>/dev/null; true")
    time.sleep(6)
    result = pi.exec("pgrep -a mixxx")
    pid = result["stdout"].strip()
    msg = (f"Mixxx restarted (PID {pid.split()[0]})" if pid
           else "WARNING: Mixxx PID not found — may still be starting")
    if panel:
        time.sleep(1)
        navigate_panel(panel)
    return msg


def take_screenshot(panel: str | None = None) -> tuple[bytes | None, str | None]:
    """Navigate to `panel` then capture. Returns (bytes, None) or (None, error)."""
    if panel:
        navigate_panel(panel)
    pi.exec("rm -f /tmp/xdj_dev_screen.png")
    r = pi.exec(f"{PI_MIXXX_ENV} scrot /tmp/xdj_dev_screen.png 2>&1", timeout=10)
    if r["rc"] != 0:
        return None, (r["stdout"] + r["stderr"]).strip()
    return pi.read_bytes("/tmp/xdj_dev_screen.png"), None


def _history_dir(base: Path, direction: str, ts: str) -> Path:
    """direction: 'pushed' or 'pulled'. History lives inside the reference subject."""
    return base / ".history" / direction / ts


def push_skin(pattern: str = "*", backup_remote: bool = False) -> list[str]:
    ts   = time.strftime("%Y%m%d-%H%M%S")
    hist = _history_dir(REPO_SKIN.parent, "pushed", ts)
    pushed = []
    for f in sorted(REPO_SKIN.rglob("*")):
        if f.is_file() and fnmatch.fnmatch(f.name, pattern):
            rel    = f.relative_to(REPO_SKIN)
            remote = f"{PI_SKIN}/{rel.as_posix()}"
            if backup_remote:
                pi.exec(f"cp -p '{remote}' '{remote}.bak-{ts}' 2>/dev/null || true")
            data = f.read_bytes()
            hist.mkdir(parents=True, exist_ok=True)
            (hist / f.name).write_bytes(data)
            pi.write_bytes(remote, data)
            pushed.append(str(rel))
    return pushed


def push_midi(backup_remote: bool = False) -> list[str]:
    """Push MIDI mapping files from docs/midi/ to ~/.mixxx/controllers/ on Pi."""
    ts   = time.strftime("%Y%m%d-%H%M%S")
    hist = _history_dir(REPO_MIDI, "pushed", ts)
    pushed = []
    for fname in MIDI_FILES:
        local = REPO_MIDI / fname
        if not local.exists():
            warn(f"Not found locally: {local}")
            continue
        if backup_remote:
            pi.exec(f"cp -p '{PI_MIDI_DIR}/{fname}' '{PI_MIDI_DIR}/{fname}.bak-{ts}' 2>/dev/null || true")
        data = local.read_bytes()
        hist.mkdir(parents=True, exist_ok=True)
        (hist / fname).write_bytes(data)
        pi.write_bytes(f"{PI_MIDI_DIR}/{fname}", data)
        pushed.append(fname)
    return pushed


def pull_midi(backup: bool = False) -> list[str]:
    """Pull MIDI mapping files from ~/.mixxx/controllers/ on Pi to docs/midi/."""
    ts   = time.strftime("%Y%m%d-%H%M%S")
    hist = _history_dir(REPO_MIDI, "pulled", ts)
    pulled = []
    for fname in MIDI_FILES:
        remote = f"{PI_MIDI_DIR}/{fname}"
        try:
            data  = pi.read_bytes(remote)
            local = REPO_MIDI / fname
            if backup and local.exists():
                local.rename(local.parent / f"{local.name}.bak-{ts}")
            hist.mkdir(parents=True, exist_ok=True)
            (hist / fname).write_bytes(data)
            local.write_bytes(data)
            pulled.append(fname)
        except Exception as e:
            warn(f"Skipped {fname}: {e}")
    return pulled


def pull_skin(backup: bool = False) -> list[str]:
    ts   = time.strftime("%Y%m%d-%H%M%S")
    hist = _history_dir(REPO_SKIN.parent, "pulled", ts)
    pulled = []
    for fname in pi.listdir(PI_SKIN):
        remote = f"{PI_SKIN}/{fname}"
        try:
            data  = pi.read_bytes(remote)
            local = REPO_SKIN / fname
            if backup and local.exists():
                local.rename(local.parent / f"{local.name}.bak-{ts}")
            hist.mkdir(parents=True, exist_ok=True)
            (hist / fname).write_bytes(data)
            local.write_bytes(data)
            pulled.append(fname)
        except Exception as e:
            warn(f"Skipped {fname}: {e}")
    return pulled


# ─── Pico firmware tools ──────────────────────────────────────────────────────

from xdj_pi_dev.pico_tools import pico_bootloader, pico_flash  # noqa: F401

# ─── MIDI monitor ─────────────────────────────────────────────────────────────

from xdj_pi_dev.midi import midi_monitor  # noqa: F401

# ─── Signal Analyzer ─────────────────────────────────────────────────────────

from xdj_pi_dev.signal_analyzer import (
    SA_PIN_NAMES, SA_BUTTON_PINS, SA_JOG_PINS, SA_BROWSE_PINS, SA_LED_PINS, SA_ALL_PINS,
    run_signal_analyzer_web, run_signal_analyzer_cli,
)


# ─── Pico compile ─────────────────────────────────────────────────────────────

from xdj_pi_dev.pico_tools import (
    setup_pico_cli, pico_compile, DEFAULT_BOARD, BOARD_PROFILES,  # noqa: F401
    REPO_FIRMWARE,
)

# ─── Setup commands ───────────────────────────────────────────────────────────

from xdj_pi_dev.setup_cmds import (  # noqa: F401
    setup_ssh_keys, restore_ssh, setup_pi_dhcp, set_hostname,
)

# ─── Pi image backup ──────────────────────────────────────────────────────────

from xdj_pi_dev.backup import backup_pi_image, verify_backup  # noqa: F401

# ─── Watch mode ───────────────────────────────────────────────────────────────

from xdj_pi_dev.watch import watch_mode, _watch_loop  # noqa: F401

# ─── Pre-flight check ─────────────────────────────────────────────────────────

def run_check(host_override: str | None = None) -> None:
    section("XDJ Pi Developer Tool — Pre-flight Check")

    # 1. Python version
    pv = sys.version_info
    if pv >= (3, 8):
        ok(f"Python {pv.major}.{pv.minor}.{pv.micro}")
    else:
        fail(f"Python {pv.major}.{pv.minor} — need 3.8+")

    # 2. paramiko
    ok(f"paramiko {paramiko.__version__}")

    # 3. watchdog (optional)
    try:
        import watchdog
        ver = getattr(watchdog, "__version__", "installed")
        ok(f"watchdog {ver} (faster file watching)")
    except ImportError:
        warn("watchdog not installed — watch mode uses 1s polling. pip install watchdog")

    # 4. ssh-keygen
    if shutil.which("ssh-keygen"):
        ok("ssh-keygen found")
    else:
        warn("ssh-keygen not found — --setup-ssh-keys won't work")

    # 5. SSH key
    if SSH_KEY_PATH.exists():
        ok(f"Project SSH key: {SSH_KEY_PATH}")
    else:
        warn(f"No project SSH key yet — run --setup-ssh-keys for passwordless auth")

    # 6. Repo skin dir
    if REPO_SKIN.exists():
        files = list(REPO_SKIN.glob("*.xml")) + list(REPO_SKIN.glob("*.qss"))
        ok(f"Repo skin dir: {REPO_SKIN}  ({len(files)} skin files)")
    else:
        fail(f"Repo skin dir not found: {REPO_SKIN}")

    print()
    section("Network")

    # 7. Resolve Pi
    if host_override:
        candidates = [host_override]
    else:
        env = os.environ.get("XDJ_HOST")
        candidates = [env] if env else _DEFAULT_HOSTS

    print(f"  Trying: {', '.join(candidates)}")
    host = resolve_host(candidates)
    if not host:
        fail("Pi not reachable on port 22")
        print()
        print("  If using a direct cable, set up the network alias:")
        print(textwrap.indent(direct_cable_instructions(), "  "))
        print()
        print("  Or run --setup-pi-dhcp after connecting via any route.")
        return

    ok(f"Pi reachable at: {host}")

    global PI_USER, PI_PASS
    pi_c = PiClient(host, PI_USER, PI_PASS)
    global pi
    pi = pi_c

    # 8. SSH auth
    try:
        r = pi.exec("echo ssh_ok", timeout=8)
        if "ssh_ok" in r["stdout"]:
            auth_method = "key" if SSH_KEY_PATH.exists() else "password"
            ok(f"SSH connected ({auth_method} auth)")
        else:
            fail("SSH connected but shell not responding")
            return
    except Exception as e:
        fail(f"SSH auth failed: {e}")
        print("  Check username/password or run --setup-ssh-keys")
        return

    print()
    section("Pi Status")

    # 9. Mixxx
    r = pi.exec("pgrep -a mixxx")
    if r["stdout"].strip():
        pid = r["stdout"].strip().split()[0]
        ok(f"Mixxx running (PID {pid})")
    else:
        warn("Mixxx not running")

    # 10. Display
    r = pi.exec(f"{PI_MIXXX_ENV} xdotool getactivewindow 2>/dev/null && echo display_ok || echo display_fail")
    if "display_ok" in r["stdout"]:
        ok("Display reachable (xdotool works)")
    else:
        warn("Display not reachable — screenshot/navigate won't work")

    # 11. scrot
    r = pi.exec("which scrot")
    if r["rc"] == 0:
        ok("scrot installed (screenshots work)")
    else:
        fail("scrot not installed on Pi — run: sudo apt install scrot")

    # 12. Audio
    r = pi.exec("aplay -l 2>/dev/null | grep card")
    if r["stdout"].strip():
        for line in r["stdout"].strip().splitlines():
            ok(f"Audio: {line.strip()}")
    else:
        warn("No ALSA sound cards found")

    # 13. MIDI (Pico)
    r = pi.exec("ls /dev/ttyACM* 2>/dev/null || amidi -l 2>/dev/null | grep XDJ || echo none")
    if "none" not in r["stdout"]:
        ok(f"MIDI/serial device: {r['stdout'].strip()}")
    else:
        warn("No Pico/MIDI device found — check USB connection")

    # 14. USB media
    r = pi.exec("ls /media/ 2>/dev/null")
    if r["stdout"].strip():
        ok(f"USB media: /media/{r['stdout'].strip()}")
    else:
        warn("No USB media mounted (normal if no stick inserted)")

    # 15. mDNS
    r = pi.exec("hostname")
    hostname = r["stdout"].strip()
    ok(f"Pi hostname: {hostname}  ({hostname}.local via mDNS)")

    # 16. dnsmasq (Pi DHCP)
    r = pi.exec("systemctl is-active dnsmasq 2>/dev/null || echo inactive")
    if r["stdout"].strip() == "active":
        ok("dnsmasq running (Pi auto-assigns IPs to connected machines)")
    else:
        warn("dnsmasq not running — connected machines may need manual IP setup")
        print("    Run --setup-pi-dhcp to fix this")

    print()
    print(f"  Connected to: {host}")
    print()


# ─── CLI status ───────────────────────────────────────────────────────────────

def cli_status() -> None:
    r = pi.exec(
        "echo '=== Pi ===' && hostname && ip addr show eth0 | grep 'inet ' && "
        "echo '=== Mixxx ===' && pgrep -a mixxx && "
        "echo '=== Audio ===' && aplay -l 2>/dev/null | grep card && "
        "echo '=== USB ===' && ls /media/ 2>/dev/null && "
        "echo '=== Pico ===' && ls /dev/ttyACM* 2>/dev/null || true"
    )
    print(f"Connected to: {pi.host}")
    print(r["stdout"])


# ─── MCP server ───────────────────────────────────────────────────────────────

MCP_TOOLS = [
    {
        "name": "run_command",
        "description": "Run a shell command on the Pi via SSH.",
        "inputSchema": {
            "type": "object",
            "properties": {"command": {"type": "string"}},
            "required": ["command"],
        },
    },
    {
        "name": "read_file",
        "description": "Read a text file from the Pi.",
        "inputSchema": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "Absolute path on Pi"}},
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": "Write a text file to the Pi.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path":    {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "list_files",
        "description": "List files in a Pi directory (default: skin dir).",
        "inputSchema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
        },
    },
    {
        "name": "restart_mixxx",
        "description": "Kill Mixxx and wait for xinitrc to restart it.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "panel": {
                    "type": "string",
                    "description": "Navigate to this panel after restart",
                }
            },
        },
    },
    {
        "name": "take_screenshot",
        "description": "Capture the Pi display. Pass panel to navigate first.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "panel": {
                    "type": "string",
                    "description": "Panel tab to show before screenshotting",
                }
            },
        },
    },
    {
        "name": "navigate_panel",
        "description": "Click a skin panel tab.",
        "inputSchema": {
            "type": "object",
            "properties": {"panel": {"type": "string"}},
            "required": ["panel"],
        },
    },
    {
        "name": "push_skin_file",
        "description": "Upload one skin file from the local repo to the Pi.",
        "inputSchema": {
            "type": "object",
            "properties": {"filename": {"type": "string"}},
            "required": ["filename"],
        },
    },
    {
        "name": "pull_skin_file",
        "description": "Download one skin file from the Pi to the local repo.",
        "inputSchema": {
            "type": "object",
            "properties": {"filename": {"type": "string"}},
            "required": ["filename"],
        },
    },
    {
        "name": "push_skin",
        "description": "Push all local skin files (or a glob subset) to the Pi.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "glob": {"type": "string", "description": "Filename glob, e.g. '*.qss'. Omit for all files."},
            },
        },
    },
    {
        "name": "pull_skin",
        "description": "Pull all skin files from Pi to local repo.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "push_midi",
        "description": "Push local MIDI mapping files to Pi controllers directory.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "pull_midi",
        "description": "Pull MIDI mapping files from Pi to local midi directory.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "check",
        "description": "Run preflight: verify SSH connection, Mixxx status, Pico MIDI visibility.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "pico_bootloader",
        "description": "Reset Pico into UF2 bootloader mode (MIDI trigger).",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "pico_flash",
        "description": "Flash a .uf2 file to the Pico.",
        "inputSchema": {
            "type": "object",
            "properties": {"local_path": {"type": "string"}},
            "required": ["local_path"],
        },
    },
    {
        "name": "discover_units",
        "description": "Scan the network for all reachable XDJ Pi units. Returns hostnames and IPs.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "select_unit",
        "description": "Switch the active connection to a specific XDJ Pi unit by hostname or IP.",
        "inputSchema": {
            "type": "object",
            "properties": {"host": {"type": "string", "description": "Hostname or IP of the unit to connect to"}},
            "required": ["host"],
        },
    },
]


def _call_tool(name: str, args: dict) -> list[dict]:
    if name == "run_command":
        r = pi.exec(args["command"])
        parts = []
        if r["stdout"]: parts.append(r["stdout"].rstrip())
        if r["stderr"]: parts.append(f"[stderr] {r['stderr'].rstrip()}")
        parts.append(f"[exit {r['rc']}]")
        return [{"type": "text", "text": "\n".join(parts)}]

    if name == "read_file":
        return [{"type": "text", "text": pi.read_text(args["path"])}]

    if name == "write_file":
        pi.write_text(args["path"], args["content"])
        return [{"type": "text", "text": f"Written: {args['path']}"}]

    if name == "list_files":
        files = pi.listdir(args.get("path", PI_SKIN))
        return [{"type": "text", "text": "\n".join(files)}]

    if name == "restart_mixxx":
        return [{"type": "text", "text": restart_mixxx(panel=args.get("panel"))}]

    if name == "take_screenshot":
        data, err = take_screenshot(panel=args.get("panel"))
        if err:
            return [{"type": "text", "text": f"Screenshot failed: {err}"}]
        return [{"type": "image", "data": base64.b64encode(data).decode(), "mimeType": "image/png"}]

    if name == "navigate_panel":
        navigate_panel(args["panel"])
        return [{"type": "text", "text": f"Navigated to {args['panel']}"}]

    if name == "push_skin_file":
        fname = args["filename"]
        local = REPO_SKIN / fname
        if not local.exists():
            return [{"type": "text", "text": f"Not found locally: {local}"}]
        pi.write_bytes(f"{PI_SKIN}/{fname}", local.read_bytes())
        return [{"type": "text", "text": f"Pushed {fname} → Pi"}]

    if name == "pull_skin_file":
        fname = args["filename"]
        data  = pi.read_bytes(f"{PI_SKIN}/{fname}")
        local = REPO_SKIN / fname
        local.parent.mkdir(parents=True, exist_ok=True)
        local.write_bytes(data)
        return [{"type": "text", "text": f"Pulled {fname} → {local}"}]

    if name == "push_skin":
        pushed = push_skin(glob=args.get("glob", "*"))
        return [{"type": "text", "text": f"Pushed {len(pushed)} file(s): {', '.join(pushed)}"}]

    if name == "pull_skin":
        pulled = pull_skin()
        return [{"type": "text", "text": f"Pulled {len(pulled)} file(s): {', '.join(pulled)}"}]

    if name == "push_midi":
        pushed = push_midi()
        return [{"type": "text", "text": f"Pushed {len(pushed)} MIDI file(s): {', '.join(pushed)}"}]

    if name == "pull_midi":
        pulled = pull_midi()
        return [{"type": "text", "text": f"Pulled {len(pulled)} MIDI file(s): {', '.join(pulled)}"}]

    if name == "check":
        import io, contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            run_check()
        return [{"type": "text", "text": buf.getvalue()}]

    if name == "pico_bootloader":
        return [{"type": "text", "text": pico_bootloader(pi)}]

    if name == "pico_flash":
        return [{"type": "text", "text": pico_flash(pi, args["local_path"])}]

    if name == "discover_units":
        units = discover_units()
        if not units:
            return [{"type": "text", "text": "No XDJ Pi units found on the network."}]
        lines = "\n".join(f"  {host}  ({hostname})" for host, hostname in units)
        return [{"type": "text", "text": f"Found {len(units)} unit(s):\n{lines}"}]

    if name == "select_unit":
        host = init_client(host_override=args["host"])
        return [{"type": "text", "text": f"Switched active connection to: {host}"}]

    return [{"type": "text", "text": f"Unknown tool: {name}"}]


def _mcp_send(obj: dict) -> None:
    sys.stdout.buffer.write(json.dumps(obj).encode() + b"\n")
    sys.stdout.buffer.flush()


def run_mcp_server() -> None:
    print("XDJ Pi MCP server started.", file=sys.stderr)
    print("For CLI use: python3 xdj-pi-dev.py --help", file=sys.stderr)
    for line in sys.stdin.buffer:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        method = msg.get("method", "")
        rid    = msg.get("id")

        if method == "initialize":
            _mcp_send({
                "jsonrpc": "2.0", "id": rid,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "xdj-pi-dev", "version": "3.0.0"},
                },
            })
        elif method == "notifications/initialized":
            pass
        elif method == "tools/list":
            _mcp_send({"jsonrpc": "2.0", "id": rid, "result": {"tools": MCP_TOOLS}})
        elif method == "tools/call":
            p = msg.get("params", {})
            try:
                content = _call_tool(p.get("name", ""), p.get("arguments", {}))
                _mcp_send({"jsonrpc": "2.0", "id": rid, "result": {"content": content}})
            except Exception as exc:
                _mcp_send({
                    "jsonrpc": "2.0", "id": rid,
                    "error": {"code": -32000, "message": str(exc)},
                })
        elif rid is not None:
            _mcp_send({
                "jsonrpc": "2.0", "id": rid,
                "error": {"code": -32601, "message": f"Unknown method: {method}"},
            })


# ─── Main ─────────────────────────────────────────────────────────────────────

# ─── Textual TUI ──────────────────────────────────────────────────────────────

try:
    from textual.app import App, ComposeResult
    from textual.binding import Binding
    from textual.containers import Horizontal, Vertical, ScrollableContainer
    from textual.screen import ModalScreen
    from textual.widgets import Button, Footer, Header, Input, Label, RichLog, Static
    from textual import work as _twork
    _TEXTUAL = True
except ImportError:
    _TEXTUAL = False


if _TEXTUAL:
    from textual.widgets import Select  # noqa: E402

    _BOARD_META = {
        "pico":    ("Raspberry Pi Pico",   "Full support — recommended"),
        "pico2":   ("Raspberry Pi Pico 2", "Full support"),
        "teensy":  ("Teensy 4.x",          "Skin & MIDI only (design phase)"),
        "unknown": ("Other / unknown",     "Skin & MIDI tools only"),
    }

    _BOARD_SPECS = {
        "pico":    "MCU: RP2040 · 133 MHz\nRAM: 264 KB · Flash: 2 MB\nUSB boot (UF2)",
        "pico2":   "MCU: RP2350 · 150 MHz\nRAM: 520 KB · Flash: 4 MB\nUSB boot (UF2)",
        "teensy":  "MCU: iMXRT1062 · 600 MHz\nRAM: 1 MB · Flash: 2 MB\nUSB native",
        "unknown": "Use if you're not sure.\nSkin & MIDI tools work\nfor any board.",
    }

    class BoardSelectScreen(ModalScreen):  # type: ignore[misc]
        """Board selection screen — shows board images with background removed."""

        DEFAULT_CSS = """
        BoardSelectScreen { align: center middle; }

        #board-dialog {
            background: $panel;
            border: solid $primary;
            padding: 1 2;
            width: 88;
            height: auto;
        }
        #board-title {
            width: 100%;
            text-align: center;
            text-style: bold;
            color: $primary;
            margin-bottom: 1;
        }
        #board-cards {
            layout: horizontal;
            height: auto;
            width: 100%;
        }
        .board-card {
            width: 1fr;
            height: auto;
            border: tall $panel-lighten-3;
            padding: 0 1;
            margin: 0 1;
            background: $panel-lighten-1;
        }
        .board-card.-selected {
            border: tall $primary;
            background: $panel-lighten-2;
        }
        .board-specs {
            width: 100%;
            color: $text-muted;
            margin-bottom: 1;
            height: 5;
        }
        .board-name {
            width: 100%;
            text-align: center;
            text-style: bold;
            color: $text;
        }
        .board-desc {
            width: 100%;
            text-align: center;
            color: $text-muted;
        }
        .btn-sel {
            width: 100%;
            margin-top: 1;
        }
        #board-footer {
            width: 100%;
            align: right middle;
            height: 3;
            margin-top: 1;
        }
        """

        def __init__(self, current: str = "pico") -> None:
            super().__init__()
            self._selected = current

        def compose(self) -> ComposeResult:
            with Vertical(id="board-dialog"):
                yield Label("What's inside your DJ unit?", id="board-title")
                with Horizontal(id="board-cards"):
                    for key, (name, desc) in _BOARD_META.items():
                        is_sel = key == self._selected
                        card_cls = "board-card" + (" -selected" if is_sel else "")
                        with Vertical(classes=card_cls, id=f"card-{key}"):
                            yield Static(
                                _BOARD_SPECS.get(key, ""),
                                classes="board-specs",
                            )
                            yield Label(name, classes="board-name")
                            yield Label(desc, classes="board-desc")
                            yield Button(
                                "✓ Selected" if is_sel else "Select",
                                id=f"btn-sel-{key}",
                                variant="primary" if is_sel else "default",
                                classes="btn-sel",
                            )
                with Horizontal(id="board-footer"):
                    yield Button("Save & Continue →", id="btn-board-save", variant="success")

        def on_button_pressed(self, event: Button.Pressed) -> None:
            event.stop()
            bid = event.button.id or ""

            if bid == "btn-board-save":
                from xdj_pi_dev.config import update_config
                update_config(board=self._selected)
                self.dismiss(self._selected)

            elif bid.startswith("btn-sel-"):
                self._select(bid[len("btn-sel-"):])

        def _select(self, key: str) -> None:
            if key == self._selected:
                return
            # Deselect old
            try:
                self.query_one(f"#card-{self._selected}").remove_class("-selected")
                old_btn = self.query_one(f"#btn-sel-{self._selected}", Button)
                old_btn.label = "Select"
                old_btn.variant = "default"
            except Exception:
                pass
            # Select new
            self._selected = key
            try:
                self.query_one(f"#card-{key}").add_class("-selected")
                new_btn = self.query_one(f"#btn-sel-{key}", Button)
                new_btn.label = "✓ Selected"
                new_btn.variant = "primary"
            except Exception:
                pass

        def on_key(self, event) -> None:
            if event.key == "escape":
                self.dismiss(None)

    class ConfirmScreen(ModalScreen):  # type: ignore[misc]
        """Generic two-option confirm modal."""

        def __init__(self, title: str, ok_label: str, ok_key: str, alt_label: str, alt_key: str) -> None:
            super().__init__()
            self._title     = title
            self._ok_label  = ok_label
            self._alt_label = alt_label
            self._ok_key    = ok_key
            self._alt_key   = alt_key

        def compose(self) -> ComposeResult:
            with Vertical(id="confirm-box"):
                yield Label(self._title)
                yield Button(self._ok_label,  id="cb-ok",  variant="primary")
                yield Button(self._alt_label, id="cb-alt")
                yield Button("Cancel",        id="cb-cancel", variant="error")

        def on_button_pressed(self, event: Button.Pressed) -> None:
            event.stop()  # prevent bubbling to XDJApp.on_button_pressed
            if   event.button.id == "cb-ok":     self.dismiss(self._ok_key)
            elif event.button.id == "cb-alt":    self.dismiss(self._alt_key)
            elif event.button.id == "cb-cancel": self.dismiss(None)

        def on_key(self, event) -> None:
            if event.key == "escape":
                self.dismiss(None)

    class SettingsScreen(ModalScreen):  # type: ignore[misc]
        """Full settings: SSH credentials + board selection."""

        DEFAULT_CSS = """
        SettingsScreen { align: center middle; }
        #settings-dialog {
            background: $panel;
            border: solid $primary;
            padding: 1 2;
            width: 60;
            height: auto;
        }
        #settings-title {
            width: 100%;
            text-align: center;
            text-style: bold;
            color: $primary;
            margin-bottom: 1;
        }
        .settings-section {
            color: $primary;
            text-style: bold;
            margin-top: 1;
        }
        .settings-row { height: 3; margin-bottom: 0; }
        .field-label { width: 12; color: $text-muted; padding-top: 1; }
        .field-input { width: 1fr; }
        #settings-board { width: 100%; margin-top: 1; margin-bottom: 0; }
        #settings-footer {
            width: 100%;
            align: right middle;
            height: 3;
            margin-top: 1;
        }
        #settings-footer Button { width: auto; min-width: 16; margin-left: 1; }
        """

        def __init__(self) -> None:
            super().__init__()
            from xdj_pi_dev.config import load_config
            cfg = load_config()
            self._init_user  = cfg.get("ssh_user", "")
            self._init_pass  = cfg.get("ssh_pass", "")
            self._init_board = cfg.get("board", "pico")

        def compose(self) -> ComposeResult:
            board_options = [(_BOARD_META[k][0], k) for k in _BOARD_META]
            with Vertical(id="settings-dialog"):
                yield Label("Settings", id="settings-title")
                yield Label("SSH CREDENTIALS", classes="settings-section")
                with Horizontal(classes="settings-row"):
                    yield Label("Username:", classes="field-label")
                    yield Input(
                        value=self._init_user,
                        placeholder="xdj100sx",
                        id="inp-user",
                        classes="field-input",
                    )
                with Horizontal(classes="settings-row"):
                    yield Label("Password:", classes="field-label")
                    yield Input(
                        value=self._init_pass,
                        placeholder="xdj100sx",
                        password=True,
                        id="inp-pass",
                        classes="field-input",
                    )
                yield Label("BOARD", classes="settings-section")
                yield Select(board_options, id="settings-board", value=self._init_board)
                with Horizontal(id="settings-footer"):
                    yield Button("Save & Close", id="btn-st-save", variant="success")
                    yield Button("Cancel",        id="btn-st-cancel")

        def on_button_pressed(self, event: Button.Pressed) -> None:
            event.stop()
            if event.button.id == "btn-st-save":
                from xdj_pi_dev.config import update_config
                user   = self.query_one("#inp-user",  Input).value.strip()
                passwd = self.query_one("#inp-pass",  Input).value.strip()
                bsel   = self.query_one("#settings-board", Select)
                board  = str(bsel.value) if bsel.value and bsel.value is not Select.BLANK else "pico"
                update_config(ssh_user=user or None, ssh_pass=passwd or None, board=board)
                self.dismiss(board)
            elif event.button.id == "btn-st-cancel":
                self.dismiss(None)

        def on_key(self, event) -> None:
            if event.key == "escape":
                self.dismiss(None)

    class AboutScreen(ModalScreen):  # type: ignore[misc]
        """Authors, credits, and legal notices."""

        DEFAULT_CSS = """
        AboutScreen { align: center middle; }
        #about-dialog {
            background: $panel;
            border: solid $primary;
            padding: 1 2;
            width: 72;
            height: auto;
            max-height: 44;
        }
        #about-title {
            width: 100%;
            text-align: center;
            text-style: bold;
            color: $primary;
            margin-bottom: 1;
        }
        #about-body {
            height: 30;
            overflow-y: auto;
        }
        #about-footer {
            width: 100%;
            align: center middle;
            height: 3;
            margin-top: 1;
        }
        """

        _ABOUT = _TOOL_ABOUT

        def compose(self) -> ComposeResult:
            with Vertical(id="about-dialog"):
                yield Static("XDJ-100SX Pi Developer Tool", id="about-title")
                with ScrollableContainer(id="about-body"):
                    yield Static(self._ABOUT)
                with Horizontal(id="about-footer"):
                    yield Button("Close", id="btn-about-close", variant="primary")

        def on_button_pressed(self, event: Button.Pressed) -> None:
            event.stop()
            if event.button.id == "btn-about-close":
                self.dismiss()

        def on_key(self, event) -> None:
            if event.key == "escape":
                self.dismiss()

    class HelpScreen(ModalScreen):  # type: ignore[misc]
        """First-connection guide — how to reach the Pi."""

        DEFAULT_CSS = """
        HelpScreen { align: center middle; }
        #help-dialog {
            background: $panel;
            border: solid $primary;
            padding: 1 2;
            width: 72;
            height: auto;
            max-height: 44;
        }
        #help-title {
            width: 100%;
            text-align: center;
            text-style: bold;
            color: $primary;
            margin-bottom: 1;
        }
        #help-body {
            height: 30;
            overflow-y: auto;
        }
        #help-footer {
            width: 100%;
            align: center middle;
            height: 3;
            margin-top: 1;
        }
        """

        _GUIDE = """\
━━━ OPTION 1 — XDJ100SX.local  [dim](any network, WiFi or LAN)[/] ━━━

Pi and your computer must be on the same network.

[bold]Pi side[/] — needs avahi-daemon (check it's running):
[dim]  sudo systemctl enable --now avahi-daemon[/]
[dim]  sudo apt install -y avahi-daemon    ← if not installed[/]

[bold]macOS[/] — Bonjour is built-in. Nothing to install.

[bold]Windows 10/11[/] — mDNS is built-in but Windows Firewall
  often blocks it. If XDJ100SX.local doesn't resolve:
  • Use the IP address (192.168.10.2) instead, or
  • Install [bold]Bonjour Print Services for Windows[/] (free, from Apple)

[bold]Linux[/] — install avahi-daemon on your machine too:
[dim]  sudo apt install avahi-daemon[/]


━━━ OPTION 2 — 192.168.10.2  [dim](direct Ethernet cable)[/] ━━━

No router needed. Faster and more stable for development.

[bold]PI SIDE — configure static IP[/] (skip if already done):
[dim]  sudo nmcli con mod eth0 \\[/]
[dim]    ipv4.method manual \\[/]
[dim]    ipv4.addresses 192.168.10.2/24 \\[/]
[dim]    ipv4.gateway "" ipv4.dns "" \\[/]
[dim]    connection.autoconnect yes[/]
[dim]  sudo nmcli con up eth0[/]

[bold]YOUR MACHINE — set a matching IP on the cable port:[/]

macOS  (once per reboot — check interface with: ifconfig | grep -B2 'status: active'):
[dim]  sudo ifconfig en0 alias 192.168.10.1 255.255.255.0[/]

Windows  (run as Administrator, once per reboot):
[dim]  netsh interface ip set address "Ethernet" static 192.168.10.1 255.255.255.0[/]
[dim]  ← replace "Ethernet" with your interface name (check: ipconfig /all)[/]

Linux:
[dim]  sudo ip addr add 192.168.10.1/24 dev eth0[/]

Or run [bold]--setup-pi-dhcp[/] once — Pi assigns IPs automatically,
no local config needed ever again.


━━━ OPTION 3 — Custom IP or hostname ━━━

Type any address in the top field and press Enter.
It gets added to the dropdown for quick switching.


━━━ IT'S NOT CONNECTING? ━━━

[bold]1. Enable SSH on the Pi[/]  (run on the Pi itself or via its keyboard):
[dim]  sudo systemctl enable ssh && sudo systemctl start ssh[/]

[bold]2. Allow password login[/]  (newer Pi OS blocks it by default):
[dim]  sudo nano /etc/ssh/sshd_config[/]
[dim]  → find or add:  PasswordAuthentication yes[/]
[dim]  sudo systemctl restart ssh[/]

[bold]3. Wrong password?[/]  Open Settings (⚙) → enter your credentials.

[bold]4. Full pre-flight check:[/]
[dim]  python3 xdj-pi-dev.py --check    ← macOS / Linux[/]
[dim]  python  xdj-pi-dev.py --check    ← Windows[/]
"""

        def compose(self) -> ComposeResult:
            with Vertical(id="help-dialog"):
                yield Label("First Connection Guide", id="help-title")
                with ScrollableContainer(id="help-body"):
                    yield Static(self._GUIDE)
                with Horizontal(id="help-footer"):
                    yield Button("Close", id="btn-help-close", variant="primary")

        def on_button_pressed(self, event: Button.Pressed) -> None:
            event.stop()
            self.dismiss(None)

        def on_key(self, event) -> None:
            if event.key == "escape":
                self.dismiss(None)

    class XDJApp(App):  # type: ignore[misc]
        TITLE = "XDJ Pi Dev"

        CSS = """
        Screen { layout: vertical; }

        #top-bar {
            height: 3;
            background: $panel;
            border-bottom: solid $primary-darken-2;
            padding: 0 1;
            align: left middle;
        }
        #unit-select { width: 34; margin-right: 1; }
        #host-input  { width: 30; margin-right: 1; }
        #status { width: 1fr; color: $text-muted; }

        Input {
            background: $panel-lighten-1;
            border: tall $panel-lighten-3;
            color: $text;
        }
        Input:focus { border: tall $primary; }

        #body { layout: horizontal; height: 1fr; }

        #sidebar {
            width: 20;
            background: $panel;
            border-right: solid $primary-darken-2;
            padding: 1 1;
            overflow-y: auto;
        }

        /* Section headers */
        .sec {
            color: $primary;
            text-style: bold;
            margin-top: 1;
            margin-bottom: 0;
            padding: 0 0;
        }
        .sec-first { margin-top: 0; }

        /* All sidebar buttons */
        Button {
            width: 100%;
            height: 1;
            min-height: 1;
            border: none;
            padding: 0 1;
            background: $panel-lighten-1;
            color: $text;
            margin-bottom: 0;
        }
        Button:hover          { background: $primary-darken-1; color: $text; }
        Button:focus          { border: none; }
        Button.-primary       { background: $primary;          color: $text; }
        Button.-warning       { background: $warning;          color: $text-muted; }
        Button.-active-watch  { background: $warning 80%;      color: $text; }

        /* Main log area */
        #main { padding: 0 1; height: 1fr; }
        #log  { border: solid $primary-darken-3; height: 1fr; }

        /* SSH command bar */
        #ssh-bar {
            height: 3;
            padding: 0 0;
            background: $panel;
            border-top: solid $primary-darken-2;
        }
        #cmd-input { width: 1fr; border: none; }

        /* Bottom log-control strip */
        #log-bar {
            height: 1;
            background: $panel;
            border-top: solid $primary-darken-2;
            padding: 0 1;
            align: left middle;
        }
        #log-bar Button {
            width: auto;
            min-width: 12;
            margin-right: 1;
            background: $panel-lighten-2;
        }
        #log-bar Button:hover { background: $primary-darken-1; }

        /* Confirm dialog modal */
        ConfirmScreen, .modal {
            align: center middle;
        }
        #confirm-box {
            background: $panel;
            border: solid $primary;
            padding: 1 2;
            width: 44;
            height: auto;
        }
        #confirm-box Label {
            width: 100%;
            margin-bottom: 1;
            text-style: bold;
        }
        #confirm-box Button {
            width: 100%;
            margin-bottom: 0;
        }
        """

        BINDINGS = [
            Binding("x",       "quit",        "Quit"),
            Binding("p",       "push",        "Push skin"),
            Binding("s",       "screenshot",  "Screenshot"),
            Binding("r",       "restart",     "Restart"),
            Binding("w",       "watch",       "Watch"),
            Binding("d",       "discover",    "Discover"),
            Binding("ctrl+c",  "copy_log",    "Copy log"),
            Binding("ctrl+y",  "copy_tail",   "Copy tail"),
            Binding("l",       "clear_log",   "Clear log"),
        ]

        def __init__(self, host: str | None = None) -> None:
            super().__init__()
            self._host = host
            self._known_hosts: list[str] = [host] if host else list(_DEFAULT_HOSTS)
            self._watching = False
            self._watch_stop = threading.Event()
            self._midi_mon = False
            self._midi_mon_stop = threading.Event()
            self._signal_an = False
            self._signal_an_stop = threading.Event()
            # Prevents on_select_changed from firing a reconnect during programmatic updates
            self._unit_switching = False
            # Prevents concurrent connections (one at a time)
            self._connect_lock = threading.Lock()
            # Prevents concurrent SSH operations (push, screenshot, flash, etc.)
            self._op_lock = threading.Lock()
            # Keeps a plain-text copy of every log line for clipboard export
            self._log_lines: list[str] = []

        @staticmethod
        def _select_labels(hosts: list[str]) -> list[tuple[str, str]]:
            _WELL_KNOWN = {
                "XDJ100SX.local": "XDJ100SX.local  (mDNS — any network)",
                "192.168.10.2":   "192.168.10.2  (direct cable)",
            }
            return [(_WELL_KNOWN.get(h, h), h) for h in hosts]

        def compose(self) -> ComposeResult:
            yield Header(show_clock=True)
            with Horizontal(id="top-bar"):
                yield Select(
                    self._select_labels(self._known_hosts),
                    id="unit-select",
                    prompt="Select unit…",
                    # value is set in on_mount after _unit_switching=True to avoid a
                    # spurious on_select_changed that would trigger a second connect
                )
                yield Input(placeholder="or type IP / hostname…", id="host-input")
                yield Static("Connecting…", id="status")
            with Horizontal(id="body"):
                with Vertical(id="sidebar"):
                    yield Button("⚙ Settings",       id="btn-settings", variant="warning")
                    yield Button("? Connect Help",   id="btn-help")
                    yield Button("ℹ About",           id="btn-about")
                    yield Label("DEPLOY",           classes="sec sec-first")
                    yield Button("Push Skin",        id="btn-push",       variant="primary")
                    yield Button("Pull Skin",        id="btn-pull")
                    yield Button("Push MIDI",        id="btn-push-midi")
                    yield Button("Pull MIDI",        id="btn-pull-midi")
                    yield Button("Screenshot",       id="btn-screenshot")
                    yield Button("Restart",          id="btn-restart",    variant="warning")
                    yield Label("LIVE",              classes="sec")
                    yield Button("Watch ▶",          id="btn-watch")
                    yield Button("MIDI Mon ▶",       id="btn-midi-mon")
                    # PICO-specific — always mounted, visibility set by _apply_board_visibility
                    yield Button("Signal An ▶",      id="btn-signal-an")
                    yield Label("PICO",              classes="sec", id="lbl-pico")
                    yield Button("Bootloader",       id="btn-bootloader")
                    yield Button("Flash UF2",        id="btn-flash")
                    yield Label("TOOLS",             classes="sec")
                    yield Button("Discover",         id="btn-discover")
                    yield Button("Check",            id="btn-check")
                    yield Button("Backup Pi",        id="btn-backup")
                    yield Button("Verify Bak",       id="btn-verify-backup")
                    yield Button("SSH Keys",         id="btn-ssh-keys")
                    yield Button("DHCP",             id="btn-dhcp")
                with Vertical(id="main"):
                    yield RichLog(id="log", highlight=True, markup=True, max_lines=500)
                    with Horizontal(id="ssh-bar"):
                        yield Input(placeholder="$ command on Pi…", id="cmd-input")
            with Horizontal(id="log-bar"):
                yield Button("Copy Log",  id="btn-copy-log")
                yield Button("Copy Tail", id="btn-copy-tail")
                yield Button("Clear Log", id="btn-clear-log")
            yield Footer()

        def on_mount(self) -> None:
            _term._tui_log_fn = self._log_from_thread
            self._unit_switching = True
            initial = self._host or _DEFAULT_HOSTS[0]
            self.query_one("#unit-select", Select).value = initial
            self._apply_board_visibility()
            from xdj_pi_dev.config import load_config
            if "board" not in load_config():
                # First run — show board selector before connecting
                self.push_screen(
                    BoardSelectScreen(current="pico"),
                    lambda choice: self._after_first_board(choice, initial),
                )
            else:
                self._do_connect(initial)

        def _after_first_board(self, choice: str | None, initial: str) -> None:
            # ESC on first-run = accept default (pico). Don't leave config empty
            # or the selector would show again on every launch.
            from xdj_pi_dev.config import update_config
            update_config(board=choice or "pico")
            self._apply_board_visibility()
            self._do_connect(initial)

        # ── Thread-safe log ───────────────────────────────────────────────────

        def _log_from_thread(self, level: str, msg: str) -> None:
            self.call_from_thread(self._log, level, msg)

        def _log(self, level: str, msg: str) -> None:
            icons = {
                "ok":   "[green]✓[/]",
                "warn": "[yellow]⚠[/]",
                "fail": "[red]✗[/]",
                "info": "[dim]·[/]",
                "head": "[bold cyan]╌[/]",
            }
            self._log_lines.append(f"{level.upper()}: {msg}")
            self.query_one("#log", RichLog).write(f"{icons.get(level, '·')} {msg}")

        def _set_status(self, text: str) -> None:
            self.query_one("#status", Static).update(text)

        def _clear_switching(self) -> None:
            self._unit_switching = False

        def _op_start(self) -> bool:
            """Try to acquire the operation lock. Returns False if not ready or busy."""
            if pi is None:
                self._log_from_thread("warn", MSG["not_connected"])
                return False
            if not self._op_lock.acquire(blocking=False):
                self._log_from_thread("warn", MSG["busy"])
                return False
            return True

        def _op_end(self) -> None:
            try:
                self._op_lock.release()
            except RuntimeError:
                pass

        # ── Unit switcher ─────────────────────────────────────────────────────

        def on_select_changed(self, event: Select.Changed) -> None:
            if event.select.id != "unit-select" or self._unit_switching:
                return
            if event.value and event.value is not Select.BLANK:
                self._unit_switching = True
                self._do_connect(str(event.value))

        def on_input_submitted(self, event: Input.Submitted) -> None:
            iid = event.input.id
            if iid == "host-input":
                host = event.value.strip()
                if host:
                    event.input.value = ""
                    self._connect_to_custom(host)
            elif iid == "cmd-input":
                cmd = event.value.strip()
                if cmd:
                    event.input.value = ""
                    self._run_ssh_cmd(cmd)

        def _connect_to_custom(self, host: str) -> None:
            if host not in self._known_hosts:
                self._known_hosts.insert(0, host)
            sel = self.query_one("#unit-select", Select)
            self._unit_switching = True
            sel.set_options(self._select_labels(self._known_hosts))
            sel.value = host
            self.call_later(self._clear_switching)
            self._do_connect(host)

        def _do_connect(self, host: str) -> None:
            if not self._connect_lock.acquire(blocking=False):
                self._log_from_thread("warn", MSG["already_connecting"])
                return
            self._connect_worker(host)

        @_twork(thread=True)
        def _connect_worker(self, host: str) -> None:
            self.call_from_thread(self._set_status, f"Connecting to {host}…")
            try:
                resolved = init_client(host)
                bits = []
                r = pi.exec("pgrep -c mixxx || true")
                if r["stdout"].strip() not in ("", "0"):
                    bits.append("Mixxx ◉")
                r2 = pi.exec("ls /media/ 2>/dev/null")
                if r2["stdout"].strip():
                    bits.append(f"USB:{r2['stdout'].strip()}")
                r3 = pi.exec("[ -e /dev/ttyACM0 ] && echo yes || true")
                if "yes" in r3["stdout"]:
                    bits.append("Pico ◉")
                summary = "  [dim]│[/]  ".join(bits) if bits else "ready"
                self.call_from_thread(
                    self._set_status, f"[green]◉[/] {resolved}  [dim]│[/]  {summary}"
                )
                self._log_from_thread("ok", f"Connected → {resolved}")
            except Exception as e:
                self.call_from_thread(self._set_status, f"[red]✗[/] {host} — {e}")
                self._log_from_thread("fail", f"{host}: {e}")
            finally:
                self._connect_lock.release()
                # Re-enable on_select_changed after connect (deferred one tick)
                self.call_from_thread(lambda: self.call_later(self._clear_switching))

        @_twork(thread=True)
        def action_discover(self) -> None:
            self._log_from_thread("info", MSG["discovering"])
            try:
                units = discover_units(
                    extra_hosts=[self._host] if self._host else None
                )
                if not units:
                    self._log_from_thread("warn", MSG["no_units_found"])
                    return
                for host, hostname in units:
                    self._log_from_thread("ok", f"{hostname}  ({host})")
                options = [(f"{hostname}  ({host})", host) for host, hostname in units]
                self.call_from_thread(self._apply_discovered_units, options)
            except Exception as e:
                self._log_from_thread("fail", str(e))

        def _apply_discovered_units(self, options: list) -> None:
            sel = self.query_one("#unit-select", Select)
            current = sel.value
            for _, h in options:
                if h not in self._known_hosts:
                    self._known_hosts.append(h)
            self._unit_switching = True
            sel.set_options(options)
            values = [v for _, v in options]
            sel.value = current if current in values else values[0]
            self.call_later(self._clear_switching)

        # ── Button dispatch ───────────────────────────────────────────────────

        def on_button_pressed(self, event: Button.Pressed) -> None:
            {
                "btn-push":          self._ask_push,
                "btn-pull":          self._ask_pull,
                "btn-push-midi":     self._ask_push_midi,
                "btn-pull-midi":     self._ask_pull_midi,
                "btn-screenshot":    self.action_screenshot,
                "btn-restart":       self.action_restart,
                "btn-watch":         self.action_watch,
                "btn-midi-mon":      self.action_midi_mon,
                "btn-signal-an":     self.action_signal_an,
                "btn-bootloader":    self._do_bootloader,
                "btn-flash":         self._do_flash,
                "btn-discover":      self.action_discover,
                "btn-check":         self._do_check,
                "btn-backup":        self._do_backup,
                "btn-verify-backup": self._do_verify_backup,
                "btn-ssh-keys":      self._do_ssh_keys,
                "btn-dhcp":          self._do_dhcp,
                "btn-help":          self._open_help,
                "btn-about":         self._open_about,
                "btn-settings":      self._open_settings,
                "btn-copy-log":      self.action_copy_log,
                "btn-copy-tail":     self.action_copy_tail,
                "btn-clear-log":     self.action_clear_log,
            }.get(event.button.id, lambda: None)()

        # ── Confirm-modal helpers ─────────────────────────────────────────────

        def _ask_push(self) -> None:
            self.push_screen(
                ConfirmScreen("Push skin to Pi — backup remote first?",
                              "Push",  "push",
                              "Backup remote then push", "backup"),
                self._start_push,
            )

        def _start_push(self, choice: str | None) -> None:
            if choice is None: return
            self.action_push(backup_remote=(choice == "backup"))

        def _ask_pull(self) -> None:
            self.push_screen(
                ConfirmScreen("Pull skin from Pi — what to do with local files?",
                              "Replace", "replace",
                              "Backup then replace", "backup"),
                self._start_pull,
            )

        def _start_pull(self, choice: str | None) -> None:
            if choice is None: return
            self._do_pull(backup=(choice == "backup"))

        def _ask_push_midi(self) -> None:
            self.push_screen(
                ConfirmScreen("Push MIDI to Pi — backup remote first?",
                              "Push",  "push",
                              "Backup remote then push", "backup"),
                self._start_push_midi,
            )

        def _start_push_midi(self, choice: str | None) -> None:
            if choice is None: return
            self._do_push_midi(backup_remote=(choice == "backup"))

        def _ask_pull_midi(self) -> None:
            self.push_screen(
                ConfirmScreen("Pull MIDI from Pi — what to do with local files?",
                              "Replace", "replace",
                              "Backup then replace", "backup"),
                self._start_pull_midi,
            )

        def _start_pull_midi(self, choice: str | None) -> None:
            if choice is None: return
            self._do_pull_midi(backup=(choice == "backup"))

        # ── Actions ───────────────────────────────────────────────────────────

        @_twork(thread=True)
        def action_push(self, backup_remote: bool = False) -> None:
            if not self._op_start(): return
            try:
                label = MSG["pushing_skin_backup"] if backup_remote else MSG["pushing_skin"]
                self._log_from_thread("head", label)
                pushed = push_skin(backup_remote=backup_remote)
                for p in pushed:
                    self._log_from_thread("ok", p)
                self._log_from_thread("ok", MSG["pushed_skin"].format(n=len(pushed)))
            except Exception as e:
                self._log_from_thread("fail", str(e))
            finally:
                self._op_end()

        @_twork(thread=True)
        def _do_pull(self, backup: bool = False) -> None:
            if not self._op_start(): return
            try:
                label = MSG["pulling_skin_backup"] if backup else MSG["pulling_skin"]
                self._log_from_thread("head", label)
                pulled = pull_skin(backup=backup)
                for p in pulled:
                    self._log_from_thread("ok", p)
                self._log_from_thread("ok", MSG["pulled_skin"].format(n=len(pulled)))
            except Exception as e:
                self._log_from_thread("fail", str(e))
            finally:
                self._op_end()

        @_twork(thread=True)
        def action_screenshot(self) -> None:
            if not self._op_start(): return
            try:
                self._log_from_thread("info", MSG["screenshotting"])
                data, err = take_screenshot()
                if err:
                    self._log_from_thread("fail", err)
                else:
                    out = tmp_path("xdj_screenshot.png")
                    out.write_bytes(data)
                    self._log_from_thread("ok", f"Saved → {out}")
                    open_image(out)
            except Exception as e:
                self._log_from_thread("fail", str(e))
            finally:
                self._op_end()

        @_twork(thread=True)
        def action_restart(self) -> None:
            if not self._op_start(): return
            try:
                self._log_from_thread("info", MSG["restarting_mixxx"])
                self._log_from_thread("ok", restart_mixxx())
            except Exception as e:
                self._log_from_thread("fail", str(e))
            finally:
                self._op_end()

        def action_watch(self) -> None:
            btn = self.query_one("#btn-watch", Button)
            if self._watching:
                self._watch_stop.set()
                self._watching = False
                btn.label = "Watch ▶"
                btn.remove_class("-active-watch")
            else:
                self._watch_stop.clear()
                self._watching = True
                btn.label = "Watch ■"
                btn.add_class("-active-watch")
                self._do_watch()

        @_twork(thread=True)
        def _do_watch(self) -> None:
            self._log_from_thread("head", MSG["watch_started"])
            from xdj_pi_dev.watch import _REPO_SKIN as _ws
            self._log_from_thread("info", f"Folder: {_ws}")
            try:
                def _watch_shot(_paths: list[str]) -> None:
                    data, err = take_screenshot()
                    if err:
                        self._log_from_thread("warn", f"Screenshot: {err}")
                        return
                    out = tmp_path("xdj_watch_screen.png")
                    out.write_bytes(data)
                    open_image(out)
                    self._log_from_thread("info", f"Screenshot → {out}")

                _watch_loop(pi, self._watch_stop, self._log_from_thread, screenshot_fn=_watch_shot)
            except Exception as e:
                self._log_from_thread("fail", str(e))
            self.call_from_thread(self._watch_done)

        def _watch_done(self) -> None:
            self._watching = False
            btn = self.query_one("#btn-watch", Button)
            btn.label = "Watch ▶"
            btn.remove_class("-active-watch")
            self._log("info", MSG["watch_stopped"])

        def action_midi_mon(self) -> None:
            btn = self.query_one("#btn-midi-mon", Button)
            if self._midi_mon:
                self._midi_mon_stop.set()
                self._midi_mon = False
                btn.label = "MIDI Mon ▶"
                btn.remove_class("-active-watch")
            else:
                self._midi_mon_stop.clear()
                self._midi_mon = True
                btn.label = "MIDI Mon ■"
                btn.add_class("-active-watch")
                self._do_midi_mon()

        @_twork(thread=True)
        def _do_midi_mon(self) -> None:
            try:
                midi_monitor(pi, self._midi_mon_stop, self._log_from_thread)
            except Exception as e:
                self._log_from_thread("fail", str(e))
            self.call_from_thread(self._midi_mon_done)

        def _midi_mon_done(self) -> None:
            self._midi_mon = False
            btn = self.query_one("#btn-midi-mon", Button)
            btn.label = "MIDI Mon ▶"
            btn.remove_class("-active-watch")
            self._log("info", "MIDI monitor stopped")

        def action_signal_an(self) -> None:
            import socket as _sock, webbrowser
            if self._signal_an:
                self._signal_an_stop.set()
                self._signal_an = False
                btn = self.query_one("#btn-signal-an", Button)
                btn.label = "Signal An ▶"
                btn.remove_class("-active-watch")
                return
            with _sock.socket() as s:
                s.bind(("", 0))
                port = s.getsockname()[1]
            self._signal_an_stop = threading.Event()
            self._signal_an = True
            btn = self.query_one("#btn-signal-an", Button)
            btn.label = "Signal An ■"
            btn.add_class("-active-watch")
            url = f"http://localhost:{port}/"
            self._log("info", f"Signal Analyzer → {url}")
            threading.Thread(
                target=run_signal_analyzer_web,
                args=(pi, self._signal_an_stop, port),
                daemon=True,
            ).start()
            self.call_later(lambda: webbrowser.open(url))

        @_twork(thread=True)
        def _do_push_midi(self, backup_remote: bool = False) -> None:
            if not self._op_start(): return
            try:
                label = MSG["pushing_midi_backup"] if backup_remote else MSG["pushing_midi"]
                self._log_from_thread("head", label)
                pushed = push_midi(backup_remote=backup_remote)
                for p in pushed:
                    self._log_from_thread("ok", p)
                self._log_from_thread("ok", MSG["midi_reload"])
            except Exception as e:
                self._log_from_thread("fail", str(e))
            finally:
                self._op_end()

        @_twork(thread=True)
        def _do_pull_midi(self, backup: bool = False) -> None:
            if not self._op_start(): return
            try:
                label = MSG["pulling_midi_backup"] if backup else MSG["pulling_midi"]
                self._log_from_thread("head", label)
                pulled = pull_midi(backup=backup)
                for p in pulled:
                    self._log_from_thread("ok", p)
                self._log_from_thread("ok", MSG["pulled_midi"].format(n=len(pulled)))
            except Exception as e:
                self._log_from_thread("fail", str(e))
            finally:
                self._op_end()

        @_twork(thread=True)
        def _do_bootloader(self) -> None:
            # MIDI monitor holds the Pi ALSA port — release it before sending the bootloader signal
            if self._midi_mon:
                self._midi_mon_stop.set()
                self._log_from_thread("info", "Stopping MIDI monitor (needed for bootloader)…")
                time.sleep(0.8)
                self.call_from_thread(self._midi_mon_done)
            if not self._op_start(): return
            try:
                self._log_from_thread("head", MSG["pico_boot_starting"])
                msg = pico_bootloader(pi)
                level = "ok" if "update mode" in msg else ("warn" if "signal sent" in msg else "fail")
                self._log_from_thread(level, msg)
            except Exception as e:
                self._log_from_thread("fail", str(e) or f"{type(e).__name__}")
            finally:
                self._op_end()

        @_twork(thread=True)
        def _do_flash(self) -> None:
            if not self._op_start(): return
            try:
                from xdj_pi_dev.config import get_firmware_dir
                try:
                    fw_dir = get_firmware_dir()
                except RuntimeError as e:
                    self._log_from_thread("warn", str(e))
                    return
                candidates = sorted(
                    fw_dir.glob("*.uf2"),
                    key=lambda p: p.stat().st_mtime, reverse=True,
                )
                if not candidates:
                    self._log_from_thread("fail", MSG["flash_fail_nofile"])
                    return
                uf2 = candidates[0]
                self._log_from_thread("head", MSG["flashing"])
                msg = pico_flash(pi, str(uf2))
                is_fail = any(w in msg.lower() for w in (
                    "couldn't", "failed", "not found", "cp_failed", "error", "unexpected",
                ))
                self._log_from_thread("fail" if is_fail else "ok", msg or "No output from flash command")
            except Exception as e:
                self._log_from_thread("fail", repr(e) if not str(e) else str(e))
            finally:
                self._op_end()

        @_twork(thread=True)
        def _do_ssh_keys(self) -> None:
            if not self._op_start(): return
            try:
                self._log_from_thread("head", MSG["ssh_keys_starting"])
                setup_ssh_keys(pi)
            except Exception as e:
                self._log_from_thread("fail", str(e))
            finally:
                self._op_end()

        @_twork(thread=True)
        def _do_dhcp(self) -> None:
            if not self._op_start(): return
            try:
                self._log_from_thread("head", MSG["dhcp_starting"])
                setup_pi_dhcp(pi)
            except Exception as e:
                self._log_from_thread("fail", str(e))
            finally:
                self._op_end()

        @_twork(thread=True)
        def _run_ssh_cmd(self, cmd: str) -> None:
            if pi is None:
                self._log_from_thread("warn", MSG["not_connected"])
                return
            self._log_from_thread("info", f"$ {cmd}")
            try:
                r = pi.exec(cmd, timeout=60)
                for line in (r["stdout"] or "").splitlines():
                    self._log_from_thread("info", line)
                for line in (r["stderr"] or "").splitlines():
                    self._log_from_thread("warn", line)
                if r["rc"] != 0:
                    self._log_from_thread("info", f"[exit {r['rc']}]")
            except Exception as e:
                self._log_from_thread("fail", str(e))

        def _apply_board_visibility(self) -> None:
            """Show/hide PICO-specific sidebar items based on current board config."""
            pico = is_pico_board()
            for wid in ("btn-signal-an", "lbl-pico", "btn-bootloader", "btn-flash"):
                try:
                    self.query_one(f"#{wid}").display = pico
                except Exception:
                    pass

        def _open_help(self) -> None:
            self.push_screen(HelpScreen())

        def _open_about(self) -> None:
            self.push_screen(AboutScreen())

        def _open_settings(self) -> None:
            self.push_screen(SettingsScreen(), self._on_settings_saved)

        def _on_settings_saved(self, chosen: str | None) -> None:
            if chosen is None:
                return
            self._log("ok", f"Settings saved — board: {_BOARD_META.get(chosen, (chosen,))[0]}")
            self._apply_board_visibility()

        def action_copy_log(self) -> None:
            text = "\n".join(self._log_lines)
            try:
                if sys.platform == "darwin":
                    subprocess.run(["pbcopy"], input=text.encode(), check=True)
                elif shutil.which("xclip"):
                    subprocess.run(["xclip", "-selection", "clipboard"],
                                   input=text.encode(), check=True)
                elif shutil.which("xsel"):
                    subprocess.run(["xsel", "--clipboard", "--input"],
                                   input=text.encode(), check=True)
                else:
                    self._log("warn", "No clipboard tool found (pbcopy/xclip/xsel)")
                    return
                self._log("ok", f"Log copied to clipboard ({len(self._log_lines)} lines)")
            except Exception as e:
                self._log("fail", f"Copy failed: {e}")

        def action_clear_log(self) -> None:
            self._log_lines.clear()
            self.query_one("#log", RichLog).clear()
            self.query_one("#log", RichLog).write("[dim]── log cleared ──[/]")

        def action_copy_tail(self) -> None:
            """Copy last 30 log lines to clipboard — useful for grabbing recent output."""
            tail = self._log_lines[-30:]
            text = "\n".join(tail)
            try:
                if sys.platform == "darwin":
                    subprocess.run(["pbcopy"], input=text.encode(), check=True)
                elif shutil.which("xclip"):
                    subprocess.run(["xclip", "-selection", "clipboard"],
                                   input=text.encode(), check=True)
                elif shutil.which("xsel"):
                    subprocess.run(["xsel", "--clipboard", "--input"],
                                   input=text.encode(), check=True)
                else:
                    self._log("warn", "No clipboard tool found (pbcopy/xclip/xsel)")
                    return
                self._log("ok", f"Last {len(tail)} lines copied to clipboard")
            except Exception as e:
                self._log("fail", f"Copy failed: {e}")

        @_twork(thread=True)
        def _do_check(self) -> None:
            if not self._op_start(): return
            try:
                self._log_from_thread("head", MSG["preflight_start"])
                run_check(self._host)
            except Exception as e:
                self._log_from_thread("fail", str(e))
            finally:
                self._op_end()

        @_twork(thread=True)
        def _do_backup(self) -> None:
            if not self._op_start(): return
            try:
                self._log_from_thread("head", MSG["backup_starting"])
                self._log_from_thread("warn", MSG["backup_wait"])
                out_path = backup_pi_image(pi, log_fn=self._log_from_thread)
                if out_path:
                    self._log_from_thread("ok", f"Backup saved → {out_path}")
            except Exception as e:
                self._log_from_thread("fail", str(e))
            finally:
                self._op_end()

        @_twork(thread=True)
        def _do_verify_backup(self) -> None:
            if not self._op_start(): return
            # Ask user to provide the file path via the log (TUI can't open file dialogs)
            # Find the most recent backup in the repo directory
            import glob as _glob
            pattern = str(Path(__file__).parent.parent / "xdj-pi-backup-*.tar")
            matches = sorted(_glob.glob(pattern))
            if not matches:
                self._log_from_thread("warn", "No xdj-pi-backup-*.tar found in repo root")
                self._log_from_thread("info", "Run:  python3 tools/xdj-pi-dev.py --verify-backup <file.tar>")
                self._op_end()
                return
            latest = matches[-1]
            try:
                self._log_from_thread("head", f"Verifying {Path(latest).name}…")
                verify_backup(pi, latest)
                self._log_from_thread("ok", "Verification complete — check terminal for details")
            except Exception as e:
                self._log_from_thread("fail", str(e))
            finally:
                self._op_end()


def main() -> None:
    global PI_USER, PI_PASS, pi

    ap = argparse.ArgumentParser(
        description="XDJ Pi developer tool — CLI + MCP server for Claude Code",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # Connection
    conn = ap.add_argument_group("connection")
    conn.add_argument("--host",     metavar="HOST",
                      help="Pi IP or hostname (overrides XDJ_HOST env)")
    conn.add_argument("--user",     metavar="USER",    default=PI_USER,
                      help=f"SSH username (default: {PI_USER})")
    conn.add_argument("--password", metavar="PASS",    default=PI_PASS,
                      help="SSH password (default: built-in or XDJ_PASS env)")

    # Setup
    setup = ap.add_argument_group("setup (run these first)")
    setup.add_argument("--check",          action="store_true",
                       help="Pre-flight: check deps, connection, Mixxx, audio")
    setup.add_argument("--discover",       action="store_true",
                       help="Scan network for Pi units")
    setup.add_argument("--setup-pi-dhcp", action="store_true",
                       help="Configure Pi as DHCP server — no manual IP config ever again")
    setup.add_argument("--setup-ssh-keys", action="store_true",
                       help="Generate key pair and install on Pi (passwordless auth)")
    setup.add_argument("--restore-ssh",   action="store_true",
                       help="Print SSH recovery guide (no connection required)")
    setup.add_argument("--set-hostname",  metavar="NAME",
                       help="Rename Pi (e.g. xdj-unit2 for multi-unit setups)")
    setup.add_argument("--backup-image",  metavar="FILE", nargs="?", const="",
                       help="Backup Pi SD card to a .tar archive (used blocks only, default: cwd)")
    setup.add_argument("--verify-backup", metavar="FILE",
                       help="Verify a backup .tar: test gzip integrity + compare manifest against live Pi")

    # Skin dev
    skin = ap.add_argument_group("skin development")
    skin.add_argument("--status",       action="store_true",  help="Pi + Mixxx live status")
    skin.add_argument("--screenshot",   action="store_true",  help="Capture Pi display")
    skin.add_argument("--panel",        metavar="PANEL",
                      help="Panel to show (hotcue/hc, beatloop/bl, keyshift/ks, beatjump/bj, stems/st)")
    skin.add_argument("--restart",      action="store_true",  help="Restart Mixxx")
    skin.add_argument("--push",         metavar="GLOB", nargs="?", const="*",
                      help="Push skin files to Pi (default: all)")
    skin.add_argument("--push-midi",    action="store_true",
                      help="Push MIDI mapping files (docs/midi/) to Pi controllers dir")
    skin.add_argument("--pull-midi",    action="store_true",
                      help="Pull MIDI mapping files from Pi to local midi dir")
    skin.add_argument("--midi-mon",     action="store_true",
                      help="Stream live MIDI messages from controller (Ctrl-C to stop)")
    skin.add_argument("--pull",         action="store_true",  help="Pull skin from Pi to repo")
    skin.add_argument("--watch",        action="store_true",
                      help="Watch skin dir, auto-push + screenshot on change")
    skin.add_argument("--full-restart", action="store_true",
                      help="Full Mixxx restart in watch mode (default: try Ctrl+F5)")

    # Pico / firmware
    pico = ap.add_argument_group("firmware")
    pico.add_argument("--setup-pico-cli",  action="store_true",
                      help="Install arduino-cli + RP2040 toolchain on Pi (one-time, needs Pi internet)")
    pico.add_argument("--pico-compile",    action="store_true",
                      help="Compile firmware (local arduino-cli first, falls back to Pi)")
    pico.add_argument("--pico-bootloader", action="store_true",
                      help="Trigger UF2 bootloader on Pico via MIDI (or combined with --pico-compile to compile+flash)")
    pico.add_argument("--pico-flash",      metavar="FILE",
                      help="Flash a local .uf2/.hex file to Pico via Pi")
    pico.add_argument("--board",           metavar="BOARD", default=DEFAULT_BOARD,
                      help=(
                          f"Board profile or raw FQBN (default: {DEFAULT_BOARD}). "
                          f"Profiles: {', '.join(BOARD_PROFILES)}"
                      ))
    pico.add_argument("--analyze",         action="store_true",
                      help="Live GPIO signal analyzer — curses dashboard reading Pico Core 1 via /dev/ttyACM0")

    # Other
    ap.add_argument("--cmd",   metavar="CMD", help="Run arbitrary SSH command on Pi")
    ap.add_argument("--ui",   action="store_true", help="Open interactive TUI (requires: pip install textual)")
    ap.add_argument("--about", action="store_true", help="Show authors and credits")

    args = ap.parse_args()

    # Apply CLI credential overrides
    PI_USER = args.user
    PI_PASS = args.password

    # TUI — launches before any connection (app handles it internally)
    if args.about:
        print(_TOOL_ABOUT)
        return

    if args.ui:
        if not _TEXTUAL:
            print("textual not installed. Run:  pip install textual")
            sys.exit(1)
        XDJApp(host=args.host).run()
        return

    # Commands that need no Pi connection
    if args.restore_ssh:
        restore_ssh()
        return

    if args.discover:
        units = discover_units(extra_hosts=[args.host] if args.host else None)
        if units:
            print(f"\nFound {len(units)} Pi unit(s):\n")
            for host, hostname in units:
                print(f"  {host:<20}  hostname: {hostname}")
            print(f"\nConnect:  python3 xdj-pi-dev.py --host {units[0][0]} --status")
        else:
            print("No Pi units found.")
        return

    # Pre-flight check (resolves connection internally)
    if args.check:
        run_check(args.host)
        return

    # All remaining commands need a live Pi connection
    try:
        host = init_client(args.host)
    except ConnectionError as e:
        print(f"\n{e}")
        sys.exit(1)

    if args.status:
        cli_status()

    elif args.setup_pi_dhcp:
        setup_pi_dhcp(pi)

    elif args.setup_ssh_keys:
        setup_ssh_keys(pi)

    elif args.set_hostname:
        set_hostname(pi, args.set_hostname)

    elif args.backup_image is not None:
        backup_pi_image(pi, args.backup_image or None)

    elif args.verify_backup:
        verify_backup(pi, args.verify_backup)

    elif args.screenshot:
        data, err = take_screenshot(panel=args.panel)
        if err:
            print(f"Failed: {err}")
        else:
            out = tmp_path("xdj_screenshot.png")
            out.write_bytes(data)
            print(f"Saved: {out}")
            open_image(out)

    elif args.restart:
        print(restart_mixxx(panel=args.panel))

    elif args.push is not None:
        pushed = push_skin(args.push)
        for p in pushed:
            print(f"  ✓ {p}")
        print(f"Done: {len(pushed)} file(s)")

    elif args.push_midi:
        pushed = push_midi()
        for p in pushed:
            ok(p)
        print(f"\n  Pushed {len(pushed)} MIDI file(s) → {PI_MIDI_DIR}")
        print(f"  {_C.DIM}In Mixxx: Preferences → Controllers → disable + re-enable mapping{_C.RESET}")

    elif args.pull_midi:
        pulled = pull_midi()
        for p in pulled:
            print(f"  ✓ {p}")
        print(f"Done: {len(pulled)} MIDI file(s)")

    elif args.midi_mon:
        stop = threading.Event()
        try:
            midi_monitor(pi, stop, lambda t, m: print(f"[{t}] {m}"))
        except KeyboardInterrupt:
            stop.set()

    elif args.pull:
        pulled = pull_skin()
        for p in pulled:
            print(f"  ✓ {p}")
        print(f"Done: {len(pulled)} file(s)")

    elif args.watch:
        watch_mode(pi, panel=args.panel, restart=args.full_restart)

    elif args.setup_pico_cli:
        setup_pico_cli(pi)

    elif args.pico_compile:
        pico_compile(pi, flash=args.pico_bootloader, board=args.board)

    elif args.pico_bootloader:
        print(pico_bootloader(pi))

    elif args.pico_flash:
        print(pico_flash(pi, args.pico_flash))

    elif args.analyze:
        run_signal_analyzer_cli(pi)

    elif args.cmd:
        r = pi.exec(args.cmd)
        if r["stdout"]: sys.stdout.write(r["stdout"])
        if r["stderr"]: sys.stderr.write(r["stderr"])
        sys.exit(r["rc"])

    else:
        # No CLI flag → MCP server mode
        env = os.environ.get("XDJ_HOST")
        candidates = [args.host] if args.host else ([env] if env else _DEFAULT_HOSTS)
        resolved = resolve_host(candidates)
        if resolved:
            pi = PiClient(resolved, PI_USER, PI_PASS)
        run_mcp_server()


if __name__ == "__main__":
    main()
