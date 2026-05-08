from __future__ import annotations

"""
Pico firmware tools: bootloader, flash, compile, and CLI setup.

Extracted from xdj-pi-dev.py (lines 577-741 and 853-1101).
"""

import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from xdj_pi_dev._terminal import (
    _C, Step, section, ok, warn, fail, _log_line,
)
from xdj_pi_dev.messages import MSG

# ─── Module-level constants ───────────────────────────────────────────────────

# Resolve relative to this file: xdj_pi_dev/ → tools/ → repo root
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_PI_USER   = os.environ.get("XDJ_USER", "xdj100sx")

REPO_FIRMWARE   = _REPO_ROOT / "arduino" / "pico" / "pico-XDJ100SX.ino"
PI_FIRMWARE_DIR = f"/home/{_PI_USER}/pico-firmware"
PI_FIRMWARE_INO = f"{PI_FIRMWARE_DIR}/pico-XDJ100SX.ino"
PI_BUILD_DIR    = f"{PI_FIRMWARE_DIR}/build"
ARDUINO_CLI_URL = (
    "https://downloads.arduino.cc/arduino-cli/arduino-cli_latest_Linux_ARMv7.tar.gz"
)
ARDUINO_BOARD_URL = (
    "https://github.com/earlephilhower/arduino-pico/releases/download/global/"
    "package_rp2040_index.json"
)

# Board profiles: short name → full FQBN
# rp2040 boards need usbstack=tinyusb for Adafruit TinyUSB to compile
BOARD_PROFILES: dict[str, str] = {
    "pico":      "rp2040:rp2040:rpipico:usbstack=tinyusb",
    "pico2":     "rp2040:rp2040:rpipico2:usbstack=tinyusb",
    "picow":     "rp2040:rp2040:rpipicow:usbstack=tinyusb",
    "micro":     "arduino:avr:micro",
    "leonardo":  "arduino:avr:leonardo",
    "uno":       "arduino:avr:uno",
    "nano":      "arduino:avr:nano",
}
DEFAULT_BOARD = "pico"


# ─── Pico bootloader ──────────────────────────────────────────────────────────

def pico_bootloader(pi_client) -> str:
    """
    Reset the Pico into UF2 bootloader mode via MIDI Note 127 ch16 vel127.

    Mixxx holds the ALSA MIDI port while running, so we must stop it first.
    amidi (already on Pi) is used — no Python dependencies needed.
    Mixxx auto-restarts via the xinitrc while-loop after ~2-3 s.
    """
    # Kill Mixxx so it releases the ALSA port; SIGTERM then SIGKILL to be sure
    ok("Stopping Mixxx…")
    pi_client.exec(
        "pkill -x mixxx 2>/dev/null; sleep 2; pkill -9 -x mixxx 2>/dev/null; true",
        timeout=10,
    )
    time.sleep(1)   # let ALSA finish releasing the port

    # Find Pico MIDI port via amidi -l; default to hw:1,0,0 (card 1 = USB)
    ports_r = pi_client.exec("amidi -l 2>&1")
    port = "hw:1,0,0"
    for line in ports_r["stdout"].splitlines():
        if "XDJ" in line or "Pico" in line or "USB" in line.upper():
            for tok in line.split():
                if tok.startswith("hw:"):
                    port = tok
                    break

    ok(f"Sending update signal via {port}…")
    # Note On: status 0x9F = ch16, note 0x7F = 127, vel 0x7F = 127.
    # Shell timeout prevents hang if the Pico reboots and amidi stalls on ALSA cleanup.
    # rc=124 means shell killed amidi = port vanished during send = likely success.
    r = pi_client.exec(f"timeout 6 amidi -p {port} -S '9F 7F 7F' 2>&1", timeout=10)
    amidi_out = r["stdout"].strip()
    amidi_rc  = r["rc"]

    if amidi_rc not in (0, 124) and amidi_out:
        # amidi returned a real error — port busy, not found, etc.
        return f"amidi error (rc={amidi_rc}): {amidi_out}"

    time.sleep(3)  # give Pico time to enumerate as mass storage

    # Broad detection: check by-label symlink (most reliable), then lsblk fallbacks
    check = pi_client.exec(
        "ls /dev/disk/by-label/RPI-RP2 2>/dev/null && echo BY_LABEL;"
        "lsblk -no NAME,LABEL  2>/dev/null | grep -i RPI-RP2  && echo BY_LABEL_LSBLK;"
        "lsblk -no NAME,VENDOR 2>/dev/null | grep -i raspberr && echo BY_VENDOR;"
        "lsblk -no NAME,MODEL  2>/dev/null | grep -iE 'RP2|RPI' && echo BY_MODEL;"
        "mountpoint -q /media/RPI-RP2 2>/dev/null && echo MOUNTED || true"
    )
    found = any(k in check["stdout"] for k in ("BY_LABEL", "BY_VENDOR", "BY_MODEL", "MOUNTED"))
    if found:
        return MSG["pico_boot_ok"]

    # Port vanished (amidi hung and was killed, or returned "No such") → likely in bootloader
    if amidi_rc == 124 or not amidi_out or "No such" in amidi_out or "cannot open" in amidi_out:
        ok("Update signal sent — Pico is rebooting into update mode…")
        time.sleep(4)
        check2 = pi_client.exec(
            "ls /dev/disk/by-label/RPI-RP2 2>/dev/null && echo BY_LABEL;"
            "lsblk -no NAME,LABEL  2>/dev/null | grep -i RPI-RP2 && echo BY_LABEL_LSBLK || true"
        )
        if any(k in check2["stdout"] for k in ("BY_LABEL", "BY_LABEL_LSBLK")):
            return MSG["pico_boot_ok"]
        return MSG["pico_boot_likely"]

    return MSG["pico_boot_fail"]


