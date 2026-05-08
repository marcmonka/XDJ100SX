from __future__ import annotations

"""
Watch mode: detect skin file changes and auto-deploy to Pi.

Extracted from xdj-pi-dev.py (lines 1706-1863).
"""

import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from xdj_pi_dev._terminal import warn

# ─── Module-level config ──────────────────────────────────────────────────────

# Resolve relative to this file: xdj_pi_dev/ → tools/ → repo root
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_PI_USER   = os.environ.get("XDJ_USER", "xdj100sx")

_REPO_SKIN    = _REPO_ROOT / "mixxx" / "SKIN" / "XDJ100SX"
_PI_SKIN      = f"/home/{_PI_USER}/.mixxx/skins/XDJ100SX"
_PI_MIXXX_ENV = f"DISPLAY=:0 XAUTHORITY=/home/{_PI_USER}/.Xauthority"

_PANELS = {
    "hotcue":   (368, 57), "hc":  (368, 57),
    "beatloop": (464, 57), "bl":  (464, 57),
    "keyshift": (560, 57), "ks":  (560, 57),
    "beatjump": (656, 57), "bj":  (656, 57),
    "stems":    (752, 57), "st":  (752, 57),
}

_FILE_PANEL = {
    "hotcues.xml":  "hotcue",
    "beatloop.xml": "beatloop",
    "keyshift.xml": "keyshift",
    "beatjump.xml": "beatjump",
    "stems.xml":    "stems",
}


# ─── Platform helpers ─────────────────────────────────────────────────────────

def _tmp_path(name: str) -> Path:
    return Path(tempfile.gettempdir()) / name


def _open_image(path: Path) -> None:
    """Open an image in the default viewer — macOS, Linux, Windows."""
    s = str(path)
    if sys.platform == "darwin":
        subprocess.run(["open", s], check=False)
    elif sys.platform == "win32":
        os.startfile(s)
    else:
        subprocess.run(["xdg-open", s], check=False)


# ─── Navigation / screenshot inlined ─────────────────────────────────────────

def _navigate_panel(pi_client, panel_key: str) -> None:
    key = panel_key.lower().strip()
    coords = _PANELS.get(key)
    if not coords:
        return
    x, y = coords
    pi_client.exec(f"{_PI_MIXXX_ENV} xdotool mousemove {x} {y} click 1", timeout=5)
    time.sleep(0.4)


def _restart_mixxx(pi_client, panel: str | None = None) -> str:
    pi_client.exec("killall mixxx 2>/dev/null; true")
    time.sleep(6)
    result = pi_client.exec("pgrep -a mixxx")
    pid = result["stdout"].strip()
    msg = (f"Mixxx restarted (PID {pid.split()[0]})" if pid
           else "WARNING: Mixxx PID not found — may still be starting")
    if panel:
        time.sleep(1)
        _navigate_panel(pi_client, panel)
    return msg


def _take_screenshot(pi_client, panel: str | None = None) -> tuple[bytes | None, str | None]:
    """Navigate to `panel` then capture. Returns (bytes, None) or (None, error)."""
    if panel:
        _navigate_panel(pi_client, panel)
    pi_client.exec("rm -f /tmp/xdj_dev_screen.png")
    r = pi_client.exec(f"{_PI_MIXXX_ENV} scrot /tmp/xdj_dev_screen.png 2>&1", timeout=10)
    if r["rc"] != 0:
        return None, (r["stdout"] + r["stderr"]).strip()
    return pi_client.read_bytes("/tmp/xdj_dev_screen.png"), None


# ─── Deploy helper ────────────────────────────────────────────────────────────

def _deploy_changes(pi_client, paths: list[str], panel: str | None, restart: bool) -> None:
    changed_names = [Path(p).name for p in paths]
    print(f"\n[{time.strftime('%H:%M:%S')}] Changed: {', '.join(changed_names)}")

    for path in paths:
        f = Path(path)
        if not f.exists():
            continue
        remote = f"{_PI_SKIN}/{f.relative_to(_REPO_SKIN).as_posix()}"
        pi_client.write_bytes(remote, f.read_bytes())
        print(f"  pushed {f.name}")

    target_panel = panel
    if not target_panel:
        for name in changed_names:
            target_panel = _FILE_PANEL.get(name)
            if target_panel:
                break

    if restart:
        print("  restarting Mixxx…")
        print(f"  {_restart_mixxx(pi_client, panel=target_panel)}")
    else:
        pi_client.exec(f"{_PI_MIXXX_ENV} xdotool key ctrl+F5", timeout=5)
        time.sleep(2)
        if target_panel:
            _navigate_panel(pi_client, target_panel)

    print("  screenshotting…")
    data, err = _take_screenshot(pi_client, panel=None)
    if err:
        print(f"  screenshot failed: {err}")
        return

    out = _tmp_path("xdj_watch_screen.png")
    out.write_bytes(data)
    _open_image(out)
    print(f"  screenshot → {out}")


