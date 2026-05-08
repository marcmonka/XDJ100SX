from __future__ import annotations

"""
MIDI monitor — stream live MIDI events from the Pico via aseqdump / amidi.

Extracted from xdj-pi-dev.py (lines 742-843).
"""

import re
import threading
import time

from xdj_pi_dev._terminal import _tui_log_fn  # noqa: F401 — re-exported for callers


# ─── MIDI line parser ─────────────────────────────────────────────────────────

def _fmt_midi_line(text: str) -> tuple[str, str] | None:
    """Parse one aseqdump or amidi -d line → (log_type, formatted_string) or None."""
    t = text.strip()
    if not t or t.startswith("Source") or t.startswith("Waiting") or t.startswith("ALSA"):
        return None

    # aseqdump: " 20:0   Control change          1, controller 7, value 64"
    m = re.search(r'Control change\s+(\d+),\s*controller\s+(\d+),\s*value\s+(\d+)', t)
    if m:
        ch, ctrl, val = int(m.group(1)), int(m.group(2)), int(m.group(3))
        bar = "▓" * (val * 16 // 127) + "░" * (16 - val * 16 // 127)
        return "info", f"CC  ch{ch:2d} ctrl={ctrl:3d}  val={val:3d}  [{bar}]"

    m = re.search(r'Note on\s+(\d+),\s*note\s+(\d+),\s*velocity\s+(\d+)', t)
    if m:
        ch, note, vel = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return "ok", f"NON ch{ch:2d} note={note:3d}  vel={vel:3d}"

    m = re.search(r'Note off\s+(\d+),\s*note\s+(\d+)', t)
    if m:
        ch, note = int(m.group(1)), int(m.group(2))
        return "warn", f"NOF ch{ch:2d} note={note:3d}"

    m = re.search(r'Pitch bend\s+(\d+),\s*value\s+(-?\d+)', t)
    if m:
        ch, val = int(m.group(1)), int(m.group(2))
        return "info", f"PB  ch{ch:2d} val={val:6d}"

    # amidi -d raw hex: "B0 07 40"
    parts = t.split()
    if parts and re.match(r'^[0-9A-Fa-f]{2}$', parts[0]):
        try:
            status = int(parts[0], 16)
            mtype = (status & 0xF0) >> 4
            ch = (status & 0x0F) + 1
            b1 = int(parts[1], 16) if len(parts) > 1 else 0
            b2 = int(parts[2], 16) if len(parts) > 2 else 0
            if mtype == 0xB:
                bar = "▓" * (b2 * 16 // 127) + "░" * (16 - b2 * 16 // 127)
                return "info", f"CC  ch{ch:2d} ctrl={b1:3d}  val={b2:3d}  [{bar}]"
            if mtype == 0x9 and b2 > 0:
                return "ok",   f"NON ch{ch:2d} note={b1:3d}  vel={b2:3d}"
            if mtype == 0x8 or (mtype == 0x9 and b2 == 0):
                return "warn", f"NOF ch{ch:2d} note={b1:3d}"
            if mtype == 0xE:
                val = (b2 << 7 | b1) - 8192
                return "info", f"PB  ch{ch:2d} val={val:6d}"
        except (ValueError, IndexError):
            pass

    return "info", t


# ─── MIDI monitor ─────────────────────────────────────────────────────────────

def midi_monitor(pi_client, stop_event: threading.Event, emit=None) -> None:
    """Stream live MIDI from the Pico via aseqdump (falls back to amidi -d).

    Parameters
    ----------
    pi_client:
        A connected PiClient instance.
    stop_event:
        Threading event; monitoring stops when set.
    emit:
        Optional callable(level, msg) for TUI output.
    """
    # Find the Pico's ALSA sequencer port
    ports_out = pi_client.exec("aconnect -l 2>/dev/null")
    seq_port = None
    for line in ports_out["stdout"].splitlines():
        if "XDJ" in line or "Pico" in line:
            m = re.search(r'client (\d+):', line)
            if m:
                seq_port = f"{m.group(1)}:0"
                break

    # Build the monitoring command
    if seq_port:
        cmd = f"aseqdump -p {seq_port} 2>/dev/null || amidi -p hw:1,0,0 -d 2>&1"
        label = f"aseqdump port {seq_port}"
    else:
        cmd = "amidi -p hw:1,0,0 -d 2>&1"
        label = "amidi hw:1,0,0"

    if emit:
        emit("head", f"MIDI monitor — {label}  (press button to stop)")

    transport = pi_client._ssh.get_transport()
    assert transport
    channel = transport.open_session()
    channel.set_combine_stderr(True)
    channel.exec_command(cmd)

    buf = b""
    while not stop_event.is_set():
        if channel.recv_ready():
            buf += channel.recv(4096)
            while b"\n" in buf:
                raw, buf = buf.split(b"\n", 1)
                parsed = _fmt_midi_line(raw.decode(errors="replace"))
                if parsed and emit:
                    emit(*parsed)
        elif channel.exit_status_ready() and not channel.recv_ready():
            break
        else:
            time.sleep(0.02)

    channel.close()