# ─── Pico flash ───────────────────────────────────────────────────────────────

def pico_flash(pi_client, local_uf2_path: str) -> str:
    local = Path(local_uf2_path)
    if not local.exists():
        return f"File not found: {local}"

    ok(f"Uploading {local.name} to Pi…")
    remote_uf2 = f"/tmp/{local.name}"
    pi_client.write_bytes(remote_uf2, local.read_bytes())

    # Try picotool first (cleanest method — works if installed on Pi)
    r = pi_client.exec(f"picotool load {remote_uf2} --force 2>&1", timeout=8)
    if r["rc"] == 0:
        return f"Flashed via picotool: {local.name}\n{r['stdout'].strip()}"

    ok("Locating RPI-RP2 block device and mounting…")

    # Shell script that:
    # 1. Finds the Pico block device via lsblk VENDOR (reads sysfs — no blkid probe, no hang)
    # 2. Mounts it with uid=1000 so the pi user can write (or uses sudo if already root-mounted)
    # 3. Verifies the mount with mountpoint before writing (not just directory existence)
    # 4. Runs cp and checks its exit code separately — a leftover empty dir won't fool us
    # 5. sync before umount to force page-cache flush to the Pico
    flash_script = (
        "MPOINT=/media/RPI-RP2\n"
        f"UF2={remote_uf2}\n"
        "mkdir -p \"$MPOINT\"\n"
        "for i in $(seq 1 30); do\n"
        # 1. by-label symlink (most reliable, set by udev on Raspberry Pi OS)
        "    DEV=$(readlink -f /dev/disk/by-label/RPI-RP2 2>/dev/null)\n"
        # 2. lsblk by LABEL
        "    [ -z \"$DEV\" ] && DEV=$(lsblk -no NAME,LABEL 2>/dev/null"
        " | awk '$2==\"RPI-RP2\"{print \"/dev/\"$1}'"
        " | grep -v mmcblk | head -1)\n"
        # 3. lsblk by MODEL (RP2 Boot, RP2, RPI-RP2)
        "    if [ -z \"$DEV\" ]; then\n"
        "        DISK=$(lsblk -no NAME,MODEL 2>/dev/null"
        " | awk '$2~/^RP2|^RPI/{print $1}'"
        " | grep -v mmcblk | head -1)\n"
        "        [ -n \"$DISK\" ] && { if [ -b \"/dev/${DISK}1\" ]; then DEV=\"/dev/${DISK}1\"; else DEV=\"/dev/$DISK\"; fi; }\n"
        "    fi\n"
        # 4. lsblk by VENDOR (RaspberryPi, Raspberry)
        "    [ -z \"$DEV\" ] && DEV=$(lsblk -no NAME,VENDOR 2>/dev/null"
        " | awk 'tolower($2)~/raspberr/{print \"/dev/\"$1}'"
        " | grep -v mmcblk | head -1)\n"
        "    if [ -n \"$DEV\" ]; then\n"
        "        if ! mountpoint -q \"$MPOINT\" 2>/dev/null; then\n"
        "            sudo mount -t vfat -o uid=1000,gid=1000,sync \"$DEV\" \"$MPOINT\" 2>/dev/null"
        " || sudo mount -t vfat -o sync \"$DEV\" \"$MPOINT\" 2>/dev/null || true\n"
        "        fi\n"
        "        if mountpoint -q \"$MPOINT\" 2>/dev/null; then\n"
        "            echo \"MOUNTED:$DEV\"\n"
        "            cp \"$UF2\" \"$MPOINT/fw.uf2\"\n"
        "            CP_RC=$?\n"
        "            sync\n"
        "            sudo umount \"$MPOINT\" 2>/dev/null || true\n"
        "            if [ \"$CP_RC\" -eq 0 ]; then\n"
        "                echo FLASHED\n"
        "                exit 0\n"
        "            else\n"
        "                echo \"CP_FAILED:$CP_RC\"\n"
        "                exit 1\n"
        "            fi\n"
        "        fi\n"
        "    fi\n"
        "    sleep 1\n"
        "done\n"
        "echo NOTMOUNTED\n"
        "exit 1\n"
    )
    r2 = pi_client.exec(flash_script, timeout=60)
    stdout = r2["stdout"]

    if "CP_FAILED" in stdout:
        return MSG["flash_fail_copy"]
    if "NOTMOUNTED" in stdout:
        return MSG["flash_fail_nodev"]
    if "FLASHED" not in stdout:
        return f"Flash failed — unexpected output:\n{stdout}"

    ok("UF2 sent — waiting for Pico to reboot into firmware…")
    for i in range(45):
        time.sleep(1)
        # Match any ttyACM* in case enumeration picks a different index
        chk = pi_client.exec(
            "ls /dev/ttyACM* 2>/dev/null | head -1 || echo WAITING",
            timeout=5,
        )
        port = chk["stdout"].strip()
        if port and port != "WAITING":
            ok(MSG["pico_alive"].format(port=port))
            midi = pi_client.exec("aconnect -l 2>/dev/null | grep -i xdj || echo NOT_VISIBLE", timeout=5)
            if "NOT_VISIBLE" not in midi["stdout"]:
                ok(MSG["pico_midi_ok"])
            else:
                warn(MSG["pico_midi_wait"])
            return MSG["flash_ok"]

    return (
        "UF2 was sent successfully but /dev/ttyACM* did not appear within 45 s.\n"
        "The firmware is on the Pico — it is not lost.\n"
        "Wait a few more seconds then run:  python3 xdj-pi-dev.py --status\n"
        "If still missing, unplug and replug the Pico USB cable on the Pi."
    )


