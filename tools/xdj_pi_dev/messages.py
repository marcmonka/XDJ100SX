from __future__ import annotations

"""
All user-visible strings in one place.
Use MSG["key"].format(...) for parametric messages.
"""

MSG: dict[str, str] = {
    # Connection
    "connecting":           "Connecting to {host}…",
    "connected":            "Connected to {host}",
    "not_connected":        "Not connected yet — connect to the Pi first.",
    "already_connecting":   "Already connecting — please wait.",
    "cant_reach_pi":        "Can't find the Raspberry Pi. Check that it's powered on and connected.",
    "cant_reach_pi_detail": (
        "Can't find the Raspberry Pi.\n"
        "Tried: {tried}\n"
        "If using a direct cable, set up the network alias first:\n"
        "{instructions}"
    ),

    # General operation state
    "busy":                 "Still working on the last task — please wait.",
    "op_cancelled":         "Operation cancelled.",

    # Push / pull
    "pushing_skin":         "Sending skin files to Pi…",
    "pushing_skin_backup":  "Sending skin files to Pi (saving remote copy first)…",
    "pushed_skin":          "Sent {n} file(s) to Pi.",
    "pulling_skin":         "Getting skin files from Pi…",
    "pulling_skin_backup":  "Getting skin files from Pi (saving local copy first)…",
    "pulled_skin":          "Got {n} file(s) from Pi.",
    "pushing_midi":         "Sending MIDI mapping to Pi…",
    "pushing_midi_backup":  "Sending MIDI mapping to Pi (saving remote copy first)…",
    "pushed_midi":          "Sent {n} MIDI file(s) to Pi.",
    "pulling_midi":         "Getting MIDI mapping from Pi…",
    "pulling_midi_backup":  "Getting MIDI mapping from Pi (saving local copy first)…",
    "pulled_midi":          "Got {n} MIDI file(s) from Pi.",
    "midi_reload":          "Done. To apply: open Mixxx → Preferences → Controllers and reload the mapping.",

    # Screenshot
    "screenshotting":       "Capturing Pi display…",
    "screenshot_saved":     "Screenshot saved.",

    # Mixxx
    "restarting_mixxx":     "Restarting Mixxx…",
    "mixxx_restarted":      "Mixxx restarted.",

    # Watch mode
    "watch_started":        (
        "Watch mode ON\n"
        "Watching local skin folder for changes.\n"
        "Workflow: edit any skin XML on your Mac → save → file is pushed to the Pi\n"
        "automatically → Mixxx reloads the skin (Ctrl+F5) → screenshot opens here.\n"
        "No manual Push Skin needed while Watch is running."
    ),
    "watch_stopped":        "Watch mode OFF.",

    # Pico bootloader
    "pico_boot_starting":   "Sending update signal to Pico…",
    "pico_boot_ok":         "Pico is in update mode. Click Flash UF2.",
    "pico_boot_likely":     (
        "Update signal sent — waiting for Pico to appear as a USB drive…\n"
        "If Flash UF2 fails, wait a few more seconds then try again."
    ),
    "pico_boot_fail":       (
        "Couldn't confirm Pico is in update mode.\n"
        "Try clicking Bootloader first, then Flash UF2."
    ),

    # Pico flash
    "flashing":             "Installing firmware on Pico…",
    "flash_ok":             "Firmware installed successfully.",
    "flash_fail_nofile":    "No firmware file found. Compile the firmware first.",
    "flash_fail_nodev":     (
        "Couldn't find Pico in update mode after 30 seconds.\n"
        "Click Bootloader first, then try Flash UF2 again."
    ),
    "flash_fail_copy":      "Firmware file could not be written to Pico.",
    "pico_alive":           "Pico is running on {port}.",
    "pico_midi_ok":         "MIDI is visible — reload the mapping in Mixxx: Preferences → Controllers",
    "pico_midi_wait":       "Pico is running but MIDI isn't visible yet — restart Mixxx.",

    # Setup / check
    "preflight_start":      "Pre-flight check…",
    "ssh_keys_starting":    "Setting up SSH key login…",
    "dhcp_starting":        "Configuring Pi DHCP server…",
    "discovering":          "Scanning network for Pi units…",
    "no_units_found":       "No Pi units found — check cable / network.",
    "backup_starting":      "Pi backup — reading used blocks only… (this takes a few minutes)",
    "backup_wait":          "Do not disconnect while the backup is running.",
    "backup_saved":         "Backup saved → {path}",
    "verifying_backup":     "Verifying backup {name}…",
    "verify_ok":            "Backup file looks good.",

    # Signal analyzer
    "signal_an_started":    "Signal Analyzer → {url}",
    "signal_an_stopped":    "Signal Analyzer stopped.",
}
