from __future__ import annotations

"""
Config layer — owns all path resolution and the config file.

In dev mode (python3 xdj-pi-dev.py): paths resolve from __file__ inside the repo.
In standalone mode (PyInstaller frozen binary): paths come from ~/.xdj-pi-dev/config.json.
"""

import json
import os
import sys
from pathlib import Path

# True only when running inside a PyInstaller bundle
_FROZEN: bool = getattr(sys, "frozen", False)

CONFIG_PATH = Path.home() / ".xdj-pi-dev" / "config.json"

# Keys stored in the config file
KEYS = ["skin_dir", "midi_dir", "firmware_dir", "backup_dir", "host", "board", "ssh_user", "ssh_pass"]

# Supported boards — only "pico" has full feature support right now
BOARDS = ["pico", "pico2", "teensy", "arduino", "unknown"]
PICO_BOARDS = {"pico", "pico2"}  # boards that support UF2 bootloader + flash


def load_config() -> dict:
    """Read config file; return {} if missing or corrupt."""
    try:
        return json.loads(CONFIG_PATH.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_config(data: dict) -> None:
    """Write config to disk, creating parent dir if needed."""
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(data, indent=2))


def update_config(**kwargs) -> None:
    """Merge kwargs into existing config and save."""
    cfg = load_config()
    cfg.update(kwargs)
    save_config(cfg)


def config_complete() -> bool:
    """True when all required path keys have values."""
    cfg = load_config()
    return all(cfg.get(k) for k in ["skin_dir", "midi_dir"])


def get_board() -> str:
    """Return board name from config; default 'pico' in dev mode."""
    if _FROZEN:
        return load_config().get("board", "unknown")
    return load_config().get("board", "pico")


def is_pico_board() -> bool:
    return get_board() in PICO_BOARDS


# ─── Path getters ─────────────────────────────────────────────────────────────

def _repo_root() -> Path:
    """Repo root — only valid in dev mode."""
    return Path(__file__).resolve().parent.parent.parent


def get_skin_dir() -> Path:
    if _FROZEN:
        p = load_config().get("skin_dir")
        if not p:
            raise RuntimeError("Skin folder not configured — open Settings.")
        return Path(p)
    return _repo_root() / "mixxx" / "SKIN" / "XDJ100SX"


def get_midi_dir() -> Path:
    if _FROZEN:
        p = load_config().get("midi_dir")
        if not p:
            raise RuntimeError("MIDI folder not configured — open Settings.")
        return Path(p)
    return _repo_root() / "mixxx" / "MIDI"


def get_firmware_dir() -> Path:
    if _FROZEN:
        p = load_config().get("firmware_dir")
        if not p:
            raise RuntimeError("Firmware folder not configured — open Settings.")
        return Path(p)
    return _repo_root() / "arduino" / "pico"


def get_backup_dir() -> Path:
    if _FROZEN:
        p = load_config().get("backup_dir")
        if p:
            return Path(p)
    # Default: cwd for dev, ~/Downloads/XDJ-Backups for standalone
    if _FROZEN:
        d = Path.home() / "Downloads" / "XDJ-Backups"
        d.mkdir(parents=True, exist_ok=True)
        return d
    return _repo_root()


def get_saved_host() -> str | None:
    """Return the remembered Pi host, or None if not set."""
    return load_config().get("host") or None


def get_ssh_user() -> str:
    """SSH username: config file → XDJ_USER env → built-in default."""
    v = load_config().get("ssh_user")
    return v if v else os.environ.get("XDJ_USER", "xdj100sx")


def get_ssh_pass() -> str:
    """SSH password: config file → XDJ_PASS env → built-in default."""
    v = load_config().get("ssh_pass")
    return v if v else os.environ.get("XDJ_PASS", "xdj100sx")