# ─── Pico CLI setup ───────────────────────────────────────────────────────────

def setup_pico_cli(pi_client) -> None:
    """
    One-time setup: install arduino-cli on the Pi, add the arduino-pico core,
    and install the required libraries.  Downloads ~500 MB of toolchain.
    Mixxx is stopped during the download/install to free RAM, then restarted.
    """
    section("Pico Toolchain Setup  (one-time, ~500 MB download)")
    print(f"  {_C.DIM}Mixxx will be stopped during this operation.{_C.RESET}\n")

    with Step("Stopping Mixxx"):
        pi_client.exec("killall mixxx 2>/dev/null; true", timeout=5)
        time.sleep(2)

    with Step("Creating firmware directory"):
        pi_client.exec(f"mkdir -p {PI_FIRMWARE_DIR} {PI_BUILD_DIR}")

    # Download arduino-cli if not present
    cli_present = pi_client.exec("which arduino-cli")
    if cli_present["rc"] != 0:
        with Step("Downloading arduino-cli"):
            rc = pi_client.exec_stream(
                f"cd /tmp && curl -fsSL {ARDUINO_CLI_URL} | tar xz arduino-cli"
                f" && sudo mv /tmp/arduino-cli /usr/local/bin/ && echo ok",
                timeout=120,
            )
            if rc != 0:
                fail("arduino-cli download failed — check internet connection on Pi")
                with Step("Restarting Mixxx"):
                    pi_client.exec("killall mixxx 2>/dev/null; true")
                return
    else:
        ok(f"arduino-cli already installed ({cli_present['stdout'].strip()})")

    with Step("Initialising arduino-cli config"):
        pi_client.exec("arduino-cli config init --overwrite 2>/dev/null; true")
        pi_client.exec(
            f"arduino-cli config add board_manager.additional_urls {ARDUINO_BOARD_URL}"
        )

    with Step("Updating board index"):
        pi_client.exec_stream("arduino-cli core update-index 2>&1", timeout=60)

    print(f"\n  {_C.DIM}Installing RP2040 core + ARM toolchain (~500 MB)…{_C.RESET}")
    print(f"  {_C.GRAY}│{_C.RESET}")
    rc = pi_client.exec_stream("arduino-cli core install rp2040:rp2040 2>&1", timeout=900)
    if rc != 0:
        fail("Core install failed")
    else:
        ok("RP2040 core installed")

    print()
    with Step("Installing Adafruit TinyUSB"):
        pi_client.exec_stream(
            'arduino-cli lib install "Adafruit TinyUSB Library" 2>&1', timeout=120
        )
    with Step("Installing MIDI Library"):
        pi_client.exec_stream('arduino-cli lib install "MIDI Library" 2>&1', timeout=60)
    with Step("Installing Bounce2"):
        pi_client.exec_stream('arduino-cli lib install "Bounce2" 2>&1', timeout=60)

    with Step("Restarting Mixxx"):
        time.sleep(4)
        pi_client.exec("killall mixxx 2>/dev/null; true")

    print()
    ok("Toolchain ready — run --pico-compile to build firmware")


