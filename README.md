# FT8 Plus 1.0 Protocol Feature Demo

[![License](https://img.shields.io/badge/License-GPL--3.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.8%2B-blue)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/Platform-CLI%20%7C%20GUI-lightgrey)](https://github.com/BI3BJU/FT8_Plus_Desktop)
[![GitHub last commit](https://img.shields.io/github/last-commit/BI3BJU/FT8_Plus_Desktop)](https://github.com/BI3BJU/FT8_Plus_Desktop)

---

## Screenshots

| Main |
| :---: |
| ![Main](./main.jpg) |

Copyright (C) 2026 BI3BJU

Based on PyFT8, this program implements the FT8 Plus 1.0 protocol for demonstration purposes.

- Project homepage: https://github.com/BI3BJU/FT8_Plus_Desktop
- Email: guerilla1949@gmail.com

## Capabilities

- Receive standard FT8 messages: i3=1, decode standard callsign, grid, reports.
- Transmit/receive free text: i3=0, n3=0, up to 13 chars, base-42 charset.
- Transmit/receive transparent single frame (i3=6, f2=0): UTF-8 text up to 9 bytes, right-padded with `0x20` to 9 bytes, no CRC/EOT.
- Transmit/receive transparent continuous frame (i3=6, f2=1): UTF-8 text > 9 bytes, total length is a multiple of 9 (reserving 1 byte each for CRC8 and EOT), text padded with `0x20`, then CRC8 and EOT `0x04` appended, split into 9-byte frames. Max 64 frames, max 574 bytes raw data.
- Receiver groups continuous frames by frequency (±10 Hz tolerance), concatenates them, finds `0x04` (EOT), verifies CRC8, then strips trailing `0x20` padding to recover the original text.
- The sender automatically filters out non-printable characters (including `0x04`, control characters, etc.) to avoid conflicts with EOT; `\t`, `\r`, and `\n` are preserved.
- Beacon mode: transmits `<CALL> PLUS` using standard FT8 free text (i3=0, n3=0, max 13 chars, base-42 charset). Period every 4 minutes (16 × 15 s slots), at slot start. Requires a valid callsign. If the TX input field is non-empty, the beacon slot is skipped; if empty or showing placeholder, it is auto-filled with `<CALL> PLUS`, transmitted, and cleared afterwards.
- Callsign strictly 3~7 chars.
- Auto extract sender callsign from message start, validate and add contact.
- Highlight in blue when either the sender or the target matches the local callsign.
- Auto save config, contacts, history, status.
- NTP time correction, half-duplex.

## Installation

### Prerequisites

- Python 3.8 or newer
- `pip`
- A working audio input/output device
- Optional: Git

> This program does **not** use CAT, PTT, serial port, frequency, or mode control. It only uses the system default audio output device. For VOX operation, enable the optional preamble noise in the GUI.

### 1. Clone the repository

```bash
git clone https://github.com/BI3BJU/FT8_Plus_Desktop.git
cd FT8_Plus_Desktop