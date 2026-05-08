from __future__ import annotations

"""
Shared terminal UI helpers.

Extracted from xdj-pi-dev.py so all sub-modules can import consistent
colour, spinner, and logging primitives without circular dependencies.
"""

import itertools
import shutil
import sys
import threading
from typing import Any


# ─── ANSI colour ─────────────────────────────────────────────────────────────

def _ansi_enable() -> bool:
    """Enable ANSI on Windows; return True if terminal supports colour."""
    if not sys.stdout.isatty():
        return False
    if sys.platform == "win32":
        try:
            import ctypes
            k = ctypes.windll.kernel32
            k.SetConsoleMode(k.GetStdHandle(-11), 7)
        except Exception:
            return False
    return True


_COLOR = _ansi_enable()


class _C:
    RESET  = "\033[0m"   if _COLOR else ""
    BOLD   = "\033[1m"   if _COLOR else ""
    DIM    = "\033[2m"   if _COLOR else ""
    GREEN  = "\033[32m"  if _COLOR else ""
    YELLOW = "\033[33m"  if _COLOR else ""
    RED    = "\033[31m"  if _COLOR else ""
    CYAN   = "\033[36m"  if _COLOR else ""
    GRAY   = "\033[90m"  if _COLOR else ""
    ERASE  = "\r\033[K"  if _COLOR else "\r"


_SPIN_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


# ─── Spinner step ─────────────────────────────────────────────────────────────

class Step:
    """
    Context manager for a named operation with a live spinner.

        with Step("Stopping Mixxx"):
            pi_client.exec("killall mixxx")

    Prints  ⠹  Stopping Mixxx...   while running,
    then    ✓  Stopping Mixxx       on success,
    or      ✗  Stopping Mixxx       on exception.
    """

    def __init__(self, label: str, indent: int = 2) -> None:
        self.label  = label
        self.indent = " " * indent
        self._stop  = threading.Event()
        self._thread: threading.Thread | None = None

    def __enter__(self) -> "Step":
        self._stop.clear()
        self._thread = threading.Thread(target=self._spin, daemon=True)
        self._thread.start()
        return self

    def _spin(self) -> None:
        for frame in itertools.cycle(_SPIN_FRAMES):
            sys.stdout.write(
                f"{_C.ERASE}{self.indent}{_C.CYAN}{frame}{_C.RESET}"
                f"  {self.label}…"
            )
            sys.stdout.flush()
            if self._stop.wait(0.08):
                break

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join()
        if exc_type is None:
            sys.stdout.write(
                f"{_C.ERASE}{self.indent}{_C.GREEN}✓{_C.RESET}"
                f"  {self.label}\n"
            )
        else:
            sys.stdout.write(
                f"{_C.ERASE}{self.indent}{_C.RED}✗{_C.RESET}"
                f"  {self.label}  {_C.DIM}({exc_val}){_C.RESET}\n"
            )
        sys.stdout.flush()
        return False  # don't suppress exceptions


# ─── Log routing ──────────────────────────────────────────────────────────────

# Set by XDJApp when TUI is active; (level, msg) -> None  where level in ok/warn/fail/info/head
_tui_log_fn: Any = None


def section(title: str) -> None:
    if _tui_log_fn:
        _tui_log_fn("head", title)
        return
    w = shutil.get_terminal_size((72, 24)).columns
    bar = "─" * min(w, 72)
    print(f"\n{_C.BOLD}{bar}{_C.RESET}")
    print(f"  {_C.BOLD}{title}{_C.RESET}")
    print(f"{_C.BOLD}{bar}{_C.RESET}")


def ok(msg: str) -> None:
    if _tui_log_fn:
        _tui_log_fn("ok", msg)
        return
    print(f"  {_C.GREEN}✓{_C.RESET}  {msg}")


def warn(msg: str) -> None:
    if _tui_log_fn:
        _tui_log_fn("warn", msg)
        return
    print(f"  {_C.YELLOW}⚠{_C.RESET}  {msg}")


def fail(msg: str) -> None:
    if _tui_log_fn:
        _tui_log_fn("fail", msg)
        return
    print(f"  {_C.RED}✗{_C.RESET}  {msg}")


def _log_line(line: str) -> None:
    lo = line.lower()
    if _tui_log_fn:
        if any(x in lo for x in ("error:", "fatal error:", " error ")):
            _tui_log_fn("fail", line)
        elif "warning:" in lo:
            _tui_log_fn("warn", line)
        elif line.strip():
            _tui_log_fn("info", line)
        return
    if any(x in lo for x in ("error:", "fatal error:", " error ")):
        print(f"  {_C.RED}│{_C.RESET} {_C.RED}{line}{_C.RESET}")
    elif "warning:" in lo:
        print(f"  {_C.YELLOW}│{_C.RESET} {_C.YELLOW}{line}{_C.RESET}")
    elif line.strip():
        print(f"  {_C.GRAY}│{_C.RESET} {line}")