# ─── Private compile helpers ──────────────────────────────────────────────────

def _resolve_fqbn(board: str) -> str:
    """Resolve a board name or raw FQBN to a full FQBN string."""
    return BOARD_PROFILES.get(board, board)


def _compile_local(fqbn: str, ino: Path) -> Path:
    """
    Compile firmware using arduino-cli on this machine.
    Returns path to the produced .uf2 (or .hex for AVR).
    Raises RuntimeError on failure.
    """
    build_dir = Path(tempfile.mkdtemp(prefix="xdj-build-"))
    # arduino-cli requires sketch dir name == .ino stem
    sketch_dir = build_dir / ino.stem
    sketch_dir.mkdir()
    shutil.copy(ino, sketch_dir / ino.name)

    r = subprocess.run(
        [
            "arduino-cli", "compile",
            "--fqbn", fqbn,
            "--output-dir", str(build_dir),
            "--warnings", "none",
            str(sketch_dir),
        ],
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout).strip())

    artifacts = list(build_dir.glob("*.uf2")) or list(build_dir.glob("*.hex"))
    if not artifacts:
        raise RuntimeError("Compile succeeded but no .uf2/.hex found in output dir")
    return artifacts[0]


def _compile_on_pi(pi_client, fqbn: str, ino: Path) -> str:
    """
    Push firmware to Pi and compile there.
    Returns the remote path of the produced .uf2.
    Raises RuntimeError on failure.
    """
    pi_sketch_dir = f"{PI_FIRMWARE_DIR}/{ino.stem}"
    pi_ino        = f"{pi_sketch_dir}/{ino.name}"

    pi_client.exec(f"mkdir -p {pi_sketch_dir} {PI_BUILD_DIR}")
    pi_client.write_bytes(pi_ino, ino.read_bytes())

    w   = shutil.get_terminal_size((72, 24)).columns
    bar = _C.GRAY + "─" * min(w - 4, 68) + _C.RESET
    print(f"\n  {bar}")
    t0  = time.time()
    rc  = pi_client.exec_stream(
        f"arduino-cli compile --fqbn {fqbn}"
        f" --output-dir {PI_BUILD_DIR} --warnings none {pi_ino} 2>&1",
        timeout=300,
    )
    print(f"  {bar}\n")
    if rc != 0:
        raise RuntimeError(f"Compile failed on Pi after {time.time()-t0:.0f}s")

    check = pi_client.exec(f"ls {PI_BUILD_DIR}/*.uf2 {PI_BUILD_DIR}/*.hex 2>/dev/null | head -1")
    path  = check["stdout"].strip()
    if not path:
        raise RuntimeError("Compile finished but no .uf2/.hex found on Pi")
    return path


