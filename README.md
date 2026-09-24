# README.md

# FT8 Plus 1.0 Protocol Feature Demo

Based on PyFT8, this program implements the FT8 Plus 1.0 protocol for demonstration purposes.

## Capabilities

- Receive standard FT8 messages: i3=1, decode standard callsign, grid, reports.
- Transmit/receive free text: i3=0, n3=0, up to 13 chars, base-42 charset.
- Transmit/receive beacon: i3=0, n3=0, content is "callsign + 6-char Maidenhead grid", every 4 slots (60s).
- Transmit/receive transparent single frame: i3=6, f2=0, up to 9 bytes, no CRC/EOT.
- Transmit/receive transparent continuous frame: i3=6, f2=1, multi-frame, 9-byte chunks, CRC8+EOT, up to 64 frames.
- Callsign strictly 3~6 chars; grid strictly 6-char Maidenhead.
- Auto extract sender callsign from message start, validate and add contact.
- Highlight in orange when own callsign is targeted.
- Auto save config, contacts, history, status.
- NTP time correction, half-duplex.

## Radio Control & Audio

- No radio control: no PTT, CAT, serial, freq, mode control; only audio output.
- Optional preamble noise for VOX control: 1s before slot, 0.5s white noise + 0.5s silence, then FT8 audio.
- Uses system default audio devices.

## Fixed Parameters

- Cycle 15s; sample rate 12000 Hz; symbol rate 6.25; HPS=4; BPT=2.
- 0.04s per hop; 0.160s per symbol; 375 hops/cycle; 750 hops/2 cycles.
- TX freq 300~3000 Hz; default 1500 Hz; step 6.25 Hz.
- Max raw data 574 bytes; total 576 bytes; max 64 frames.
- Freq group tolerance +/-10 Hz; merge delay 4 slots (60s).
- Max contacts 100; max history 100; max status messages 100; max note 32 bytes.

## Persistent Files

- config.txt: callsign, TX freq, preamble noise, grid.
- contact.txt: contacts, one "callsign,note" per line.
- history.txt: history, JSON Lines.
- status.txt: status log, plain text.

## Validation Rules

- Callsign: strict 3~6 chars, structure 1~2 prefix + 1 digit + 0~3 letters, prefix has at least one letter.
- Grid: strict 6-char Maidenhead, format [A-R]{2}[0-9]{2}[A-X]{2}.