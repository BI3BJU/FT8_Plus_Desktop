# main.py - Merged from multiple modules (i18n, ft8_*, core_*)
# All code combined into a single file. Chinese comments translated to English.
# Original project directory: C:\Users\Administrator\examples\FT8_Plus

import sys
# Register this module under both names so that `from main import ...`
# reuses the same instance when main.py is executed as __main__.
# Without this, main.py is loaded twice (once as __main__, once as main),
# which duplicates every class, function and global in this file.
if __name__ == "__main__":
    sys.modules.setdefault("main", sys.modules[__name__])

import os
import json
import locale
import ctypes
import re
import threading
import time
from datetime import datetime
from pathlib import Path

# External dependencies
import numpy as np
import pyaudio
try:
    import ntplib
    _NTP_AVAILABLE = True
except ImportError:
    _NTP_AVAILABLE = False
    ntplib = None

from transmitter import (
    AudioOut,
    pack_transparent_message, pack_free_text, is_free_text_compatible,
)
from receiver import AudioIn, Receiver

# -----------------------------------------------------------------------------
# Constants (from ft8_constants.py)
# -----------------------------------------------------------------------------
MAX_RAW_DATA_BYTES = 574
MAX_TOTAL_BYTES    = 576
MAX_FRAMES         = 64
MAX_NOTE_BYTES     = 32
MAX_CONTACTS       = 100
MAX_ACTIVE_BUFFERS = 200

FIXED_MAX_HISTORY  = 100
FIXED_MAX_MESSAGES = 100
FIXED_FREQ_START   = 300
FIXED_FREQ_END     = 3000

FIXED_DELAY_SLOTS    = 4
FIXED_DELAY_SECONDS  = FIXED_DELAY_SLOTS * 15
FREQ_GROUP_TOLERANCE = 10     # Hz

PROTOCOL_PAD_BYTE = 0x20   # space
PROTOCOL_EOT_BYTE = 0x04   # EOT

BEACON_PATTERN = re.compile(r'^([A-Z0-9]{3,7}) PLUS$')

# -----------------------------------------------------------------------------
# CRC8 (from ft8_crc.py)
# -----------------------------------------------------------------------------
def _crc8_table(poly=0x07):
    table = []
    for i in range(256):
        crc = i
        for _bit in range(8):
            if crc & 0x80:
                crc = (crc << 1) ^ poly
            else:
                crc <<= 1
            crc &= 0xFF
        table.append(crc)
    return table

_CRC8_TABLE = _crc8_table()

def crc8(data, poly=0x07, init=0x00):
    crc = init
    for byte in data:
        crc = _CRC8_TABLE[(crc ^ byte) & 0xFF]
    return crc

# -----------------------------------------------------------------------------
# Callsign utilities (from ft8_callsign.py)
# -----------------------------------------------------------------------------
def is_valid_callsign(call: str) -> bool:
    """3~7 chars; 1~2 prefix + 1 digit + 0~4 letters; prefix has at least one letter."""
    call = call.strip().upper()
    if not (3 <= len(call) <= 7):
        return False
    if not re.fullmatch(r'^[A-Z0-9]{1,2}[0-9][A-Z]{0,4}$', call):
        return False
    prefix = re.match(r'^[A-Z0-9]{1,2}', call).group()
    return bool(re.search(r'[A-Z]', prefix))

def extract_source_callsign(raw_text):
    """Extract the source callsign: the token before the first space."""
    if not raw_text:
        return None
    raw_upper = raw_text.strip().upper()
    space_idx = raw_upper.find(' ')
    if space_idx != -1:
        src_part = raw_upper[:space_idx].strip()
        if is_valid_callsign(src_part):
            return src_part
    for length in range(7, 2, -1):
        if len(raw_upper) >= length:
            cand = raw_upper[:length]
            if is_valid_callsign(cand):
                return cand
    return None

def extract_target_callsign(raw_text):
    """Extract the target callsign: the token between the first and second space."""
    if not raw_text:
        return None
    raw_upper = raw_text.strip().upper()
    first_space = raw_upper.find(' ')
    if first_space == -1:
        return None
    second_space = raw_upper.find(' ', first_space + 1)
    if second_space == -1:
        cand = raw_upper[first_space + 1:].strip()
    else:
        cand = raw_upper[first_space + 1:second_space].strip()
    return cand if is_valid_callsign(cand) else None

def parse_message_callsigns(raw_text):
    return (extract_source_callsign(raw_text),
            extract_target_callsign(raw_text))

# -----------------------------------------------------------------------------
# i18n - Internationalization (merged into main.py)
# Strings files: strings-<lang>-r<REGION>.txt in project root (JSON content).
# Cross-platform locale auto-detection:
#   Windows : GetUserDefaultLocaleName via kernel32
#   macOS   : `defaults read -g AppleLocale`
#   Linux   : LC_ALL / LC_MESSAGES / LANG / LANGUAGE
#   Fallback: locale.getdefaultlocale()
# -----------------------------------------------------------------------------
def _get_base_dir():
    """Return the directory used for persistent files (config, history, etc.).

    - In PyInstaller onefile mode: the directory containing the exe.
    - In dev mode: the directory containing main.py.
    """
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).parent
    return Path(__file__).parent


def _get_i18n_dir():
    """Return the directory used for i18n strings files.

    - In PyInstaller onefile mode: sys._MEIPASS (bundled strings-*.txt).
    - In dev mode: the directory containing main.py.
    External strings next to the exe are intentionally ignored.
    """
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        return Path(sys._MEIPASS)
    return Path(__file__).parent


BASE_DIR = _get_base_dir()
_I18N_DIR = _get_i18n_dir()

DEFAULT_TAG = "en-rUS"

# Internal markers (used as code tokens; display is translated separately).
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

# Per-language default region when the OS doesn't supply one.
_LANG_DEFAULT_REGION = {
    "en": "US", "zh": "CN", "ja": "JP", "ko": "KR",
    "de": "DE", "fr": "FR", "es": "ES", "it": "IT",
    "pt": "BR", "ru": "RU", "ar": "SA", "hi": "IN",
    "nl": "NL", "pl": "PL", "tr": "TR", "sv": "SE",
    "vi": "VN", "th": "TH", "id": "ID",
}

# Per-language preferred region order when the exact region file is missing.
_LANG_REGION_PREFERENCE = {
    "zh": ["CN", "TW", "HK", "SG"],
    "en": ["US", "GB", "AU", "CA"],
    "pt": ["BR", "PT"],
    "es": ["ES", "MX", "AR"],
    "fr": ["FR", "CA"],
    "de": ["DE", "AT", "CH"],
}