# ─── Pico compile (top-level) ─────────────────────────────────────────────────

def pico_compile(pi_client, flash: bool = False, board: str = DEFAULT_BOARD) -> None:
    """
    Compile firmware then optionally flash.
    Strategy: local arduino-cli first (faster, no Pi needed); falls back to Pi.
    """
    section("Pico Firmware Compile")

    if not REPO_FIRMWARE.exists():
        fail(f"Firmware not found: {REPO_FIRMWARE}")
        return

    fqbn = _resolve_fqbn(board)
    ok(f"Board: {board}  →  {fqbn}")

    local_cli = shutil.which("arduino-cli")
    pi_cli    = pi_client.exec("which arduino-cli 2>/dev/null")["rc"] == 0

    if not local_cli and not pi_cli:
        fail("arduino-cli not found — install it first:")
        print(f"  {_C.CYAN}Mac/Linux:{_C.RESET}  brew install arduino-cli")
        print(f"  {_C.CYAN}Pi:{_C.RESET}          {sys.argv[0]} --setup-pico-cli  (Pi needs internet)")
        return

    uf2_local:  Path | None = None   # set if compiled on this machine
    uf2_remote: str  | None = None   # set if compiled on Pi

    if local_cli:
        ok(f"Compiling locally  ({local_cli})")
        t0 = time.time()
        try:
            uf2_local = _compile_local(fqbn, REPO_FIRMWARE)
        except RuntimeError as e:
            fail(f"Local compile failed:\n{e}")
            return
        kb = uf2_local.stat().st_size // 1024
        ok(f"Done in {time.time()-t0:.0f}s — {uf2_local.name}  ({kb} KB)")
    else:
        ok("Compiling on Pi  (arduino-cli found there, local not available)")
        with Step("Stopping Mixxx"):
            pi_client.exec("killall mixxx 2>/dev/null; true", timeout=5)
            time.sleep(3)
        try:
            uf2_remote = _compile_on_pi(pi_client, fqbn, REPO_FIRMWARE)
        except RuntimeError as e:
            fail(str(e))
            with Step("Restarting Mixxx"):
                pi_client.exec("killall mixxx 2>/dev/null; true")
            return
        sz_r = pi_client.exec(f"stat -c%s {uf2_remote} 2>/dev/null")["stdout"].strip()
        kb   = int(sz_r) // 1024 if sz_r.isdigit() else 0
        ok(f"Compiled on Pi — {Path(uf2_remote).name}  ({kb} KB)")

    if not flash:
        if uf2_remote:
            # nothing to do locally; restart Mixxx
            with Step("Restarting Mixxx"):
                time.sleep(2)
                pi_client.exec("killall mixxx 2>/dev/null; true")
        print()
        return

    # ── Flash path ──────────────────────────────────────────────────────────────
    print()

    # If compiled remotely, download UF2 locally so pico_flash() can upload it fresh
    if uf2_remote and not uf2_local:
        with Step("Downloading UF2 from Pi"):
            tmp = Path(tempfile.gettempdir()) / Path(uf2_remote).name
            tmp.write_bytes(pi_client.read_bytes(uf2_remote))
            uf2_local = tmp

    with Step("Triggering Pico bootloader"):
        result = pico_bootloader(pi_client)
        if "failed" in result.lower() or "error" in result.lower():
            fail(result)
            return
        ok(result)

    time.sleep(3)
    print(pico_flash(pi_client, str(uf2_local)))
    print()