# ─── Public watch_mode ────────────────────────────────────────────────────────

def watch_mode(pi_client, panel: str | None = None, restart: bool = False) -> None:
    print(f"Watching {_REPO_SKIN}")
    print("Edit any skin file — changes deploy to Pi automatically.")
    print("Ctrl-C to stop.\n")

    try:
        from watchdog.observers import Observer
        from watchdog.events import FileSystemEventHandler

        class Handler(FileSystemEventHandler):
            def __init__(self) -> None:
                self.pending: dict[str, float] = {}

            def on_modified(self, event) -> None:
                if not event.is_directory:
                    self.pending[event.src_path] = time.time()

            def on_created(self, event) -> None:
                self.on_modified(event)

        handler = Handler()
        observer = Observer()
        observer.schedule(handler, str(_REPO_SKIN), recursive=True)
        observer.start()
        try:
            while True:
                time.sleep(0.5)
                now   = time.time()
                ready = [p for p, t in list(handler.pending.items()) if now - t > 0.8]
                if not ready:
                    continue
                for path in ready:
                    del handler.pending[path]
                _deploy_changes(pi_client, ready, panel, restart)
        finally:
            observer.stop()
            observer.join()

    except ImportError:
        print("(watchdog not installed — using 1s polling. pip install watchdog for faster)\n")
        mtimes = {f: f.stat().st_mtime for f in _REPO_SKIN.rglob("*") if f.is_file()}
        while True:
            time.sleep(1)
            changed = []
            for f in _REPO_SKIN.rglob("*"):
                if not f.is_file():
                    continue
                mt = f.stat().st_mtime
                if mt != mtimes.get(f):
                    mtimes[f] = mt
                    changed.append(str(f))
            if changed:
                _deploy_changes(pi_client, changed, panel, restart)


# ─── Stoppable watch loop (used by TUI) ──────────────────────────────────────

def _watch_loop(pi_client, stop_event: threading.Event, emit=None, screenshot_fn=None) -> None:
    """Watch skin files and push on change. Stops when stop_event is set.

    screenshot_fn: optional callable(paths) invoked after each successful deploy.
    """
    _emit = emit or (lambda lvl, msg: None)
    _emit("info", f"Watching {_REPO_SKIN}")

    def _deploy(paths: list[str]) -> None:
        names = [Path(p).name for p in paths]
        _emit("info", f"Changed: {', '.join(names)}")
        for path in paths:
            f = Path(path)
            if not f.exists():
                continue
            remote = f"{_PI_SKIN}/{f.relative_to(_REPO_SKIN).as_posix()}"
            pi_client.write_bytes(remote, f.read_bytes())
        _emit("ok", f"Pushed {len(paths)} file(s)")
        if screenshot_fn:
            try:
                screenshot_fn(paths)
            except Exception as _e:
                _emit("warn", f"Screenshot: {_e}")

    try:
        from watchdog.observers import Observer
        from watchdog.events import FileSystemEventHandler

        class _Handler(FileSystemEventHandler):
            def __init__(self) -> None:
                self.pending: dict[str, float] = {}

            def on_modified(self, event) -> None:
                if not event.is_directory:
                    self.pending[event.src_path] = time.time()

            def on_created(self, event) -> None:
                self.on_modified(event)

        handler = _Handler()
        observer = Observer()
        observer.schedule(handler, str(_REPO_SKIN), recursive=True)
        observer.start()
        try:
            while not stop_event.is_set():
                time.sleep(0.5)
                now = time.time()
                ready = [p for p, t in list(handler.pending.items()) if now - t > 0.8]
                if ready:
                    for p in ready:
                        del handler.pending[p]
                    _deploy(ready)
        finally:
            observer.stop()
            observer.join()
    except ImportError:
        _emit("warn", "watchdog not installed — using 1s polling")
        mtimes = {f: f.stat().st_mtime for f in _REPO_SKIN.rglob("*") if f.is_file()}
        while not stop_event.is_set():
            time.sleep(1)
            changed = [
                str(f) for f in _REPO_SKIN.rglob("*")
                if f.is_file() and f.stat().st_mtime != mtimes.get(f)
            ]
            for f in [Path(p) for p in changed]:
                mtimes[f] = f.stat().st_mtime
            if changed:
                _deploy(changed)