DEFAULT_TRANSLATIONS = {
    # --- app ---
    "app.title": "FT8 Plus 1.0",
    "app.about": "",

    # --- beacon ---
    "beacon": "Beacon",
    "beacon.started": "Beacon started: {text}",
    "beacon.started_toast": "Beacon started",
    "beacon.skipped": "Beacon skipped: input field not empty ('{text}')",
    "beacon.stopped": "Beacon stopped",
    "beacon.error": "Beacon error: {e}",

    # --- rx ---
    "rx.running": "Rx running (processing i3=0,1,6 messages)",
    "rx.receiving": "Receiving",
    "rx.received_frames": "Received {n} frames {b} bytes",
    "rx.timeout": "Receive timeout",
    "rx.cleared_buffer": "Cleared audio buffer after single frame (freq {freq}Hz)",
    "rx.new_buffer": "Created new buffer for freq group {key}Hz, session={sid}",
    "rx.appended_frame": "Appended frame to freq group {key}Hz",
    "rx.reserved_frame": "Received reserved frame f2={f2}, ignored",

    # --- wav ---
    "wav.hop_stats": "read wav file with hop mean = {mean}ms, sd = {sd}ms",

    # --- tx ---
    "tx.failed": "TX failed",
    "tx.stopped": "TX stopped",
    "tx.busy": "Transmitting, please wait",
    "tx.need_rx": "Please start receiver first",
    "tx.empty": "Please enter data (cannot be empty)",
    "tx.non_printable": "Input contains only non-printable characters",
    "tx.too_long_bytes": "UTF-8 encoded {n} bytes, exceeds {max} bytes limit",
    "tx.too_many_frames": "Data too long: {n} frames needed, exceeds {max} limit",
    "tx.split_frames": "Transparent data split into {n} frames",
    "tx.data_content": "Data content: {text}",
    "tx.single_mode": "Single frame mode: f2=0, 0x20 padding, no CRC8/EOT",
    "tx.multi_mode": "Multi frame mode: f2=1, 9 bytes per frame",
    "tx.payload_formula": "Payload = raw + 0x20 padding + CRC8 + EOT(0x04)",
    "tx.prep_failed": "Data preparation failed: {e}",
    "tx.history_error": "Error recording TX failure history: {e}",
    "tx.free_text": "Free text: '{text}' (i3=0)",
    "tx.waiting_slot": "Waiting {t}s for slot start",
    "tx.stopped_by_user": "TX stopped by user",
    "tx.cancelled": "TX cancelled",
    "tx.noise_failed": "White noise playback failed, TX aborted",
    "tx.start_free": "Starting free text TX",
    "tx.free_ok": "Free text sent OK",
    "tx.free_failed": "Free text send failed",
    "tx.free_exception": "Free text TX exception: {e}",
    "tx.wait_next_slot": "TX complete, waiting {t}s for slot start to switch to RX",
    "tx.waiting_total": "Waiting slot... (total {n} frames)",
    "tx.frame_failed": "Frame TX failed, stopping.",
    "tx.frame_aborted": "Frame TX failed, TX aborted",
    "tx.wait_slot_end": "TX complete, waiting {t}s for slot end to switch to RX",
    "tx.switched_rx": "Switched to RX at slot end",
    "tx.complete_frames": "TX complete: {n}/{m} frames",
    "tx.failed_frames": "TX failed: {n}/{m} frames",
    "tx.interrupted_frames": "TX interrupted: {n}/{m} frames",
    "tx.error": "TX error: {e}",
    "tx.stopping": "Stopping TX...",

    # --- ntp ---
    "ntp.missing": "ntplib not installed, NTP unavailable. Run: pip install ntplib",
    "ntp.missing_toast": "ntplib not installed, cannot sync time",
    "ntp.ok": "NTP sync OK (server {server}), offset {offset:.3f}s",
    "ntp.calibrated": "Time calibrated (offset {offset:.3f}s)",
    "ntp.fail": "NTP sync failed ({server}): {e}",
    "ntp.fail_all": "NTP sync failed, using system time",

    # --- config ---
    "cfg.loaded": "Config loaded",
    "cfg.load_failed": "Config load failed: {e}, using defaults",
    "cfg.load_failed_toast": "Config load failed, using defaults",
    "cfg.save_error": "Save config error: {e}",
    "cfg.save_failed": "Save config failed: {e}",
    "cfg.callsign_invalid": "Invalid callsign: {callsign}, cleared",
    "cfg.callsign_invalid_toast": "Invalid callsign, cleared",
    "cfg.callsign_save_blocked": "Attempted to save invalid callsign, ignored",
    "cfg.callsign_save_ignored": "Invalid callsign, save ignored",
    "cfg.preamble_state": "Preamble noise {state}",
    "cfg.state_enabled": "enabled",
    "cfg.state_disabled": "disabled",

    # --- receiver ---
    "rcv.freq_error": "Error: start freq must be less than end freq",
    "rcv.freq_range_error": "Freq range error",
    "rcv.starting": "Starting receiver, freq range: {start}-{end} Hz",
    "rcv.audio_started": "Audio input started (default system device)",
    "rcv.started": "FT8 receiver started",
    "rcv.merge_delay": "Merge delay: {n} slots ({s} s)",
    "rcv.unicode_hint": "Unicode: single f2=0, multi f2=1, grouped by freq (\u00b110Hz), ends with EOT, CRC checked",
    "rcv.max_hint": "Max raw data: {n} bytes, max frames: {m}",
    "rcv.filter_hint": "Input filters non-printable (keeps \\t\\r\\n), no empty messages",
    "rcv.group_hint": "Receiver groups by freq (\u00b110Hz tolerance for first frame)",
    "rcv.auto_mode_hint": "Auto mode: input \u226413 chars all in free-text charset \u2192 i3=0, else \u2192 i3=6 Unicode",
    "rcv.start_error": "Start error: {e}",
    "rcv.start_failed": "Receiver start failed: {e}",
    "rcv.stopping": "Stopping receiver...",
    "rcv.audio_stopped": "Audio stream stopped",
    "rcv.stop_error": "Error stopping audio stream: {e}",
    "rcv.stopped": "FT8 receiver stopped",

    # --- half-duplex ---
    "hd.pause": "Half-duplex: pause RX, start TX",
    "hd.pause_clear_warn": "Warning clearing buffer before pause: {e}",
    "hd.paused": "Audio input paused and buffer cleared",
    "hd.pause_error": "Pause RX error: {e}",
    "hd.resume_clear_warn": "Warning clearing buffer on resume: {e}",
    "hd.resumed": "Audio input resumed",
    "hd.resume_error": "Resume RX error: {e}",
    "hd.resume": "Half-duplex: TX complete, resume RX",

    # --- contacts ---
    "ct.load_error": "Load contacts error: {e}",
    "ct.load_failed": "Load contacts failed: {e}",
    "ct.save_failed": "Save contacts failed: {e}",
    "ct.invalid": "Callsign {call} invalid",
    "ct.limit_add": "Contact limit {n} reached, cannot add {call}",
    "ct.limit": "Contact limit {n} reached",
    "ct.note_trunc": "Note too long, truncated to {n} bytes",
    "ct.added": "Added contact {call}",
    "ct.deleted": "Deleted contact {call}",
    "ct.exists": "Callsign {call} already exists",
    "ct.updated": "Updated contact {call}",
    "ct.auto_note": "Auto-added at {date}",
    "ct.auto_saved": "Auto-saved contact: {call} (from received msg start)",
    "ct.auto_saved_toast": "Auto-saved contact: {call}",

    # --- audio ---
    "audio.noise_error": "White noise playback exception: {e}",

    # --- gui ---
    "gui.waiting_sync": "Waiting for sync...",
    "gui.no_active_buffer": "No active buffer",
    "gui.active_groups": "Active groups: {n}",
    "gui.transmit": "Transmit",
    "gui.receive": "Receive",
    "gui.stop": "Stop",
    "gui.contacts": "Contacts",
    "gui.about": "About",
    "gui.empty_callsign": "(empty)",
    "gui.placeholder": "Up to 574 UTF-8 bytes, automatically divided into frames.",
    "gui.slot_progress": "Slot: {x}s / {y}s",
    "gui.tx_now": "Transmit now!",
    "gui.bytes": "Bytes: 0",
    "gui.bytes_n": "Bytes: {n}/{max}",
    "gui.bytes_exceeded": "Bytes: {n}/{max} (exceeded!)",
    "gui.frames": "Frames: 0",
    "gui.frames_n": "Frames: {n}",
    "gui.frames_exceeded": "Frames: {n} (exceeded!)",
    "gui.free_text_i3": "Free text (i3=0)",
    "gui.single_frame": "Single frame",
    "gui.freq_hz": "Freq (Hz):",
    "gui.freq_range": "(300-3000)",
    "gui.noise": "noise",
    "gui.manual_stop": "Manual stop",
    "gui.free_text_tag": "Free text",
    "gui.continuous": "Continuous",
    "gui.single": "Single",
    "gui.crc_ok": "CRC OK",
    "gui.crc_failed": "CRC failed",
    "gui.recv_timeout": "Receive timeout",
    "gui.sending": "Sending",
    "gui.interrupted": "Interrupted",
    "gui.send_complete": "Send complete",
    "gui.frames_progress": "[{n}/{m} frames] [{b}/{tb} bytes]",
    "gui.status_cleared": "Status cleared, deleted status.txt",
    "gui.status_delete_failed": "Failed to delete status file: {e}",
    "gui.history_cleared": "History cleared, deleted history.txt",
    "gui.history_delete_failed": "Failed to delete history file: {e}",

    # --- dialogs ---
    "dlg.contacts": "Contacts",
    "dlg.new": "New",
    "dlg.edit": "Edit",
    "dlg.delete": "Delete",
    "dlg.all": "All",
    "dlg.info": "Info",
    "dlg.warning": "Warning",
    "dlg.invalid": "Invalid",
    "dlg.invalid_callsign": "Invalid Callsign",
    "dlg.confirm_delete": "Confirm Delete",
    "dlg.select_record": "Please select a record first",
    "dlg.select_edit": "Please select a contact to edit",
    "dlg.select_delete": "Please select a contact to delete",
    "dlg.callsign_fixed": "\"All\" is fixed, cannot edit",
    "dlg.callsign_fixed_del": "\"All\" is fixed, cannot delete",
    "dlg.callsign_empty": "Callsign cannot be empty",
    "dlg.callsign_format": "Invalid callsign format (must be 3~7 chars, with at least one digit)",
    "dlg.add_failed": "Add failed (limit reached or callsign exists)",
    "dlg.update_failed": "Update failed (callsign may exist)",
    "dlg.delete_failed": "Delete failed",
    "dlg.delete_confirm": "Delete contact {callsign}?",
    "dlg.new_contact": "New Contact",
    "dlg.edit_contact": "Edit Contact",
    "dlg.callsign_label": "Callsign:",
    "dlg.note_label": "Note:",
    "dlg.ok": "OK",
    "dlg.cancel": "Cancel",
    "dlg.set_callsign": "Set Callsign",
    "dlg.enter_callsign": "Enter your callsign",
    "dlg.callsign_format_hint": "Format: 3~7 chars, contains at least one digit, letters/digits only",
    "dlg.callsign_correct": "\u2713 Correct",
    "dlg.callsign_invalid_hint": "\u274c Invalid format (3~7 chars, must contain digit)",
    "dlg.about_title": "About FT8 Plus 1.0 Protocol Demo",
    "dlg.copy": "Copy",
    "dlg.callsign_required": "Current station callsign is invalid, cannot fill. Please update callsign first.",
    "dlg.callsign_required_beacon": "Current station callsign is invalid, cannot start beacon. Please update callsign first.",

    # --- context menu ---
    "menu.copy": "Copy",
    "menu.paste": "Paste",
    "menu.clear": "Clear",
}


def _detect_system_locale():
    """Return raw locale string like 'zh_CN' / 'en_US'. Cross-platform."""
    # --- Windows ---
    if sys.platform.startswith("win"):
        try:
            buf = ctypes.create_unicode_buffer(85)
            if ctypes.windll.kernel32.GetUserDefaultLocaleName(buf, len(buf)):
                if buf.value:
                    return buf.value
        except Exception:
            pass

    # --- macOS ---
    if sys.platform == "darwin":
        try:
            import subprocess
            out = subprocess.check_output(
                ["defaults", "read", "-g", "AppleLocale"],
                stderr=subprocess.DEVNULL, timeout=2,
            ).decode("utf-8", errors="replace").strip()
            if out:
                return out.split("@")[0]
        except Exception:
            pass

    # --- Linux / Unix ---
    for var in ("LC_ALL", "LC_MESSAGES", "LANG", "LANGUAGE"):
        val = os.environ.get(var)
        if val:
            # "zh_CN.UTF-8" -> "zh_CN"; "zh_CN@variant" -> "zh_CN"
            return val.split(".")[0].split("@")[0]

    # --- Python fallback ---
    try:
        loc = locale.getdefaultlocale()[0]
        if loc:
            return loc
    except Exception:
        pass

    return "en_US"


def _normalize_tag(tag):
    """'zh_CN' / 'zh-CN' / 'zh'  ->  'zh-rCN'."""
    if not tag:
        return DEFAULT_TAG
    tag = tag.replace("-", "_")
    parts = tag.split("_")
    lang = parts[0].lower()

    region = None
    for p in reversed(parts[1:]):
        if len(p) == 2 and p.isalpha():
            region = p.upper()
            break

    if region is None:
        region = _LANG_DEFAULT_REGION.get(lang, "US")

    return f"{lang}-r{region}"


class I18n:
    """Loads strings-<lang>-r<REGION>.txt from project root (JSON content)."""

    def __init__(self, base_dir=None):
        self.base_dir = Path(base_dir) if base_dir else _I18N_DIR
        self.current_tag = DEFAULT_TAG
        self.translations = dict(DEFAULT_TRANSLATIONS)
        self.load_auto()

    # --- tag handling ---
    @staticmethod
    def normalize_tag(tag):
        return _normalize_tag(tag)

    @staticmethod
    def get_system_tag():
        return _normalize_tag(_detect_system_locale())

    # --- file loading ---
    def _strings_path(self, tag):
        return self.base_dir / f"strings-{tag}.txt"

    def _load_file(self, tag):
        path = self.base_dir / f"strings-{tag}.txt"
        if not path.exists():
            return None
        try:
            with open(path, "r", encoding="utf-8-sig") as f:
                return json.load(f)
        except Exception as e:
            print(f"[i18n] Failed to load {path}: {e}")
            return None

    def _list_available(self):
        """Return list of (tag, path) for every strings-*.txt file in base_dir."""
        result = []
        prefix = "strings-"
        if not self.base_dir.exists():
            return result
        for path in sorted(self.base_dir.glob("strings-*-r*.txt")):
            stem = path.stem                      # "strings-en-rUS"
            if not stem.startswith(prefix):
                continue
            tag = stem[len(prefix):]              # "en-rUS"
            result.append((tag, path))
        return result

    def _select_best(self, wanted_tag, available):
        """Return (tag, path) or None."""
        if not available:
            return None
        tag_to_path = dict(available)

        # 1. Exact match
        if wanted_tag in tag_to_path:
            return wanted_tag, tag_to_path[wanted_tag]

        lang = wanted_tag.split("-r")[0]

        # 2. Same language, preferred region order
        for region in _LANG_REGION_PREFERENCE.get(lang, []):
            cand = f"{lang}-r{region}"
            if cand in tag_to_path:
                return cand, tag_to_path[cand]

        # 3. Any same-language file
        same = sorted(t for t, _ in available if t.startswith(lang + "-r"))
        if same:
            return same[0], tag_to_path[same[0]]

        # 4. Default English
        if DEFAULT_TAG in tag_to_path:
            return DEFAULT_TAG, tag_to_path[DEFAULT_TAG]

        # 5. Any English variant
        en = sorted(t for t, _ in available if t.startswith("en-r"))
        if en:
            return en[0], tag_to_path[en[0]]

        # 6. First available
        return available[0]

    # --- public API ---
    def load_auto(self):
        self.load(self.get_system_tag())

    def load(self, tag):
        tag = self.normalize_tag(tag)
        self.current_tag = tag

        available = self._list_available()
        match = self._select_best(tag, available)

        if match is None:
            self.translations = dict(DEFAULT_TRANSLATIONS)
            self.current_tag = DEFAULT_TAG
            print("[i18n] No strings-*.txt found, using built-in English.")
            return

        matched_tag, path = match
        data = self._load_file(matched_tag)
        if data is None:
            self.translations = dict(DEFAULT_TRANSLATIONS)
            self.current_tag = DEFAULT_TAG
            return

        merged = dict(DEFAULT_TRANSLATIONS)
        merged.update(data)
        self.translations = merged
        self.current_tag = matched_tag

        if matched_tag == tag:
            print(f"[i18n] Loaded exact match: {path.name}")
        else:
            print(f"[i18n] Loaded fallback: {path.name} (requested {tag})")

    def gettext(self, message_key, **kwargs):
        # First parameter renamed from 'key' to 'message_key' so that
        # callers can pass key=... as a format placeholder without
        # colliding with the positional argument.
        text = self.translations.get(message_key, message_key)
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


