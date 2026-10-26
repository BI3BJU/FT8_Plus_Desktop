# FT8 Plus 1.0 Protocol Demo

[![License](https://img.shields.io/badge/License-GPL--3.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.10%2B-blue)](https://www.python.org/)

Copyright (C) 2026 BI3BJU

Based on PyFT8, implement FT8 Plus 1.0 protocol for demonstration purposes.

- Project: https://github.com/BI3BJU/FT8_Plus_Desktop
- Email: guerilla1949@gmail.com

| Main |
| :---: |
| ![Main](./main.jpg) |

## Features

- Standard FT8 RX: i3=1 (callsign / grid / report).
- Free text: i3=0, n3=0, ≤13 chars, base-42 charset.
- Transparent single frame: i3=6, f2=0, ≤9 bytes UTF-8, `0x20` padding, no CRC/EOT.
- Transparent continuous frames: i3=6, f2=1, 9 bytes per frame, CRC8 + EOT `0x04`, ≤64 frames / 574 bytes. RX groups frames by frequency (±10 Hz) and reassembles them.
- Beacon: sends a 13-char Base42 location message (callsign + 8-char Maidenhead grid) every 4 minutes (16 slots), at slot start; requires a valid callsign and 8-char grid; skipped if the TX input is not empty. Received beacon messages are displayed as `CALL GRID`.
- Auto contact extraction, blue highlight when the local callsign is involved, NTP sync, half-duplex.
- Optional preamble noise for VOX: 0.5 s noise + 0.5 s silence before the FT8 waveform.

No CAT / PTT / serial / frequency control — audio only via the system default device.

## Requirements

- Python 3.10+
- A working audio input/output device
- `numpy`, `pyaudio` (required)
- `ntplib` (optional, NTP time sync)
- `winsdk` (optional, Windows system location)

## Install & Run

```bash
git clone https://github.com/BI3BJU/FT8_Plus_Desktop.git
cd FT8_Plus_Desktop
pip install -r requirements.txt
# optional, Windows location button only:
# pip install winsdk
python main.py