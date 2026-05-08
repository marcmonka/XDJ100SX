# XDJ-100SX Developer Tool

Claude Code MCP server + CLI + TUI for the XDJ-100SX Pi system.
Push skin files, take screenshots, flash firmware, and manage the Pi — all from your editor.

---

## Requirements

```bash
pip install paramiko watchdog textual
```

---

## Quick start

```bash
python3 tools/xdj-pi-dev.py --check      # verify connection + environment
python3 tools/xdj-pi-dev.py --status     # live Pi + Mixxx status
python3 tools/xdj-pi-dev.py --ui         # interactive TUI
python3 tools/xdj-pi-dev.py --about      # authors & credits
python3 tools/xdj-pi-dev.py --help       # full command reference
```

---

## Connection

The tool tries these in order:

1. `--host` flag
2. `XDJ_HOST` environment variable
3. `XDJ100SX.local` — mDNS, works on any network (WiFi or LAN)
4. `192.168.10.2` — static IP fallback for direct cable

### Direct cable (no router)

One-time setup on your machine:

```bash
# macOS
sudo ifconfig en0 alias 192.168.10.1 255.255.255.0

# Linux
sudo ip addr add 192.168.10.1/24 dev eth0

# Windows (run as Administrator)
netsh interface ip set address "Ethernet" static 192.168.10.1 255.255.255.0
```

Then on the Pi (once):

```bash
python3 tools/xdj-pi-dev.py --setup-pi-dhcp
```

After that the Pi hands out IPs automatically — no manual config needed on any machine.

### Multi-unit

Each Pi should have a unique hostname:

```bash
python3 tools/xdj-pi-dev.py --set-hostname xdj-unit2
```

Then from Claude Code:
- `discover_units` — lists all reachable XDJ units on the network
- `select_unit` — switches the active connection to a specific unit

---

## Claude Code MCP setup

Add to `.mcp.json` in your project root:

```json
{
  "mcpServers": {
    "xdj-pi-dev": {
      "command": "python3",
      "args": ["tools/xdj-pi-dev.py"]
    }
  }
}
```

Add to `.claude/settings.local.json`:

```json
{
  "enabledMcpjsonServers": ["xdj-pi-dev"]
}
```

Restart Claude Code. Once connected, you can say things like:

- *"push the skin and take a screenshot"*
- *"change the play button color in style.qss, push and screenshot"*
- *"restart Mixxx and navigate to the beat loop panel"*
- *"flash the firmware"*
- *"find all XDJ units on the network"*

---

## CLI reference

### Setup

```bash
--check                  # preflight: deps, SSH, Mixxx, audio, Pico
--discover               # scan network for all Pi units
--setup-pi-dhcp          # configure Pi as DHCP server on eth0
--setup-ssh-keys         # passwordless SSH (recommended)
--set-hostname NAME      # rename Pi (e.g. xdj-unit2)
--backup-image           # backup SD card to .tar archive
--restore-ssh            # recovery guide if SSH is locked out
```

### Skin development

```bash
--push                   # push all skin files to Pi
--push "*.qss"           # push only matching files
--pull                   # pull skin files from Pi to repo
--screenshot             # capture Pi display
--screenshot --panel ks  # navigate to panel first (hc/bl/bj/ks/st)
--restart                # restart Mixxx
--watch                  # watch, auto-push + screenshot on save
--watch --panel hc       # watch with panel navigation
```

### MIDI

```bash
--push-midi              # push MIDI mapping to Pi
--pull-midi              # pull MIDI mapping from Pi
--midi-mon               # stream live MIDI messages (Ctrl-C to stop)
```

### Pico firmware

```bash
--setup-pico-cli         # install arduino-cli on Pi (one-time)
--pico-compile           # compile firmware on Pi
--pico-bootloader        # reset Pico to UF2 bootloader
--pico-flash FILE.uf2    # flash a local .uf2 to Pi
--analyze                # live GPIO signal analyzer
```

### Other

```bash
--cmd 'CMD'              # run arbitrary SSH command on Pi
--host 192.168.1.42      # target a specific IP or hostname
--ui                     # open interactive TUI (requires textual)
--about                  # show authors and credits
```

---

## Skin development guide

See [`SKIN_DEV.md`](SKIN_DEV.md) for Mixxx widget types, layout rules, ConfigKeys, QSS constraints, and color palette — everything Claude needs to build and modify skin files correctly.