def _(message_key, **kwargs):
    # First parameter renamed from 'key' to 'message_key' to avoid
    # a conflict with the {key} format placeholder used by several
    # translation strings (e.g. rx.new_buffer, rx.appended_frame).
    return _i18n.gettext(message_key, **kwargs)


def current_tag():
    return _i18n.current_tag

# -----------------------------------------------------------------------------
# Models (from ft8_models.py)
# -----------------------------------------------------------------------------
class UTF8StreamDecoder:
    def __init__(self):
        self.buffer = bytearray()
        self.remain = bytearray()
        self.missing_count = 0

    def mark_missing(self, count):
        self.missing_count += count

    def _insert_missing(self):
        if self.missing_count == 0:
            return ""
        result = "�" * self.missing_count
        self.missing_count = 0
        return result

    def feed(self, data, is_missing=False):
        if is_missing:
            self.missing_count += 1
            return ""
        result = ""
        result += self._insert_missing()
        if self.remain:
            data = self.remain + data
            self.remain.clear()
        self.buffer.extend(data)
        while self.buffer:
            try:
                decoded = self.buffer.decode('utf-8')
                result += decoded
                self.buffer.clear()
            except UnicodeDecodeError as e:
                if e.start > 0:
                    result += self.buffer[:e.start].decode('utf-8')
                    self.buffer = self.buffer[e.start:]
                else:
                    self.remain.extend(self.buffer)
                    self.buffer.clear()
                    break
        return result

    def flush(self):
        result = ""
        result += self._insert_missing()
        if self.remain:
            result += "�" * len(self.remain)
            self.remain.clear()
        if self.buffer:
            result += self.buffer.decode('utf-8', errors='replace')
            self.buffer.clear()
        return result

    def clear(self):
        self.buffer.clear()
        self.remain.clear()
        self.missing_count = 0

class TransparentBuffer:
    def __init__(self, session_id, freq_key, freq, snr, delay_seconds,
                 on_complete, on_timeout, on_partial, time_func=None):
        self.session_id = session_id
        self.freq_key = freq_key
        self.freq = freq
        self.snr = snr
        self._time_func = time_func if time_func is not None else time.time
        self.start_time = self._time_func()
        self.last_update = self.start_time
        self.delay_seconds = delay_seconds
        self.timer = None
        self.blocks = []
        self.is_complete = False
        self.on_complete = on_complete
        self.on_timeout = on_timeout
        self.on_partial = on_partial
        self.streaming_text = ""
        self.last_partial_text = ""
        self.has_missing = False
        self.slot_start_time = None
        self._eot_found = False
        self._all_data = b''
        self.freq_sum = 0.0
        self.freq_count = 0
        self.first_freq = None
        self.last_frames_count = 0

    def set_slot_start_time(self, slot_start):
        if self.slot_start_time is None:
            self.slot_start_time = slot_start

    def append_block(self, data_block, freq, timestamp=None):
        self.blocks.append(data_block)
        self.last_update = timestamp if timestamp is not None else self._time_func()
        self._all_data = b''.join(self.blocks)
        self.freq_sum += freq
        self.freq_count += 1
        if self.first_freq is None:
            self.first_freq = freq
        self._try_finish()
        self._notify_partial()
        self._reset_timer()

    def _reset_timer(self):
        if self.timer:
            self.timer.cancel()

        def timeout_callback():
            self._on_timeout()
        self.timer = threading.Timer(self.delay_seconds, timeout_callback)
        self.timer.daemon = True
        self.timer.start()

    def _try_finish(self):
        if self.is_complete:
            return
        eot_pos = self._all_data.find(bytes([PROTOCOL_EOT_BYTE]))
        if eot_pos != -1:
            data_with_crc = self._all_data[:eot_pos]
            self._finish_with_eot(data_with_crc)

    def _finish_with_eot(self, data_with_crc):
        if len(data_with_crc) == 0:
            self._finish(b"", "No data", "No data")
            return
        raw_received = data_with_crc[:-1]
        crc_received = data_with_crc[-1]
        crc_calc = crc8(raw_received)
        if crc_calc == crc_received:
            status = "CRC OK"
            marker = "CRC OK"
            text_bytes = raw_received.rstrip(bytes([PROTOCOL_PAD_BYTE]))
        else:
            status = f"CRC fail (calc {crc_calc:02x}, recv {crc_received:02x})"
            marker = "CRC fail"
            text_bytes = raw_received
        try:
            text = text_bytes.decode('utf-8', errors='replace')
        except Exception:
            text = text_bytes.decode('latin-1', errors='replace')
        self._finish(text, status, marker)

    def _finish(self, text, status, marker=None):
        if self.is_complete:
            return
        self.is_complete = True
        if self.timer:
            self.timer.cancel()
            self.timer = None
        if marker is None:
            marker = f"[{status}]"
        self.on_complete(self, text, marker, status)

    def _on_timeout(self):
        if self.is_complete:
            return
        all_data = self._all_data
        try:
            text = all_data.decode('utf-8', errors='replace')
        except Exception:
            text = all_data.decode('latin-1', errors='replace')
        self.is_complete = True
        if self.timer:
            self.timer.cancel()
            self.timer = None
        self.on_timeout(self, text)

    def _notify_partial(self):
        if self.on_partial and not self.is_complete:
            all_data = self._all_data
            eot_pos = all_data.find(bytes([PROTOCOL_EOT_BYTE]))
            data = all_data[:eot_pos] if eot_pos != -1 else all_data
            try:
                text = data.decode('utf-8', errors='replace')
            except Exception:
                text = data.decode('latin-1', errors='replace')
            self.streaming_text = text
            current_text = text[:200]
            frames_count = len(self.blocks)
            if current_text != self.last_partial_text or frames_count != self.last_frames_count:
                self.last_partial_text = current_text
                self.last_frames_count = frames_count
                self.on_partial(
                    freq=self.freq, snr=self.snr,
                    frames_count=frames_count,
                    text=text,
                    slot_start_time=self.slot_start_time,
                    freq_key=self.freq_key,
                    session_id=self.session_id
                )

    def get_frames_count(self):
        return len(self.blocks)

    def cancel_timer(self):
        if self.timer:
            self.timer.cancel()
            self.timer = None

    @property
    def avg_freq(self):
        if self.freq_count == 0:
            return None
        return self.freq_sum / self.freq_count

class HistoryEntry:
    def __init__(self, direction, timestamp, freq, snr, frames_count,
                 total_bytes, text, marker, is_complete=True, slot_progress=None,
                 is_partial=False, session_id=None, crc_status=None,
                 source_callsign=None, target_callsign=None,
                 i3=None, f2=None, total_frames=None, total_bytes_all=None,
                 is_self_targeted=False, contact_note=None):
        self.direction = direction
        self.timestamp = timestamp
        self.freq = freq
        self.snr = snr
        self.frames_count = frames_count
        self.total_bytes = total_bytes
        self.text = text
        self.marker = marker
        self.is_complete = is_complete
        self.slot_progress = slot_progress
        self.is_partial = is_partial
        self.session_id = session_id
        self.crc_status = crc_status
        self.source_callsign = source_callsign
        self.target_callsign = target_callsign
        self.i3 = i3
        # f2 is the 2-bit format identifier from the FT8 payload.
        # For receive-side transparent frames, f2=1 means a
        # continuous-frame session, f2=0 means a single frame.
        self.f2 = f2
        self.total_frames = total_frames
        self.total_bytes_all = total_bytes_all
        self.is_self_targeted = is_self_targeted
        self.contact_note = contact_note

# -----------------------------------------------------------------------------
# CustomAudioOut (from ft8_audio_out.py)
# -----------------------------------------------------------------------------
class CustomAudioOut(AudioOut):
    def __init__(self):
        super().__init__()
        self._pyaudio = None
        self.stop_flag = False

    def _get_pyaudio(self):
        if self._pyaudio is None:
            self._pyaudio = pyaudio.PyAudio()
        return self._pyaudio

    def clear_stop_flag(self):
        self.stop_flag = False
        if hasattr(super(), 'clear_stop_flag'):
            super().clear_stop_flag()

    def request_stop(self):
        self.stop_flag = True
        if hasattr(super(), 'request_stop'):
            super().request_stop()

    def play_white_noise(self, duration_seconds, sample_rate=12000, amplitude=0.5):
        self.clear_stop_flag()
        if self.stop_flag:
            return False
        try:
            num_samples = int(duration_seconds * sample_rate)
            noise = np.random.normal(0, amplitude, num_samples).astype(np.float32)
            noise = np.clip(noise, -1.0, 1.0)
            audio_int16 = (noise * 32767).astype(np.int16)
            p = self._get_pyaudio()
            stream = p.open(format=pyaudio.paInt16,
                            channels=1, rate=sample_rate,
                            output=True, frames_per_buffer=1024)
            chunk_size = 1024
            for i in range(0, len(audio_int16), chunk_size):
                if self.stop_flag:
                    break
                chunk = audio_int16[i:i + chunk_size]
                stream.write(chunk.tobytes())
            stream.stop_stream()
            stream.close()
            if self.stop_flag:
                return False
            return True
        except Exception as e:
            print(_("audio.noise_error", e=e))
            import traceback
            traceback.print_exc()
            return False

    def shutdown(self):
        if self._pyaudio is not None:
            self._pyaudio.terminate()
            self._pyaudio = None

