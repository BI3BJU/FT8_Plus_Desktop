# i18n.py - Internationalization module (grid & beacon removed)
# Default: English (US), built-in (no en_rUS.txt file).
# External: {lang}_r{REGION}.txt in the root directory, JSON content.
# Auto-matched by Windows system locale.

import json
import locale
import ctypes
from pathlib import Path

BASE_DIR = Path(__file__).parent
DEFAULT_TAG = "en_rUS"

# Internal markers (used as code tokens; display is translated separately)
MARKER_FREE_TEXT = "[Free text]"
MARKER_RECEIVING = "[Receiving]"
MARKER_CRC_OK = "[CRC OK]"
MARKER_CRC_FAIL = "[CRC fail]"
MARKER_TIMEOUT = "[Timeout]"
MARKER_SENDING = "[Sending]"
MARKER_SENT = "[Sent]"
MARKER_FAIL = "[TX failed]"
MARKER_INTERRUPT = "[Interrupted]"
MARKER_SINGLE = "[Single]"
MARKER_BEACON = "[Beacon]"

# Built-in English (US) translations.
DEFAULT_TRANSLATIONS = {
    "about.text": """FT8 Plus Protocol Function Demonstration Program 1.0 

Based on PyFT8, this program implements the FT8 Plus 1.0 protocol for demonstration purposes.

Open source: https://github.com/BI3BJU

Capabilities:
- Receive standard FT8 messages: i3=1, decode standard callsign, grid, reports.
- Transmit/receive free text: i3=0, n3=0, up to 13 chars, base-42 charset.
- Transmit/receive transparent single frame: i3=6, f2=0, up to 9 bytes, no CRC/EOT.
- Transmit/receive transparent continuous frame: i3=6, f2=1, multi-frame, 9-byte chunks, CRC8+EOT, up to 64 frames.
- Beacon mode: periodic transmission every 4 minutes, auto-filled at slot start.
- Callsign strictly 3~7 chars.
- Auto extract sender callsign from message start, validate and add contact.
- Fill rule: "All" -> callsign + space; specific contact -> callsign + space + target + space.
- Target callsign: substring between the first space and the following second space.
- Highlight in orange when own callsign is targeted.
- Auto save config, contacts, history, status.
- NTP time correction, half-duplex.

Radio Control & Audio:
- No radio control: no PTT, CAT, serial, freq, mode control; only audio output.
- Optional preamble noise for VOX control: 1s before slot, 0.5s white noise + 0.5s silence, then FT8 audio.
- Uses system default audio devices.

Fixed parameters:
- Cycle 15s; sample rate 12000 Hz; symbol rate 6.25; HPS=4; BPT=2.
- 0.04s per hop; 0.160s per symbol; 375 hops/cycle; 750 hops/2 cycles.
- TX freq 300~3000 Hz; default 1500 Hz; step 6.25 Hz.
- Max raw data 574 bytes; total 576 bytes; max 64 frames.
- Freq group tolerance +/-10 Hz; merge delay 4 slots (60s).
- Max contacts 100; max history 100; max status messages 100; max note 32 bytes.

Persistent files:
- config.txt: callsign, TX freq, preamble noise.
- contact.txt: contacts, one "callsign,note" per line.
- history.txt: history, JSON Lines.
- status.txt: status log, plain text.

Validation rules:
- Callsign: strict 3~7 chars total, structure 1~2 prefix + 1 digit + 0~4 letters, prefix has at least one letter.
""",
    "Beacon": "Beacon",
    "Rx running (processing i3=0,1,6 messages)": "Rx running (processing i3=0,1,6 messages)",
    "read wav file with hop mean = {mean}ms, sd = {sd}ms": "read wav file with hop mean = {mean}ms, sd = {sd}ms",
}


class I18n:
    def __init__(self, base_dir=None):
        self.base_dir = Path(base_dir) if base_dir else BASE_DIR
        self.current_tag = DEFAULT_TAG
        self.translations = dict(DEFAULT_TRANSLATIONS)
        self.load_auto()

    def _read_json(self, path):
        with open(path, 'r', encoding='utf-8-sig') as f:
            return json.load(f)

    def normalize_tag(self, tag):
        if not tag:
            return DEFAULT_TAG
        parts = tag.replace('-', '_').split('_')
        lang = parts[0].lower()
        region = None
        for p in reversed(parts[1:]):
            if len(p) == 2 and p.isalpha():
                region = p.upper()
                break
        if region is None:
            region = "US"
        return f"{lang}_r{region}"

    def get_system_tag(self):
        raw = None
        try:
            buf = ctypes.create_unicode_buffer(85)
            if ctypes.windll.kernel32.GetUserDefaultLocaleName(buf, len(buf)):
                raw = buf.value
        except Exception:
            pass
        if not raw:
            try:
                raw = locale.getdefaultlocale()[0]
            except Exception:
                raw = None
        return self.normalize_tag(raw or "en_US")

    def _load_file(self, tag):
        path = self.base_dir / f"{tag}.txt"
        if not path.exists():
            # 外部翻译文件缺失属于预期情况，静默回退到内置英文。
            return None
        try:
            return self._read_json(path)
        except Exception as e:
            print(f"[i18n] Failed to load {path}: {e}")
            return None

    def load_auto(self):
        self.load(self.get_system_tag())

    def load(self, tag):
        tag = self.normalize_tag(tag)
        self.current_tag = tag

        data = self._load_file(tag)
        if data is not None:
            merged = dict(DEFAULT_TRANSLATIONS)
            merged.update(data)
            self.translations = merged
            print(f"[i18n] Loaded exact match: {tag}")
            return

        lang = tag.split('_')[0]
        region_priority = ['rCN', 'rTW', 'rHK', 'rSG']
        candidates = list(self.base_dir.glob(f"{lang}_r*.txt"))

        def priority(path):
            stem = path.stem
            region = stem.split('_')[-1] if '_' in stem else ''
            if region in region_priority:
                return region_priority.index(region)
            return len(region_priority)

        candidates.sort(key=priority)

        for path in candidates:
            try:
                data = self._read_json(path)
                merged = dict(DEFAULT_TRANSLATIONS)
                merged.update(data)
                self.translations = merged
                self.current_tag = path.stem
                print(f"[i18n] Loaded fallback: {path.stem} (requested {tag})")
                return
            except Exception as e:
                print(f"[i18n] Failed to load {path}: {e}")
                continue

        self.translations = dict(DEFAULT_TRANSLATIONS)
        self.current_tag = DEFAULT_TAG

    def gettext(self, msgid, **kwargs):
        text = self.translations.get(msgid, msgid)
        if kwargs:
            try:
                return text.format(**kwargs)
            except Exception:
                return text
        return text


_i18n = I18n()


def init(tag=None):
    global _i18n
    _i18n = I18n()
    if tag:
        _i18n.load(tag)
    return _i18n


def _(msgid, **kwargs):
    return _i18n.gettext(msgid, **kwargs)


def current_tag():
    return _i18n.current_tag