# -----------------------------------------------------------------------------
# Core base (from core_base.py)
# -----------------------------------------------------------------------------
class StdoutRedirector:
    def __init__(self, callback, is_stderr=False):
        self.callback = callback
        self.is_stderr = is_stderr
        self._buffer = ""

    def write(self, text):
        if not text:
            return
        self._buffer += text
        if '\n' in self._buffer:
            lines = self._buffer.split('\n')
            self._buffer = lines[-1]
            for line in lines[:-1]:
                if line.strip():
                    tag = "error" if self.is_stderr else "info"
                    self.callback(line.strip(), tag)

    def flush(self):
        if self._buffer.strip():
            tag = "error" if self.is_stderr else "info"
            self.callback(self._buffer.strip(), tag)
            self._buffer = ""

class CoreBase:
    def __init__(self):
        self._original_stdout = sys.stdout
        self._original_stderr = sys.stderr

        self.is_running = False
        self.receiver = None
        self.audio_in = None
        self.audio_out = CustomAudioOut()
        self.is_transmitting = False
        self.transmit_thread = None
        self.receive_paused = False
        self.stop_requested = False
        self.transparent_buffers = {}
        self.buffers_lock = threading.Lock()
        self.next_session_id = 1
        self.current_send_session_id = None

        # Beacon state
        self.beacon_active = False
        self.beacon_thread = None
        self.beacon_stop_requested = False
        self._beacon_tx_done_event = threading.Event()
        self.beacon_text = ""
        self.beacon_freq = 1500

        self.config_file = str(BASE_DIR / "config.txt")
        self.callsign = ""
        self.tx_freq = 1500
        self.preamble_noise_enabled = False

        self.max_raw_data_bytes = MAX_RAW_DATA_BYTES
        self.max_total_bytes = MAX_TOTAL_BYTES
        self.max_frames = MAX_FRAMES
        self.fixed_max_history = FIXED_MAX_HISTORY
        self.fixed_max_messages = FIXED_MAX_MESSAGES
        self.fixed_freq_start = FIXED_FREQ_START
        self.fixed_freq_end = FIXED_FREQ_END
        self.delay_slots = FIXED_DELAY_SLOTS
        self.delay_seconds = FIXED_DELAY_SECONDS
        self.max_active_buffers = MAX_ACTIVE_BUFFERS
        self.cycle_seconds = 15

        self.history_entries = []
        self.max_history = FIXED_MAX_HISTORY

        self._callbacks = {
            'on_log': None,
            'on_history': None,
            'on_status': None,
            'on_tx_task': None,
            'on_buffer_count': None,
            'on_tx_progress': None,
            'on_slot_update': None,
            'on_time_display': None,
            'on_contact_updated': None,
            'on_toast': None,
            'on_beacon_fill': None,
            'on_beacon_clear': None,
            'on_beacon_state': None,
            'on_beacon_tx_request': None,
        }

        self._history_lock = threading.Lock()

        self.contact_file = str(BASE_DIR / "contact.txt")
        self.contact_list = []
        self._load_contacts()

        self.load_config()

        self._stdout_redirector = StdoutRedirector(self._redirect_print, is_stderr=False)
        self._stderr_redirector = StdoutRedirector(self._redirect_print, is_stderr=True)
        sys.stdout = self._stdout_redirector
        sys.stderr = self._stderr_redirector

        self._time_offset = 0.0
        self._ntp_synced = False

    def _redirect_print(self, msg, tag):
        if msg.startswith('[Audio]') or 'Using default output device' in msg:
            return
        self._safe_call('on_log', msg, tag)

    def set_callbacks(self, **kwargs):
        for key, func in kwargs.items():
            if key in self._callbacks:
                self._callbacks[key] = func

    def _safe_call(self, key, *args, **kwargs):
        func = self._callbacks.get(key)
        if func:
            func(*args, **kwargs)

    def _interruptible_sleep(self, seconds, check_interval=0.1):
        elapsed = 0
        while elapsed < seconds and not self.stop_requested and not self.beacon_stop_requested:
            time.sleep(min(check_interval, seconds - elapsed))
            elapsed += check_interval
        return not self.stop_requested and not self.beacon_stop_requested

    def _get_next_slot(self, t):
        cycle = self.cycle_seconds
        return int(t // cycle) * cycle + cycle

    def get_wait_time_for_next_slot_start(self):
        t = self.get_corrected_timestamp()
        cycle = self.cycle_seconds
        wait = cycle - (t % cycle)
        if wait < 0.01:
            wait = cycle
        return wait

    def shutdown(self):
        sys.stdout = self._original_stdout
        sys.stderr = self._original_stderr
        self.stop_beacon()
        self.stop_transmit()
        self.stop_receiver()
        self.save_config()
        if hasattr(self.audio_out, 'shutdown'):
            self.audio_out.shutdown()

# -----------------------------------------------------------------------------
# Time mixin (from core_time.py)
# -----------------------------------------------------------------------------
class TimeMixin:
    def start_ntp_sync(self):
        if self._ntp_synced:
            return
        threading.Thread(target=self._sync_ntp, daemon=True).start()

    def _sync_ntp(self):
        if not _NTP_AVAILABLE:
            self._safe_call('on_log', _("ntp.missing"), "warning")
            self._safe_call('on_toast', _("ntp.missing_toast"), "warning")
            return

        servers = ['cn.pool.ntp.org', 'pool.ntp.org']
        for server in servers:
            try:
                client = ntplib.NTPClient()
                response = client.request(server, version=3, timeout=3)
                ntp_timestamp = response.tx_time
                system_timestamp = time.time()
                offset = ntp_timestamp - system_timestamp
                self._time_offset = offset
                self._ntp_synced = True
                self._safe_call('on_log',
                                _("ntp.ok",
                                  server=server, offset=offset),
                                "info")
                self._safe_call('on_toast',
                                _("ntp.calibrated", offset=offset),
                                "info")
                return
            except Exception as e:
                self._safe_call('on_log',
                                _("ntp.fail", server=server, e=e),
                                "warning")
        self._time_offset = 0.0
        self._safe_call('on_log', _("ntp.fail_all"), "warning")

    def get_corrected_timestamp(self):
        return time.time() + self._time_offset

    def get_corrected_utc_now(self):
        return self.utc_from_corrected_ts(self.get_corrected_timestamp())

    def utc_from_corrected_ts(self, corrected_ts):
        return datetime.utcfromtimestamp(corrected_ts)

# -----------------------------------------------------------------------------
# Config mixin (from core_config.py)
# -----------------------------------------------------------------------------
class ConfigMixin:
    def load_config(self):
        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                config = json.load(f)
            raw_callsign = config.get('callsign', '').strip().upper()
            if is_valid_callsign(raw_callsign):
                self.callsign = raw_callsign
            else:
                self.callsign = ""
                self._safe_call('on_log',
                                _("cfg.callsign_invalid", callsign=raw_callsign),
                                "warning")
                self._safe_call('on_toast', _("cfg.callsign_invalid_toast"), "warning")
            tx_freq = config.get('tx_freq', '1500')
            try:
                val = int(float(tx_freq))
                if 300 <= val <= 3000:
                    self.tx_freq = val
            except Exception:
                pass
            self.preamble_noise_enabled = config.get('preamble_noise', False)
            self._safe_call('on_log', _("cfg.loaded"), "info")
        except Exception as e:
            self._safe_call('on_log',
                            _("cfg.load_failed", e=e),
                            "error")
            self._safe_call('on_toast', _("cfg.load_failed_toast"), "error")
            self._apply_defaults()

    def save_config(self):
        if self.callsign and not is_valid_callsign(self.callsign):
            self._safe_call('on_log', _("cfg.callsign_save_blocked"), "warning")
            self._safe_call('on_toast', _("cfg.callsign_save_ignored"), "warning")
            return
        config = {
            'callsign': self.callsign,
            'tx_freq': str(self.tx_freq),
            'preamble_noise': self.preamble_noise_enabled,
        }
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(_("cfg.save_error", e=e))
            self._safe_call('on_toast', _("cfg.save_failed", e=e), "error")

    def _apply_defaults(self):
        self.callsign = ""
        self.tx_freq = 1500
        self.preamble_noise_enabled = False

    def set_preamble_noise(self, value):
        self.preamble_noise_enabled = value
        self.save_config()
        state = _("cfg.state_enabled") if value else _("cfg.state_disabled")
        self._safe_call('on_log', _("cfg.preamble_state", state=state), "info")
        self._safe_call('on_toast', _("cfg.preamble_state", state=state), "info")

# -----------------------------------------------------------------------------
# Receiver mixin (from core_receiver.py)
# -----------------------------------------------------------------------------
class ReceiverMixin:
    def start_receiver(self):
        try:
            freq_start = self.fixed_freq_start
            freq_end = self.fixed_freq_end
            if freq_start >= freq_end:
                self._safe_call('on_log', _("rcv.freq_error"), "error")
                self._safe_call('on_toast', _("rcv.freq_range_error"), "error")
                return
            freq_range = (freq_start, freq_end)
            self._safe_call('on_log',
                            _("rcv.starting",
                              start=freq_start, end=freq_end),
                            "info")
            self.audio_in = AudioIn(max_freq=freq_end, wav_files=None)
            self.audio_in.start_streamed_audio(None)
            self._safe_call('on_log', _("rcv.audio_started"), "info")
            self.receiver = Receiver(
                audio_in=self.audio_in, freq_range=freq_range,
                on_decode=self.on_decode, on_busy_profile=self.on_busy_profile, verbose=False
            )
            self.is_running = True
            self.receive_paused = False
            self._safe_call('on_status', False)
            self._safe_call('on_log', _("rcv.started"), "info")
            self._safe_call('on_log',
                            _("rcv.merge_delay",
                              n=self.delay_slots, s=self.delay_seconds),
                            "info")
            self._safe_call('on_log',
                            _("rcv.unicode_hint"),
                            "info")
            self._safe_call('on_log',
                            _("rcv.max_hint",
                              n=self.max_raw_data_bytes, m=self.max_frames),
                            "info")
            self._safe_call('on_log',
                            _("rcv.filter_hint"),
                            "info")
            self._safe_call('on_log',
                            _("rcv.group_hint"),
                            "info")
            self._safe_call('on_log',
                            _("rcv.auto_mode_hint"),
                            "info")
        except Exception as e:
            self._safe_call('on_log', _("rcv.start_error", e=e), "error")
            self._safe_call('on_toast', _("rcv.start_failed", e=e), "error")
            print(_("rcv.start_error", e=e))

    def stop_receiver(self):
        self._safe_call('on_log', _("rcv.stopping"), "info")
        self.stop_beacon()
        self.stop_transmit()
        with self.buffers_lock:
            for buf in self.transparent_buffers.values():
                buf.cancel_timer()
            self.transparent_buffers.clear()
        self.is_running = False
        self.receive_paused = False
        self._safe_call('on_status', False)
        try:
            if self.audio_in and hasattr(self.audio_in, 'stream'):
                self.audio_in.stream.stop_stream()
                self.audio_in.stream.close()
                self._safe_call('on_log', _("rcv.audio_stopped"), "info")
            if self.audio_in and hasattr(self.audio_in, 'close'):
                self.audio_in.close()
        except Exception as e:
            self._safe_call('on_log', _("rcv.stop_error", e=e), "error")
            self._safe_call('on_toast', _("rcv.stop_error", e=e), "error")
        self.receiver = None
        self.audio_in = None
        self._safe_call('on_log', _("rcv.stopped"), "info")

    def on_busy_profile(self, bp, cycle):
        pass

    def pause_receiver(self):
        if self.receive_paused:
            return
        self.receive_paused = True
        self._safe_call('on_log', _("hd.pause"), "halfduplex")
        self._safe_call('on_status', True)
        if self.audio_in and hasattr(self.audio_in, 'stream'):
            try:
                if self.audio_in.stream.is_active():
                    try:
                        while True:
                            available = self.audio_in.stream.get_read_available()
                            if available == 0:
                                break
                            self.audio_in.stream.read(available, exception_on_overflow=False)
                    except Exception as e:
                        self._safe_call('on_log',
                                        _("hd.pause_clear_warn", e=e),
                                        "warning")
                    self.audio_in.stream.stop_stream()
                    self._safe_call('on_log', _("hd.paused"), "halfduplex")
            except Exception as e:
                self._safe_call('on_log', _("hd.pause_error", e=e), "error")
                self._safe_call('on_toast', _("hd.pause_error", e=e), "error")

    def resume_receiver(self):
        if not self.receive_paused:
            return
        if self.audio_in and hasattr(self.audio_in, 'stream'):
            try:
                if not self.audio_in.stream.is_active():
                    self.audio_in.stream.start_stream()
                    try:
                        time.sleep(0.05)
                        while True:
                            available = self.audio_in.stream.get_read_available()
                            if available == 0:
                                break
                            self.audio_in.stream.read(available, exception_on_overflow=False)
                    except Exception as e:
                        self._safe_call('on_log',
                                        _("hd.resume_clear_warn", e=e),
                                        "warning")
                    self.audio_in.sync_pointer_to_wall_clock()
                    self._safe_call('on_log', _("hd.resumed"), "halfduplex")
            except Exception as e:
                self._safe_call('on_log', _("hd.resume_error", e=e), "error")
                self._safe_call('on_toast', _("hd.resume_error", e=e), "error")
        self.receive_paused = False
        self._safe_call('on_log', _("hd.resume"), "halfduplex")
        self._safe_call('on_status', False)

# -----------------------------------------------------------------------------
# Beacon mixin (from core_beacon.py)
# -----------------------------------------------------------------------------
class BeaconMixin:
    def start_beacon(self, text, freq):
        if self.beacon_active:
            return
        self.beacon_active = True
        self.beacon_stop_requested = False
        self.stop_requested = False
        self.beacon_text = text
        self.beacon_freq = freq
        self.beacon_thread = threading.Thread(target=self._beacon_worker, daemon=True)
        self.beacon_thread.start()
        self._safe_call('on_log', _("beacon.started", text=text), "info")
        self._safe_call('on_toast', _("beacon.started_toast"), "info")
        self._safe_call('on_beacon_state', True)

    def stop_beacon(self):
        if not self.beacon_active:
            return
        self.beacon_active = False
        self.beacon_stop_requested = True
        self._safe_call('on_beacon_state', False)

        if self.is_transmitting:
            self.stop_transmit()
        if self.beacon_thread and self.beacon_thread.is_alive():
            self.beacon_thread.join(timeout=5.0)
        self.beacon_thread = None
        self.beacon_stop_requested = False

        self._safe_call('on_log', _("beacon.stopped"), "info")
        self._safe_call('on_toast', _("beacon.stopped"), "info")

    def _beacon_worker(self):
        cycle = self.cycle_seconds
        t = self.get_corrected_timestamp()
        next_slot = int(t // cycle) * cycle + cycle

        try:
            while not self.beacon_stop_requested and not self.stop_requested:
                wake_time = next_slot - 1.0 if self.preamble_noise_enabled else next_slot
                wait = wake_time - self.get_corrected_timestamp()
                if wait > 0:
                    if not self._interruptible_sleep(wait):
                        break
                if self.beacon_stop_requested or self.stop_requested:
                    break

                self._beacon_tx_done_event.clear()
                self._safe_call('on_beacon_tx_request', self.beacon_text, self.beacon_freq, next_slot)
                while not self._beacon_tx_done_event.wait(timeout=0.1):
                    if self.beacon_stop_requested or self.stop_requested:
                        break
                if self.beacon_stop_requested or self.stop_requested:
                    break

                next_slot += 16 * cycle
        except Exception as e:
            self._safe_call('on_log', _("beacon.error", e=e), "error")
        finally:
            self.beacon_active = False
            self.beacon_thread = None
            self.beacon_stop_requested = False
            self._safe_call('on_beacon_state', False)

# -----------------------------------------------------------------------------
# TX mixin (from core_tx.py)
# -----------------------------------------------------------------------------
class TxMixin:
    def transmit_text(self, text, freq, start_slot=None):
        if self.is_transmitting:
            self._safe_call('on_log', _("tx.busy"), "error")
            self._safe_call('on_toast', _("tx.busy"), "warning")
            return
        if not self.is_running:
            self._safe_call('on_log', _("tx.need_rx"), "error")
            self._safe_call('on_toast', _("tx.need_rx"), "warning")
            return
        self.is_transmitting = True
        self.stop_requested = False
        self._safe_call('on_tx_task', True)
        threading.Thread(target=self._transmit_worker,
                         args=(text, freq, start_slot), daemon=True).start()

    def _transmit_worker(self, text, freq, start_slot=None):
        try:
            if not text.strip():
                raise ValueError(_("tx.empty"))
            filtered = []
            for ch in text:
                code = ord(ch)
                if ch in ('\t', '\r', '\n') or (32 <= code <= 126) or code >= 0x80:
                    filtered.append(ch)
            filtered_str = ''.join(filtered)
            if not filtered_str:
                raise ValueError(_("tx.non_printable"))

            if is_free_text_compatible(filtered_str):
                self._send_free_text(filtered_str, freq, start_slot=start_slot)
                return

            raw_data = filtered_str.encode('utf-8')
            raw_len = len(raw_data)
            if raw_len > self.max_raw_data_bytes:
                raise ValueError(_("tx.too_long_bytes",
                                   n=raw_len, max=self.max_raw_data_bytes))

            if raw_len <= 9:
                frame_data = raw_data.ljust(9, bytes([PROTOCOL_PAD_BYTE]))
                frames = [(0, frame_data)]
                total_frames = 1
            else:
                min_payload_len = raw_len + 2
                total_len = 9 * ((min_payload_len + 8) // 9)
                padding_len = total_len - raw_len - 2
                payload_with_padding = raw_data + bytes([PROTOCOL_PAD_BYTE]) * padding_len
                crc_val = crc8(payload_with_padding)
                payload = payload_with_padding + bytes([crc_val]) + bytes([PROTOCOL_EOT_BYTE])
                blocks = [payload[i:i+9] for i in range(0, len(payload), 9)]
                if len(blocks) > self.max_frames:
                    raise ValueError(_("tx.too_many_frames",
                                       n=len(blocks), max=self.max_frames))
                frames = [(1, d9) for d9 in blocks]
                total_frames = len(frames)

            display_text = filtered_str

            self._safe_call('on_log',
                            _("tx.split_frames", n=total_frames),
                            "info")
            self._safe_call('on_log',
                            _("tx.data_content", text=display_text[:100] + ('...' if len(display_text) > 100 else '')),
                            "info")
            if total_frames == 1:
                self._safe_call('on_log', _("tx.single_mode"), "info")
            else:
                self._safe_call('on_log', _("tx.multi_mode"), "info")
                self._safe_call('on_log', _("tx.payload_formula"), "info")

            self._transmit_frames(frames, freq, total_frames, display_text, raw_data,
                                  start_slot=start_slot)

        except Exception as e:
            msg = _("tx.prep_failed", e=e)
            self._safe_call('on_log', msg, "error")
            self._safe_call('on_toast', msg, "error")
            try:
                fail_session_id = f"send_fail_prep_{int(self.get_corrected_timestamp()*1000)}"
                self._add_send_history_realtime(
                    freq=freq,
                    frames_count=0,
                    total_frames=1,
                    text=text if text else "(empty)",
                    marker=_("tx.failed"),
                    slot_progress="0/1",
                    is_partial=False,
                    session_id=fail_session_id,
                    timestamp=self.get_corrected_utc_now(),
                    total_bytes_all=len(text.encode('utf-8')) if text else 0
                )
            except Exception as ex:
                self._safe_call('on_log',
                                _("tx.history_error", e=ex),
                                "error")
            self._cleanup_tx()

    def _send_free_text(self, text, freq, start_slot=None):
        text = text.upper()
        session_id = f"free_send_{int(time.time()*1000)}"
        raw_data = text.encode('utf-8')
        total_bytes_all = len(raw_data)

        is_beacon = bool(BEACON_PATTERN.match(text.strip())) if text else False
        free_text_marker = MARKER_BEACON if is_beacon else MARKER_FREE_TEXT

        self._safe_call('on_log', _("tx.free_text", text=text), "info")
        symbols, bits77 = pack_free_text(text)
        ft8_data = self.audio_out.create_ft8_wave(symbols, fs=12000, f_base=freq, f_step=6.25, amplitude=1.0)
        self.audio_out.clear_stop_flag()

        if start_slot is not None:
            next_slot = start_slot
        else:
            t_now = self.get_corrected_timestamp()
            next_slot = self._get_next_slot(t_now)
            wait_time = next_slot - t_now
            if wait_time > 0:
                self._safe_call('on_log', _("tx.waiting_slot", t=f"{wait_time:.1f}"), "info")
                if not self._interruptible_sleep(wait_time):
                    self._safe_call('on_log', _("tx.stopped_by_user"), "info")
                    self._safe_call('on_toast', _("tx.cancelled"), "info")
                    return

        if self.preamble_noise_enabled:
            noise_start = next_slot - 1.0
            now = self.get_corrected_timestamp()
            if now < noise_start:
                if not self._interruptible_sleep(noise_start - now):
                    return
            self.pause_receiver()
            if not self.audio_out.play_white_noise(0.5):
                self._safe_call('on_log', _("tx.noise_failed"), "error")
                self._safe_call('on_toast', _("tx.noise_failed"), "error")
                self.resume_receiver()
                return
            if not self._interruptible_sleep(0.5):
                self.resume_receiver()
                return
        else:
            now = self.get_corrected_timestamp()
            if now < next_slot:
                if not self._interruptible_sleep(next_slot - now):
                    return
            self.pause_receiver()

        try:
            slot_start_dt = self.utc_from_corrected_ts(next_slot)
            self._safe_call('on_log',
                            f"[{slot_start_dt.strftime('%Y-%m-%d %H:%M:%S')}] " + _("tx.start_free"),
                            "tx")

            self._add_send_history_realtime(
                freq=freq,
                frames_count=0,
                total_frames=1,
                text=text,
                marker=free_text_marker,
                slot_progress="0/1",
                is_partial=True,
                session_id=session_id,
                timestamp=slot_start_dt,
                total_bytes_all=total_bytes_all
            )

            success = self.audio_out.play_ft8_only(ft8_data, None)
            if success:
                self._safe_call('on_log', _("tx.free_ok"), "info")
                self._safe_call('on_toast', _("tx.free_ok"), "info")
                self._add_send_history_realtime(
                    freq=freq,
                    frames_count=1,
                    total_frames=1,
                    text=text,
                    marker=free_text_marker,
                    slot_progress="1/1",
                    is_partial=False,
                    session_id=session_id,
                    timestamp=slot_start_dt,
                    total_bytes_all=total_bytes_all
                )
            elif self.stop_requested:
                self._safe_call('on_log', _("tx.stopped_by_user"), "info")
                self._safe_call('on_toast', _("tx.stopped"), "warning")
                self._add_send_history_realtime(
                    freq=freq,
                    frames_count=0,
                    total_frames=1,
                    text=text,
                    marker=MARKER_INTERRUPT,
                    slot_progress="0/1",
                    is_partial=False,
                    session_id=session_id,
                    timestamp=slot_start_dt,
                    total_bytes_all=total_bytes_all
                )
            else:
                self._safe_call('on_log', _("tx.free_failed"), "error")
                self._safe_call('on_toast', _("tx.free_failed"), "error")
                self._add_send_history_realtime(
                    freq=freq,
                    frames_count=0,
                    total_frames=1,
                    text=text,
                    marker=_("tx.failed"),
                    slot_progress="0/1",
                    is_partial=False,
                    session_id=session_id,
                    timestamp=slot_start_dt,
                    total_bytes_all=total_bytes_all
                )
        except Exception as e:
            self._safe_call('on_log', _("tx.free_exception", e=e), "error")
            self._safe_call('on_toast', _("tx.free_exception", e=e), "error")
            self._add_send_history_realtime(
                freq=freq,
                frames_count=0,
                total_frames=1,
                text=text,
                marker=_("tx.failed"),
                slot_progress="0/1",
                is_partial=False,
                session_id=session_id,
                timestamp=self.get_corrected_utc_now(),
                total_bytes_all=total_bytes_all
            )
            raise
        finally:
            t_now = self.get_corrected_timestamp()
            next_slot_after = self._get_next_slot(t_now)
            wait_time = next_slot_after - t_now
            if wait_time > 0.1:
                self._safe_call('on_log',
                                _("tx.wait_next_slot",
                                  t=f"{wait_time:.1f}"),
                                "info")
                self._interruptible_sleep(wait_time)
            self.resume_receiver()
            self.is_transmitting = False
            self.current_send_session_id = None
            self._safe_call('on_tx_task', False)

    def _transmit_frames(self, frames, freq, total_frames, display_text, raw_data, start_slot=None):
        tx_freq = freq
        send_session_id = f"send_{tx_freq}_{int(self.get_corrected_timestamp()*1000)}"
        history_initialized = False
        # Match the RX byte-count convention: include 0x20 padding but
        # exclude the CRC and EOT trailer bytes for continuous frames.
        # Single-frame payloads (f2=0) have no CRC/EOT, so the raw
        # length is used as-is.
        if total_frames > 1:
            total_bytes_all = total_frames * 9 - 2
        else:
            total_bytes_all = len(raw_data)

        is_beacon = bool(BEACON_PATTERN.match(display_text.strip())) if display_text else False

        self._safe_call('on_tx_progress',
                        _("tx.waiting_total", n=total_frames))

        if is_beacon:
            progress_marker = MARKER_BEACON
        elif total_frames == 1:
            progress_marker = MARKER_SINGLE
        else:
            progress_marker = "[Sending]"

        sent_frames_count = 0
        slot_progress = "0/0"
        tx_failed = False

        try:
            if start_slot is not None:
                first_slot = start_slot
            else:
                first_slot = self._get_next_slot(self.get_corrected_timestamp())

            for frame_idx, (f2, frame_data) in enumerate(frames):
                if self.stop_requested:
                    break

                expected_time = first_slot + frame_idx * 15

                if self.preamble_noise_enabled:
                    noise_start = expected_time - 1.0
                    now = self.get_corrected_timestamp()
                    if now < noise_start:
                        if not self._interruptible_sleep(noise_start - now):
                            break
                    if not self.receive_paused:
                        self.pause_receiver()
                    if not self.audio_out.play_white_noise(0.5):
                        self._safe_call('on_log', _("White noise playback failed, TX terminated"), "error")
                        self._safe_call('on_toast', _("White noise playback failed, TX terminated"), "error")
                        tx_failed = True
                        break
                    if not self._interruptible_sleep(0.5):
                        break
                else:
                    now = self.get_corrected_timestamp()
                    if now < expected_time:
                        if not self._interruptible_sleep(expected_time - now):
                            break
                    if not self.receive_paused:
                        self.pause_receiver()

                current_b72 = int.from_bytes(frame_data, byteorder='big')
                frame_num = sent_frames_count + 1
                tx_log = (f"[TX] i3:6 {tx_freq:.0f}Hz | "
                          f"f2={f2}  frame={frame_num}/{total_frames}  "
                          f"b72=0x{current_b72:018x}")
                slot_start_dt = self.utc_from_corrected_ts(expected_time)
                self._safe_call('on_log',
                                f"[{slot_start_dt.strftime('%Y-%m-%d %H:%M:%S')}] {tx_log}",
                                "tx")

                if not history_initialized:
                    initial_marker = progress_marker
                    initial_progress = f"0/{total_frames}"
                    self._add_send_history_realtime(
                        freq=tx_freq,
                        frames_count=0,
                        total_frames=total_frames,
                        text="",
                        marker=initial_marker,
                        slot_progress=initial_progress,
                        is_partial=True,
                        session_id=send_session_id,
                        timestamp=slot_start_dt,
                        total_bytes_all=total_bytes_all
                    )
                    history_initialized = True

                current_text = raw_data[:min(frame_num * 9, len(raw_data))].decode('utf-8', errors='replace')
                marker = progress_marker
                slot_progress = f"{frame_num}/{total_frames}"
                self._add_send_history_realtime(
                    freq=tx_freq,
                    frames_count=frame_num,
                    total_frames=total_frames,
                    text=current_text,
                    marker=marker,
                    slot_progress=slot_progress,
                    is_partial=True,
                    session_id=send_session_id,
                    timestamp=slot_start_dt,
                    total_bytes_all=total_bytes_all
                )

                success = self.transmit_single_frame(f2, frame_data, tx_freq)
                if not success:
                    self._safe_call('on_log', _("tx.frame_failed"), "error")
                    self._safe_call('on_toast', _("tx.frame_aborted"), "error")
                    tx_failed = True
                    break
                sent_frames_count += 1
                if self.stop_requested:
                    break

            if not self.stop_requested:
                last_frame_slot = first_slot + (total_frames - 1) * 15
                t = self.get_corrected_timestamp()
                wait_time = last_frame_slot + 15 - t
                if wait_time > 0.1:
                    self._safe_call('on_log',
                                    _("tx.wait_slot_end",
                                      t=f"{wait_time:.1f}"),
                                    "info")
                    self._interruptible_sleep(wait_time)
                self.resume_receiver()
                self._safe_call('on_log', _("tx.switched_rx"), "info")

            is_complete = (sent_frames_count == total_frames) and not self.stop_requested and not tx_failed
            if is_complete:
                if is_beacon:
                    final_marker = MARKER_BEACON
                elif total_frames == 1:
                    final_marker = MARKER_SINGLE
                else:
                    final_marker = "[Sent]"
                final_progress = f"{total_frames}/{total_frames}"
                final_timestamp = self.utc_from_corrected_ts(first_slot + (total_frames - 1) * 15) if total_frames > 0 else self.get_corrected_utc_now()
                self._add_send_history_realtime(
                    freq=tx_freq,
                    frames_count=total_frames,
                    total_frames=total_frames,
                    text=display_text,
                    marker=final_marker,
                    slot_progress=final_progress,
                    is_partial=False,
                    session_id=send_session_id,
                    timestamp=final_timestamp,
                    total_bytes_all=total_bytes_all
                )
                self._safe_call('on_tx_progress',
                                _("tx.complete_frames", n=total_frames, m=total_frames))
                self._safe_call('on_toast',
                                _("tx.complete_frames", n=total_frames, m=total_frames),
                                "info")
            else:
                if tx_failed:
                    final_marker = _("tx.failed")
                    shown_frames = max(sent_frames_count, 1)
                    current_text = raw_data[:min(shown_frames * 9, len(raw_data))].decode('utf-8', errors='replace')
                    final_text = current_text
                    final_slot_progress = f"{sent_frames_count}/{total_frames}"
                else:
                    final_marker = MARKER_INTERRUPT
                    current_text = raw_data[:min(sent_frames_count * 9, len(raw_data))].decode('utf-8', errors='replace')
                    final_text = current_text + " " + _("suffix_tx_interrupted")
                    final_slot_progress = slot_progress

                self._add_send_history_realtime(
                    freq=tx_freq,
                    frames_count=sent_frames_count,
                    total_frames=total_frames,
                    text=final_text,
                    marker=final_marker,
                    slot_progress=final_slot_progress,
                    is_partial=False,
                    session_id=send_session_id,
                    timestamp=self.get_corrected_utc_now(),
                    total_bytes_all=total_bytes_all
                )
                if tx_failed:
                    self._safe_call('on_tx_progress',
                                    _("tx.failed_frames", n=sent_frames_count, m=total_frames))
                    self._safe_call('on_toast',
                                    _("tx.failed_frames", n=sent_frames_count, m=total_frames),
                                    "error")
                else:
                    self._safe_call('on_tx_progress',
                                    _("tx.interrupted_frames", n=sent_frames_count, m=total_frames))
                    self._safe_call('on_toast',
                                    _("tx.interrupted_frames", n=sent_frames_count, m=total_frames),
                                    "warning")

        except Exception as e:
            self._safe_call('on_log', _("tx.error", e=e), "error")
            self._safe_call('on_toast', _("tx.error", e=e), "error")
            import traceback
            traceback.print_exc()
            try:
                self._add_send_history_realtime(
                    freq=tx_freq,
                    frames_count=sent_frames_count,
                    total_frames=total_frames,
                    text=display_text,
                    marker=_("tx.failed"),
                    slot_progress=f"{sent_frames_count}/{total_frames}",
                    is_partial=False,
                    session_id=send_session_id,
                    timestamp=self.get_corrected_utc_now(),
                    total_bytes_all=total_bytes_all
                )
            except Exception as ex:
                self._safe_call('on_log',
                                _("tx.history_error", e=ex),
                                "error")
        finally:
            if self.receive_paused:
                self.resume_receiver()
            self._cleanup_tx()

    def _cleanup_tx(self):
        self.audio_out.request_stop()
        time.sleep(0.1)
        if self.receive_paused:
            self.resume_receiver()
        self.is_transmitting = False
        self.current_send_session_id = None
        self._safe_call('on_tx_task', False)

    def stop_transmit(self):
        if not self.is_transmitting:
            return
        self._safe_call('on_log', _("tx.stopping"), "info")
        self.stop_requested = True
        self.audio_out.request_stop()
        if self.transmit_thread and self.transmit_thread.is_alive():
            self.transmit_thread.join(timeout=2.0)
        self.is_transmitting = False
        self.current_send_session_id = None
        if self.receive_paused:
            self.resume_receiver()
        self._safe_call('on_tx_task', False)
        self._safe_call('on_log', _("tx.stopped"), "info")
        self._safe_call('on_toast', _("tx.stopped"), "info")

    def transmit_single_frame(self, f2, frame_data, tx_freq_hz):
        b72 = int.from_bytes(frame_data, 'big')
        d74 = (f2 << 72) | b72
        f2_temp = (d74 >> 72) & 0x3
        b72_temp = d74 & ((1 << 72) - 1)
        symbols, _unused = pack_transparent_message(f2_temp, b72_temp)
        ft8_data = self.audio_out.create_ft8_wave(symbols, fs=12000, f_base=tx_freq_hz, f_step=6.25, amplitude=1.0)
        self.audio_out.clear_stop_flag()
        return self.audio_out.play_ft8_only(ft8_data, None)

# -----------------------------------------------------------------------------
# RX mixin (from core_rx.py)
# -----------------------------------------------------------------------------
class RxMixin:
    def on_decode(self, candidate):
        if self.receive_paused:
            return
        if not (candidate.msg and candidate.msg.strip()):
            return
        i3_value = candidate.i3 if hasattr(candidate, 'i3') and candidate.i3 >= 0 else None

        if candidate.snr != -30:
            snr_str = f"SNR:{candidate.snr:+d}"
        else:
            snr_str = "SNR:??"
        dt_str = f"DT:{candidate.dt:.1f}" if candidate.dt is not None else "DT:??"

        corrected_ts = self.get_corrected_timestamp()
        if candidate.dt is not None:
            adjusted_ts = corrected_ts - candidate.dt
        else:
            adjusted_ts = corrected_ts
        slot_start_ts = int(adjusted_ts // 15) * 15
        slot_start_dt = self.utc_from_corrected_ts(slot_start_ts)
        timestamp_str = slot_start_dt.strftime('%Y-%m-%d %H:%M:%S')

        if candidate.msg_tuple and candidate.msg_tuple[0] == 'TRANSPARENT':
            f2_value = candidate.msg_tuple[5] if len(candidate.msg_tuple) > 5 else '?'
            b72_value = candidate.msg_tuple[7] if len(candidate.msg_tuple) > 7 else 0
            self.process_transparent_frame(
                f2=int(f2_value) if f2_value != '?' else -1,
                b72=b72_value,
                freq=candidate.fHz,
                snr=candidate.snr,
                slot_start=slot_start_dt
            )
            return

        if candidate.msg_tuple and candidate.msg_tuple[0] == 'FREE_TEXT':
            free_text = candidate.msg_tuple[1] if len(candidate.msg_tuple) > 1 else ""
            if not free_text:
                free_text = "(empty message)"
            log_msg = (f"[RX] {snr_str} {dt_str} i3=0 {candidate.fHz:4.0f}Hz | "
                       f"Free Text: {free_text}")
            self._safe_call('on_log', f"[{timestamp_str}] {log_msg}", "decode")

            self._upsert_history_entry(
                direction='recv',
                freq=candidate.fHz,
                snr=candidate.snr,
                frames_count=1,
                total_frames=1,
                text=free_text,
                marker=MARKER_FREE_TEXT,
                slot_progress="1/1",
                is_partial=False,
                session_id=f"free_{slot_start_ts}_{candidate.fHz}_{candidate.f0_idx}",
                crc_status="No checksum",
                timestamp=slot_start_dt,
                source_callsign=None,
                target_callsign=None,
                i3=0,
                raw_text=free_text
            )
            return

        if i3_value == 1 and candidate.msg_tuple and len(candidate.msg_tuple) >= 3:
            msg_text = ' '.join(candidate.msg_tuple[:3])
            log_msg = (f"[RX] {snr_str} {dt_str} i3=1 {candidate.fHz:4.0f}Hz | "
                       f"{msg_text}")
            self._safe_call('on_log', f"[{timestamp_str}] {log_msg}", "decode")
            return

        if i3_value is not None and 2 <= i3_value <= 5:
            log_msg = (f"[RX] {snr_str} {dt_str} i3={i3_value} {candidate.fHz:4.0f}Hz | "
                       f"{candidate.msg}")
            self._safe_call('on_log', f"[{timestamp_str}] {log_msg}", "decode")
        else:
            if candidate.msg:
                log_msg = (f"[RX] {snr_str} {dt_str} i3={i3_value} {candidate.fHz:4.0f}Hz | "
                           f"{candidate.msg}")
                self._safe_call('on_log', f"[{timestamp_str}] {log_msg}", "decode")

    def process_transparent_frame(self, f2, b72, freq, snr, slot_start=None):
        if slot_start is None:
            slot_start = self.get_corrected_utc_now()
        timestamp_str = slot_start.strftime('%Y-%m-%d %H:%M:%S')

        frame_bytes = b72.to_bytes(9, 'big')

        if f2 == 0:
            raw = frame_bytes.rstrip(bytes([PROTOCOL_PAD_BYTE]))
            try:
                text = raw.decode('utf-8', errors='replace').strip()
            except Exception:
                text = raw.decode('latin-1', errors='replace').strip()
            if not text:
                text = "(empty message)"
            slot_ts = int(slot_start.timestamp() // 15) * 15
            session_id = f"single_{slot_ts}_{b72}"

            marker = MARKER_SINGLE
            crc_status = "No checksum"

            self._upsert_history_entry(
                direction='recv', freq=freq, snr=snr,
                frames_count=1, total_frames=1,
                text=text, marker=marker, slot_progress="1/1",
                is_partial=False, session_id=session_id, crc_status=crc_status,
                timestamp=slot_start,
                source_callsign=None, target_callsign=None,
                i3=6, f2=0,
                raw_text=text
            )

            if self.audio_in and hasattr(self.audio_in, 'sync_pointer_to_wall_clock'):
                self.audio_in.sync_pointer_to_wall_clock()
                self._safe_call('on_log',
                                _("rx.cleared_buffer",
                                  freq=f"{freq:.0f}"),
                                "debug")

            if snr is not None and snr != -30:
                snr_str = f"SNR:{snr:+d}"
            else:
                snr_str = "SNR:??"
            dt_str = "DT:--"
            msg = (f"[RX] {snr_str} {dt_str} [i3=6] {freq:.0f}Hz | "
                   f"f2=0  b72=0x{b72:018x}")
            self._safe_call('on_log', f"[{timestamp_str}] {msg}", "transparent")
            return

        elif f2 == 1:
            freq_key = int(round(freq / FREQ_GROUP_TOLERANCE) * FREQ_GROUP_TOLERANCE)
            if snr is not None and snr != -30:
                snr_str = f"SNR:{snr:+d}"
            else:
                snr_str = "SNR:??"
            self._safe_call('on_log',
                f"[{timestamp_str}] [RX] {snr_str} DT:-- [i3=6] {freq:.0f}Hz | f2=1, b72=0x{b72:018x}",
                "transparent")

            with self.buffers_lock:
                buffer = None
                for buf in self.transparent_buffers.values():
                    if abs(buf.freq - freq) <= FREQ_GROUP_TOLERANCE and not buf.is_complete:
                        buffer = buf
                        break

                if buffer is None:
                    session_id = f"recv_{freq_key}_{self.next_session_id}"
                    self.next_session_id += 1
                    buffer = TransparentBuffer(
                        session_id, freq_key, freq, snr, self.delay_seconds,
                        self.on_buffer_complete, self.on_buffer_timeout,
                        self.on_buffer_partial,
                        time_func=self.get_corrected_timestamp
                    )
                    buffer.freq_sum = freq
                    buffer.freq_count = 1
                    buffer.first_freq = freq
                    key = f"{freq_key}_{session_id}"
                    self.transparent_buffers[key] = buffer
                    self._safe_call('on_log',
                                    _("rx.new_buffer",
                                      key=freq_key, sid=session_id),
                                    "debug")
                else:
                    self._safe_call('on_log',
                                    _("rx.appended_frame", key=freq_key),
                                    "debug")

            if slot_start is not None:
                buffer.set_slot_start_time(slot_start)

            buffer.append_block(frame_bytes, freq, timestamp=self.get_corrected_timestamp())
            self._safe_call('on_buffer_count', len(self.transparent_buffers))
        else:
            self._safe_call('on_log',
                            _("rx.reserved_frame", f2=f2),
                            "info")

    def on_buffer_partial(self, freq, snr, frames_count, text, slot_start_time, freq_key, session_id):
        marker = _("rx.receiving")
        slot_progress = _("rx.received_frames",
                          n=frames_count, b=len(text.encode('utf-8')))
        self._upsert_history_entry(
            direction='recv', freq=freq, snr=snr,
            frames_count=frames_count, total_frames=None,
            text=text, marker=marker, slot_progress=slot_progress,
            is_partial=True, session_id=session_id, crc_status="partial",
            timestamp=slot_start_time,
            source_callsign=None, target_callsign=None,
            i3=6, f2=1,
            raw_text=text
        )

    def on_buffer_complete(self, buffer, text, marker, status):
        buffer.cancel_timer()
        with self.buffers_lock:
            for key, buf in list(self.transparent_buffers.items()):
                if buf is buffer:
                    del self.transparent_buffers[key]
                    break
        frames_count = buffer.get_frames_count()
        slot_progress = _("rx.received_frames",
                          n=frames_count, b=len(text.encode('utf-8')))
        timestamp = buffer.slot_start_time if buffer.slot_start_time is not None else self.get_corrected_utc_now()
        self._upsert_history_entry(
            direction='recv', freq=buffer.freq, snr=buffer.snr,
            frames_count=frames_count, total_frames=None,
            text=text, marker=marker, slot_progress=slot_progress,
            is_partial=False, session_id=buffer.session_id, crc_status=status,
            timestamp=timestamp,
            source_callsign=None, target_callsign=None,
            i3=6, f2=1,
            raw_text=text
        )
        self._safe_call('on_buffer_count', len(self.transparent_buffers))

    def on_buffer_timeout(self, buffer, text):
        with self.buffers_lock:
            for key, buf in list(self.transparent_buffers.items()):
                if buf is buffer:
                    del self.transparent_buffers[key]
                    break
        frames_count = buffer.get_frames_count()
        slot_progress = _("rx.received_frames",
                          n=frames_count, b=len(text.encode('utf-8')))
        marker = _("rx.timeout")
        timestamp = buffer.slot_start_time if buffer.slot_start_time is not None else self.get_corrected_utc_now()
        self._upsert_history_entry(
            direction='recv', freq=buffer.freq, snr=buffer.snr,
            frames_count=frames_count, total_frames=None,
            text=text, marker=marker, slot_progress=slot_progress,
            is_partial=False, session_id=buffer.session_id, crc_status="timeout",
            timestamp=timestamp,
            source_callsign=None, target_callsign=None,
            i3=6, f2=1,
            raw_text=text
        )
        self._safe_call('on_buffer_count', len(self.transparent_buffers))

# -----------------------------------------------------------------------------
# Contacts mixin (from core_contacts.py)
# -----------------------------------------------------------------------------
class ContactsMixin:
    def _load_contacts(self):
        self.contact_list = []
        if os.path.exists(self.contact_file):
            try:
                with open(self.contact_file, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if line and ',' in line:
                            parts = line.split(',', 1)
                            callsign = parts[0].strip()
                            note = parts[1].strip() if len(parts) > 1 else ""
                            if callsign:
                                self.contact_list.append((callsign, note))
                if len(self.contact_list) > MAX_CONTACTS:
                    self.contact_list = self.contact_list[:MAX_CONTACTS]
            except Exception as e:
                print(_("ct.load_error", e=e))
                self._safe_call('on_toast', _("ct.load_failed", e=e), "error")

    def _save_contacts(self):
        try:
            with open(self.contact_file, 'w', encoding='utf-8') as f:
                for callsign, note in self.contact_list[:MAX_CONTACTS]:
                    f.write(f"{callsign},{note}\n")
        except Exception as e:
            self._safe_call('on_log', _("ct.save_failed", e=e), "error")
            self._safe_call('on_toast', _("ct.save_failed", e=e), "error")

    def _contact_exists(self, callsign):
        callsign = callsign.strip().upper()
        for c, _note in self.contact_list:
            if c == callsign:
                return True
        return False

    def _add_contact(self, callsign, note=""):
        callsign = callsign.strip().upper()
        if not callsign or not is_valid_callsign(callsign):
            self._safe_call('on_toast', _("ct.invalid", call=callsign), "warning")
            return False
        if self._contact_exists(callsign):
            return True
        if len(self.contact_list) >= MAX_CONTACTS:
            self._safe_call('on_log',
                            _("ct.limit_add",
                              n=MAX_CONTACTS, call=callsign),
                            "error")
            self._safe_call('on_toast',
                            _("ct.limit", n=MAX_CONTACTS),
                            "error")
            return False
        note_encoded = note.encode('utf-8')
        if len(note_encoded) > MAX_NOTE_BYTES:
            note = note_encoded[:MAX_NOTE_BYTES].decode('utf-8', errors='ignore')
            self._safe_call('on_log',
                            _("ct.note_trunc", n=MAX_NOTE_BYTES),
                            "warning")
        self.contact_list.append((callsign, note.strip()))
        self._save_contacts()
        self._safe_call('on_contact_updated', self.contact_list)
        self._safe_call('on_toast', _("ct.added", call=callsign), "info")
        return True

    def add_contact(self, callsign, note=""):
        return self._add_contact(callsign, note)

    def delete_contact(self, index):
        if 0 <= index < len(self.contact_list):
            callsign = self.contact_list[index][0]
            del self.contact_list[index]
            self._save_contacts()
            self._safe_call('on_contact_updated', self.contact_list)
            self._safe_call('on_toast', _("ct.deleted", call=callsign), "info")
            return True
        return False

    def update_contact(self, index, new_callsign, new_note):
        if 0 <= index < len(self.contact_list):
            new_callsign = new_callsign.strip().upper()
            if not is_valid_callsign(new_callsign):
                self._safe_call('on_toast',
                                _("ct.invalid", call=new_callsign),
                                "warning")
                return False
            for i, (c, _note) in enumerate(self.contact_list):
                if i != index and c == new_callsign:
                    self._safe_call('on_toast',
                                    _("ct.exists", call=new_callsign),
                                    "warning")
                    return False
            note_encoded = new_note.encode('utf-8')
            if len(note_encoded) > MAX_NOTE_BYTES:
                new_note = note_encoded[:MAX_NOTE_BYTES].decode('utf-8', errors='ignore')
                self._safe_call('on_log',
                                _("ct.note_trunc", n=MAX_NOTE_BYTES),
                                "warning")
            self.contact_list[index] = (new_callsign, new_note.strip())
            self._save_contacts()
            self._safe_call('on_contact_updated', self.contact_list)
            self._safe_call('on_toast', _("ct.updated", call=new_callsign), "info")
            return True
        return False

    def get_contacts(self):
        return self.contact_list.copy()

    def _find_contact_note(self, callsign):
        if not callsign:
            return None
        target = callsign.strip().upper()
        for c, note in self.contact_list:
            if c.strip().upper() == target:
                return note or None
        return None

    def _auto_save_source_contact(self, callsign):
        if not callsign or self._contact_exists(callsign):
            return
        date_str = self.get_corrected_utc_now().strftime("%Y-%m-%d")
        note = _("ct.auto_note", date=date_str)
        if self._add_contact(callsign, note):
            self._safe_call('on_log',
                            _("ct.auto_saved",
                              call=callsign),
                            "auto_contact")
            self._safe_call('on_toast',
                            _("ct.auto_saved_toast", call=callsign),
                            "info")

# -----------------------------------------------------------------------------
# History mixin (from core_history.py)
# -----------------------------------------------------------------------------
class HistoryMixin:
    def _upsert_history_entry(self, direction, freq, snr, frames_count, total_frames,
                              text, marker, slot_progress, is_partial=False, session_id=None,
                              crc_status=None, timestamp=None, source_callsign=None,
                              target_callsign=None, i3=None, f2=None,
                              raw_text=None):
        if timestamp is None:
            timestamp = self.get_corrected_utc_now()

        raw_for_parse = raw_text if raw_text is not None else text

        if direction == 'recv' and raw_for_parse:
            beacon_match = BEACON_PATTERN.match(raw_for_parse.strip())
            if beacon_match:
                marker = MARKER_BEACON

        if direction == 'recv':
            source_callsign = self._extract_source_callsign(raw_for_parse)
            self._auto_save_source_contact(source_callsign)
            contact_note = self._find_contact_note(source_callsign)
        else:
            source_callsign = None
            contact_note = None

        target_callsign = self._extract_target_callsign(raw_for_parse)

        is_self_targeted = (target_callsign is not None and
                            target_callsign == self.callsign)

        total_bytes = len(text.encode('utf-8')) if text else 0
        entry = HistoryEntry(
            direction=direction, timestamp=timestamp, freq=freq, snr=snr,
            frames_count=frames_count, total_bytes=total_bytes,
            text=text,
            marker=marker, is_complete=not is_partial, slot_progress=slot_progress,
            is_partial=is_partial, session_id=session_id, crc_status=crc_status,
            source_callsign=source_callsign, target_callsign=target_callsign,
            i3=i3, f2=f2,
            total_frames=total_frames,
            total_bytes_all=None,
            is_self_targeted=is_self_targeted,
            contact_note=contact_note
        )
        self.add_history_entry(entry)

    def _add_send_history_realtime(self, freq, frames_count, total_frames, text, marker, slot_progress,
                                   is_partial=False, session_id=None, timestamp=None,
                                   total_bytes_all=None):
        if timestamp is None:
            timestamp = self.get_corrected_utc_now()
        # Match Java: when the TX entry is complete, use total_bytes_all
        # which includes 0x20 padding for continuous frames. Partial
        # entries fall back to the UTF-8 length of the current text.
        if not is_partial and total_bytes_all is not None:
            total_bytes = total_bytes_all
        else:
            total_bytes = len(text.encode('utf-8')) if text else 0
        if session_id is None:
            session_id = f"send_{freq}_{int(self.get_corrected_timestamp()*1000)}"
        entry = HistoryEntry(
            direction='send', timestamp=timestamp, freq=freq, snr=None,
            frames_count=frames_count, total_bytes=total_bytes,
            text=text,
            marker=marker, is_complete=not is_partial, slot_progress=slot_progress,
            is_partial=is_partial, session_id=session_id, crc_status=None,
            source_callsign=None, target_callsign=None,
            i3=None,
            total_frames=total_frames,
            total_bytes_all=total_bytes_all,
            is_self_targeted=False,
            contact_note=None
        )
        self.add_history_entry(entry)

    def add_history_entry(self, entry):
        with self._history_lock:
            existing_index = None
            if entry.session_id is not None:
                for i, e in enumerate(self.history_entries):
                    if e.direction == entry.direction and e.session_id == entry.session_id:
                        existing_index = i
                        break
            if existing_index is not None:
                self.history_entries[existing_index] = entry
                self._safe_call('on_history', entry)
                return

            self.history_entries.append(entry)
            while len(self.history_entries) > self.max_history:
                self.history_entries.pop(0)
            self._safe_call('on_history', entry)

    def _extract_source_callsign(self, raw_text):
        return extract_source_callsign(raw_text)

    def _extract_target_callsign(self, raw_text):
        return extract_target_callsign(raw_text)

    def _parse_message_callsigns(self, raw_text):
        return (extract_source_callsign(raw_text),
                extract_target_callsign(raw_text))

# -----------------------------------------------------------------------------
# Core assembly (from core.py)
# -----------------------------------------------------------------------------
class Core(TimeMixin, ConfigMixin, ReceiverMixin, BeaconMixin,
           TxMixin, RxMixin, ContactsMixin, HistoryMixin, CoreBase):
    """FT8 Plus business core. Functionality is split across mixins."""
    pass

__all__ = [
    "Core", "StdoutRedirector",
    "HistoryEntry", "TransparentBuffer", "UTF8StreamDecoder",
    "CustomAudioOut",
    "is_valid_callsign", "extract_source_callsign",
    "extract_target_callsign", "parse_message_callsigns",
    "crc8",
    "MAX_RAW_DATA_BYTES", "MAX_TOTAL_BYTES", "MAX_FRAMES",
    "FIXED_MAX_HISTORY", "FIXED_MAX_MESSAGES",
    "FIXED_FREQ_START", "FIXED_FREQ_END",
    "FIXED_DELAY_SLOTS", "FIXED_DELAY_SECONDS",
    "MAX_ACTIVE_BUFFERS", "MAX_CONTACTS", "MAX_NOTE_BYTES",
    "FREQ_GROUP_TOLERANCE", "PROTOCOL_PAD_BYTE", "PROTOCOL_EOT_BYTE",
    "BEACON_PATTERN",
]

# -----------------------------------------------------------------------------
# Entry point (from main.py)
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    import tkinter as tk

    def main():
        from gui import GUI
        # Language is chosen automatically by I18n.load_auto():
        #   1. bundled strings file matching the system locale (_MEIPASS)
        #   2. fallback to English
        # External strings next to the exe are intentionally ignored.
        root = tk.Tk()
        core = Core()
        gui = GUI(root, core)
        core.start_ntp_sync()
        root.protocol("WM_DELETE_WINDOW",
                      lambda: (core.stop_receiver(), core.stop_transmit(),
                               core.shutdown(), root.destroy()))
        root.mainloop()

    main()