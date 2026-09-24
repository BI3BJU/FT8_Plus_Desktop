# main.py - i18n enabled

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import threading
import time
import math
import json
import random
import re
import numpy as np
from datetime import datetime
import pyaudio
import webbrowser

from receiver import AudioIn, Receiver
from transmitter import (
    AudioOut,
    pack_transparent_message,
    pack_free_text,
    is_free_text_compatible
)

import maidenhead as mh

try:
    import ntplib
    _NTP_AVAILABLE = True
except ImportError:
    _NTP_AVAILABLE = False
    ntplib = None

from i18n import _, MARKER_FREE_TEXT, MARKER_SINGLE, MARKER_BEACON


# ---------- CRC8 ----------
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


# ---------- Constants ----------
MAX_RAW_DATA_BYTES = 574
MAX_TOTAL_BYTES = 576
MAX_FRAMES = 64
FIXED_MAX_HISTORY = 100
FIXED_MAX_MESSAGES = 100
FIXED_FREQ_START = 300
FIXED_FREQ_END = 3000
FIXED_DELAY_SLOTS = 4
FIXED_DELAY_SECONDS = FIXED_DELAY_SLOTS * 15
MAX_ACTIVE_BUFFERS = 200
MAX_CONTACTS = 100
MAX_NOTE_BYTES = 32
FREQ_GROUP_TOLERANCE = 10


# ========== Callsign format validation ==========
def is_valid_callsign(call: str) -> bool:
    call = call.strip().upper()
    if not re.fullmatch(r'^[A-Z0-9]{1,2}[0-9][A-Z]{0,3}$', call):
        return False
    prefix = re.match(r'^[A-Z0-9]{1,2}', call).group()
    if not re.search(r'[A-Z]', prefix):
        return False
    return True


def is_valid_grid6(grid: str) -> bool:
    if not grid:
        return False
    grid = grid.strip().upper()
    return bool(re.fullmatch(r'[A-R]{2}[0-9]{2}[A-X]{2}', grid))


def grid6_to_latlon(grid: str) -> tuple:
    grid = grid.strip().upper()
    if not is_valid_grid6(grid):
        raise ValueError(f"Invalid grid: {grid}")
    try:
        lat, lon = mh.to_location(grid, center=True)
        return (lat, lon)
    except Exception as e:
        raise RuntimeError(f"maidenhead conversion failed: {e}")


# ---------- UTF-8 Stream Decoder ----------
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


# ---------- TransparentBuffer ----------
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
        eot_pos = self._all_data.find(b'\x04')
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
        else:
            status = f"CRC fail (calc {crc_calc:02x}, recv {crc_received:02x})"
            marker = "CRC fail"
        try:
            text = raw_received.decode('utf-8', errors='replace')
        except Exception:
            text = raw_received.decode('latin-1', errors='replace')
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
            eot_pos = all_data.find(b'\x04')
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


# ---------- HistoryEntry ----------
class HistoryEntry:
    def __init__(self, direction, timestamp, freq, snr, frames_count,
                 total_bytes, text, marker, is_complete=True, slot_progress=None,
                 is_partial=False, session_id=None, crc_status=None,
                 source_callsign=None, target_callsign=None,
                 i3=None, total_frames=None, total_bytes_all=None,
                 is_beacon=False, grid6=None, is_self_targeted=False):
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
        self.total_frames = total_frames
        self.total_bytes_all = total_bytes_all
        self.is_beacon = is_beacon
        self.grid6 = grid6
        self.is_self_targeted = is_self_targeted


# ========== Stdout redirection ==========
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


# ========== Extended AudioOut ==========
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
                            channels=1,
                            rate=sample_rate,
                            output=True,
                            frames_per_buffer=1024)
            chunk_size = 1024
            for i in range(0, len(audio_int16), chunk_size):
                if self.stop_flag:
                    break
                chunk = audio_int16[i:i+chunk_size]
                stream.write(chunk.tobytes())
            stream.stop_stream()
            stream.close()
            if self.stop_flag:
                return False
            return True
        except Exception as e:
            print(_("White noise playback exception: {e}", e=e))
            import traceback
            traceback.print_exc()
            return False

    def shutdown(self):
        if self._pyaudio is not None:
            self._pyaudio.terminate()
            self._pyaudio = None


# ---------- Core class ----------
class Core:
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

        self.config_file = "config.txt"
        self.callsign = ""
        self.tx_freq = 1500
        self.preamble_noise_enabled = False

        self.grid6 = ""

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

        self.beacon_enabled = False
        self._beacon_stop_event = threading.Event()
        self._beacon_thread = None
        self._input_availability_callback = None
        self._fill_input_callback = None
        self._next_beacon_slot = None

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
        }

        self._history_lock = threading.Lock()

        self.contact_file = "contact.txt"
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

    # ---------- NTP ----------
    def start_ntp_sync(self):
        if self._ntp_synced:
            return
        threading.Thread(target=self._sync_ntp, daemon=True).start()

    def _sync_ntp(self):
        if not _NTP_AVAILABLE:
            self._safe_call('on_log', _("ntplib not installed, NTP unavailable. Run: pip install ntplib"), "warning")
            self._safe_call('on_toast', _("ntplib not installed, cannot sync time"), "warning")
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
                                _("NTP sync OK (server {server}), offset {offset:.3f}s",
                                  server=server, offset=offset),
                                "info")
                self._safe_call('on_toast',
                                _("Time calibrated (offset {offset:.3f}s)", offset=offset),
                                "info")
                return
            except Exception as e:
                self._safe_call('on_log',
                                _("NTP sync failed ({server}): {e}", server=server, e=e),
                                "warning")
        self._time_offset = 0.0
        self._safe_call('on_log', _("NTP sync failed, using system time"), "warning")

    def get_corrected_timestamp(self):
        return time.time() + self._time_offset

    def get_corrected_utc_now(self):
        return self.utc_from_corrected_ts(self.get_corrected_timestamp())

    def utc_from_corrected_ts(self, corrected_ts):
        return datetime.utcfromtimestamp(corrected_ts)

    # ---------- Configuration ----------
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
                                _("Invalid callsign: {callsign}, cleared", callsign=raw_callsign),
                                "warning")
                self._safe_call('on_toast', _("Invalid callsign, cleared"), "warning")
            tx_freq = config.get('tx_freq', '1500')
            try:
                val = int(float(tx_freq))
                if 300 <= val <= 3000:
                    self.tx_freq = val
            except Exception:
                pass
            self.preamble_noise_enabled = config.get('preamble_noise', False)
            raw_grid = config.get('grid6', '').strip().upper()
            if raw_grid and is_valid_grid6(raw_grid):
                self.grid6 = raw_grid
            else:
                self.grid6 = ""
                if raw_grid:
                    self._safe_call('on_log',
                                    _("Invalid grid: {grid}, cleared", grid=raw_grid),
                                    "warning")
            self._safe_call('on_log', _("Config loaded"), "info")
        except Exception as e:
            self._safe_call('on_log',
                            _("Config load failed: {e}, using defaults", e=e),
                            "error")
            self._safe_call('on_toast', _("Config load failed, using defaults"), "error")
            self._apply_defaults()

    def save_config(self):
        if self.callsign and not is_valid_callsign(self.callsign):
            self._safe_call('on_log', _("Attempted to save invalid callsign, ignored"), "warning")
            self._safe_call('on_toast', _("Invalid callsign, save ignored"), "warning")
            return
        config = {
            'callsign': self.callsign,
            'tx_freq': str(self.tx_freq),
            'preamble_noise': self.preamble_noise_enabled,
            'grid6': self.grid6,
        }
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Save config error: {e}")
            self._safe_call('on_toast', _("Save config failed: {e}", e=e), "error")

    def _apply_defaults(self):
        self.callsign = ""
        self.tx_freq = 1500
        self.preamble_noise_enabled = False
        self.grid6 = ""

    def set_preamble_noise(self, value):
        self.preamble_noise_enabled = value
        self.save_config()
        state = _("enabled") if value else _("disabled")
        self._safe_call('on_log', _("Preamble noise {state}", state=state), "info")
        self._safe_call('on_toast', _("Preamble noise {state}", state=state), "info")

    def set_grid6(self, grid):
        if grid and not is_valid_grid6(grid):
            return False
        self.grid6 = grid.strip().upper() if grid else ""
        return True

    def set_input_availability_callback(self, callback):
        self._input_availability_callback = callback

    def set_fill_input_callback(self, callback):
        self._fill_input_callback = callback

    def toggle_beacon(self):
        if not self.is_running:
            self._safe_call('on_toast', _("Please start receiver before enabling beacon"), "warning")
            return
        if not self.callsign:
            self._safe_call('on_toast', _("Please set callsign before enabling beacon"), "warning")
            return
        if not self.grid6:
            self._safe_call('on_toast', _("Please set grid (click Grid button at top)"), "warning")
            return
        self.beacon_enabled = not self.beacon_enabled
        if self.beacon_enabled:
            self._safe_call('on_log',
                            _("Beacon enabled: {callsign} {grid}, transmit every 4 slots",
                              callsign=self.callsign, grid=self.grid6),
                            "info")
            self._safe_call('on_toast', _("Beacon enabled"), "info")
            self._beacon_stop_event.clear()
            self._next_beacon_slot = self._get_next_slot(self.get_corrected_timestamp())
            self._beacon_thread = threading.Thread(target=self._beacon_worker, daemon=True)
            self._beacon_thread.start()
        else:
            self._safe_call('on_log', _("Beacon disabled"), "info")
            self._safe_call('on_toast', _("Beacon disabled"), "info")
            self._beacon_stop_event.set()
            if self._beacon_thread and self._beacon_thread.is_alive():
                self._beacon_thread.join(timeout=1.0)
            self._beacon_thread = None
            self._next_beacon_slot = None

    def _beacon_worker(self):
        while not self._beacon_stop_event.is_set():
            now = self.get_corrected_timestamp()
            if self._next_beacon_slot is None:
                self._next_beacon_slot = self._get_next_slot(now)
            wait = self._next_beacon_slot - now
            if wait > 0:
                if self._beacon_stop_event.wait(wait):
                    break

            beacon_text = f"{self.callsign} {self.grid6}"
            available = True
            if self._input_availability_callback is not None:
                try:
                    available = self._input_availability_callback(beacon_text)
                except Exception:
                    available = False
            if available and not self.is_transmitting and self.callsign and self.grid6:
                self._safe_call('on_log', _("Beacon TX: {text}", text=beacon_text), "info")
                if self._fill_input_callback is not None:
                    try:
                        self._fill_input_callback(beacon_text)
                    except Exception:
                        pass
                self._send_free_text(beacon_text, self.tx_freq,
                                     start_slot=self._next_beacon_slot, is_beacon=True)
            else:
                if not available:
                    self._safe_call('on_log', _("Beacon slot skipped: user content in input"), "debug")
                elif self.is_transmitting:
                    self._safe_call('on_log', _("Beacon slot skipped: transmitting"), "debug")
            if self._next_beacon_slot is not None:
                self._next_beacon_slot += 60
            else:
                break

    def _get_next_slot(self, t):
        cycle = self.cycle_seconds
        return int(t // cycle) * cycle + cycle

    def set_callbacks(self, **kwargs):
        for key, func in kwargs.items():
            if key in self._callbacks:
                self._callbacks[key] = func

    def _safe_call(self, key, *args, **kwargs):
        func = self._callbacks.get(key)
        if func:
            func(*args, **kwargs)

    # ---------- Receiver ----------
    def start_receiver(self):
        try:
            freq_start = self.fixed_freq_start
            freq_end = self.fixed_freq_end
            if freq_start >= freq_end:
                self._safe_call('on_log', "Error: start freq must be less than end freq", "error")
                self._safe_call('on_toast', "Freq range error", "error")
                return
            freq_range = (freq_start, freq_end)
            self._safe_call('on_log',
                            _("Starting receiver, freq range: {start}-{end} Hz",
                              start=freq_start, end=freq_end),
                            "info")
            self.audio_in = AudioIn(max_freq=freq_end, wav_files=None)
            self.audio_in.start_streamed_audio(None)
            self._safe_call('on_log', _("Audio input started (default system device)"), "info")
            self.receiver = Receiver(
                audio_in=self.audio_in, freq_range=freq_range,
                on_decode=self.on_decode, on_busy_profile=self.on_busy_profile, verbose=False
            )
            self.is_running = True
            self.receive_paused = False
            self._safe_call('on_status', False)
            self._safe_call('on_log', _("FT8 receiver started"), "info")
            self._safe_call('on_log',
                            _("Merge delay: {n} slots ({s} s)",
                              n=self.delay_slots, s=self.delay_seconds),
                            "info")
            self._safe_call('on_log',
                            _("Unicode: single f2=0, multi f2=1, grouped by freq (±10Hz), ends with EOT, CRC checked"),
                            "info")
            self._safe_call('on_log',
                            _("Max raw data: {n} bytes, max frames: {m}",
                              n=self.max_raw_data_bytes, m=self.max_frames),
                            "info")
            self._safe_call('on_log',
                            _("Input filters non-printable (keeps \\t\\r\\n), no empty messages"),
                            "info")
            self._safe_call('on_log',
                            _("Receiver groups by freq (±10Hz tolerance for first frame)"),
                            "info")
            self._safe_call('on_log',
                            _("Auto mode: input ≤13 chars all in free-text charset → i3=0, else → i3=6 Unicode"),
                            "info")
        except Exception as e:
            self._safe_call('on_log', _("Start failed: {e}", e=e), "error")
            self._safe_call('on_toast', _("Receiver start failed: {e}", e=e), "error")
            print(f"Start error: {e}")

    def stop_receiver(self):
        self._safe_call('on_log', _("Stopping receiver..."), "info")
        self.stop_transmit()
        if self.beacon_enabled:
            self.beacon_enabled = False
            self._beacon_stop_event.set()
            if self._beacon_thread and self._beacon_thread.is_alive():
                self._beacon_thread.join(timeout=1.0)
            self._beacon_thread = None
            self._next_beacon_slot = None
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
                self._safe_call('on_log', _("Audio stream stopped"), "info")
            if self.audio_in and hasattr(self.audio_in, 'close'):
                self.audio_in.close()
        except Exception as e:
            self._safe_call('on_log', _("Error stopping audio stream: {e}", e=e), "error")
            self._safe_call('on_toast', _("Error stopping audio stream: {e}", e=e), "error")
        self.receiver = None
        self.audio_in = None
        self._safe_call('on_log', _("FT8 receiver stopped"), "info")

    def on_busy_profile(self, bp, cycle):
        pass

    # ---------- Transmit ----------
    def transmit_text(self, text, freq):
        if self.is_transmitting:
            self._safe_call('on_log', _("Transmitting, please wait"), "error")
            self._safe_call('on_toast', _("Transmitting, please wait"), "warning")
            return
        if not self.is_running:
            self._safe_call('on_log', _("Please start receiver first"), "error")
            self._safe_call('on_toast', _("Please start receiver first"), "warning")
            return
        self.is_transmitting = True
        self.stop_requested = False
        self._safe_call('on_tx_task', True)
        threading.Thread(target=self._transmit_worker, args=(text, freq), daemon=True).start()

    def _transmit_worker(self, text, freq):
        try:
            if not text.strip():
                raise ValueError(_("Please enter data (cannot be empty)"))
            filtered = []
            for ch in text:
                code = ord(ch)
                if ch in ('\t', '\r', '\n') or (32 <= code <= 126) or code >= 0x80:
                    filtered.append(ch)
            filtered_str = ''.join(filtered)
            if not filtered_str:
                raise ValueError(_("Input contains only non-printable characters"))

            if is_free_text_compatible(filtered_str):
                self._send_free_text(filtered_str, freq)
                return

            raw_data = filtered_str.encode('utf-8')
            raw_len = len(raw_data)
            if raw_len > self.max_raw_data_bytes:
                raise ValueError(_("UTF-8 encoded {n} bytes, exceeds {max} bytes limit",
                                   n=raw_len, max=self.max_raw_data_bytes))

            if raw_len <= 9:
                frame_data = raw_data.ljust(9, b'\x00')
                frames = [(0, frame_data)]
                total_frames = 1
            else:
                crc_val = crc8(raw_data)
                payload = raw_data + bytes([crc_val]) + bytes([0x04])
                blocks = [payload[i:i+9] for i in range(0, len(payload), 9)]
                if len(blocks) > self.max_frames:
                    raise ValueError(_("Data too long: {n} frames needed, exceeds {max} limit",
                                       n=len(blocks), max=self.max_frames))
                if len(blocks[-1]) < 9:
                    blocks[-1] = blocks[-1].ljust(9, b'\x00')
                frames = [(1, d9) for d9 in blocks]
                total_frames = len(frames)

            display_text = filtered_str

            self._safe_call('on_log',
                            _("Transparent data split into {n} frames", n=total_frames),
                            "info")
            self._safe_call('on_log',
                            _("Data content: {text}", text=display_text[:100] + ('...' if len(display_text) > 100 else '')),
                            "info")
            if total_frames == 1:
                self._safe_call('on_log', _("Single frame mode: f2=0, no checksum"), "info")
            else:
                self._safe_call('on_log', _("Multi frame mode: f2=1, 9 bytes per frame"), "info")
                self._safe_call('on_log', _("Payload = raw + CRC8 + EOT(0x04)"), "info")

            self._transmit_frames(frames, freq, total_frames, display_text, raw_data)

        except Exception as e:
            msg = _("Data preparation failed: {e}", e=e)
            self._safe_call('on_log', msg, "error")
            self._safe_call('on_toast', msg, "error")
            try:
                fail_session_id = f"send_fail_prep_{int(self.get_corrected_timestamp()*1000)}"
                self._add_send_history_realtime(
                    freq=freq,
                    frames_count=0,
                    total_frames=1,
                    text=text if text else "(empty)",
                    marker=_("TX failed"),
                    slot_progress="0/1",
                    is_partial=False,
                    session_id=fail_session_id,
                    timestamp=self.get_corrected_utc_now(),
                    total_bytes_all=len(text.encode('utf-8')) if text else 0
                )
            except Exception as ex:
                self._safe_call('on_log',
                                _("Error recording TX failure history: {e}", e=ex),
                                "error")
            self._cleanup_tx()

    def _send_free_text(self, text, freq, start_slot=None, is_beacon=False):
        session_id = f"free_send_{int(time.time()*1000)}"
        raw_data = text.encode('utf-8')
        total_bytes_all = len(raw_data)
        self._safe_call('on_log', _("Free text: '{text}' (i3=0)", text=text), "info")
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
                self._safe_call('on_log', _("Waiting {t}s for slot start", t=f"{wait_time:.1f}"), "info")
                if not self._interruptible_sleep(wait_time):
                    self._safe_call('on_log', _("TX stopped by user"), "info")
                    self._safe_call('on_toast', _("TX cancelled"), "info")
                    return

        if self.preamble_noise_enabled:
            noise_start = next_slot - 1.0
            now = self.get_corrected_timestamp()
            if now < noise_start:
                if not self._interruptible_sleep(noise_start - now):
                    return
            self.pause_receiver()
            if not self.audio_out.play_white_noise(0.5):
                self._safe_call('on_log', _("White noise playback failed, TX aborted"), "error")
                self._safe_call('on_toast', _("White noise playback failed, TX aborted"), "error")
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
                            f"[{slot_start_dt.strftime('%Y-%m-%d %H:%M:%S')}] " + _("Starting free text TX"),
                            "tx")

            self._add_send_history_realtime(
                freq=freq,
                frames_count=0,
                total_frames=1,
                text=text,
                marker=MARKER_FREE_TEXT,
                slot_progress="0/1",
                is_partial=True,
                session_id=session_id,
                timestamp=slot_start_dt,
                total_bytes_all=total_bytes_all,
                is_beacon=is_beacon
            )

            success = self.audio_out.play_ft8_only(ft8_data, None)
            if success:
                self._safe_call('on_log', _("Free text sent OK"), "info")
                self._safe_call('on_toast', _("Free text sent OK"), "info")
                self._add_send_history_realtime(
                    freq=freq,
                    frames_count=1,
                    total_frames=1,
                    text=text,
                    marker=MARKER_FREE_TEXT,
                    slot_progress="1/1",
                    is_partial=False,
                    session_id=session_id,
                    timestamp=slot_start_dt,
                    total_bytes_all=total_bytes_all,
                    is_beacon=is_beacon
                )
            else:
                self._safe_call('on_log', _("Free text send failed"), "error")
                self._safe_call('on_toast', _("Free text send failed"), "error")
                self._add_send_history_realtime(
                    freq=freq,
                    frames_count=0,
                    total_frames=1,
                    text=text,
                    marker=_("TX failed"),
                    slot_progress="0/1",
                    is_partial=False,
                    session_id=session_id,
                    timestamp=slot_start_dt,
                    total_bytes_all=total_bytes_all,
                    is_beacon=is_beacon
                )
        except Exception as e:
            self._safe_call('on_log', _("Free text TX exception: {e}", e=e), "error")
            self._safe_call('on_toast', _("Free text TX exception: {e}", e=e), "error")
            self._add_send_history_realtime(
                freq=freq,
                frames_count=0,
                total_frames=1,
                text=text,
                marker=_("TX failed"),
                slot_progress="0/1",
                is_partial=False,
                session_id=session_id,
                timestamp=self.get_corrected_utc_now(),
                total_bytes_all=total_bytes_all,
                is_beacon=is_beacon
            )
            raise
        finally:
            t_now = self.get_corrected_timestamp()
            next_slot_after = self._get_next_slot(t_now)
            wait_time = next_slot_after - t_now
            if wait_time > 0.1:
                self._safe_call('on_log',
                                _("TX complete, waiting {t}s for slot start to switch to RX",
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
        total_bytes_all = len(raw_data)
        self._safe_call('on_tx_progress',
                        _("Waiting slot... (total {n} frames)", n=total_frames))

        if total_frames == 1:
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
                    self._safe_call('on_log', _("Frame TX failed, stopping."), "error")
                    self._safe_call('on_toast', _("Frame TX failed, TX aborted"), "error")
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
                                    _("TX complete, waiting {t}s for slot end to switch to RX",
                                      t=f"{wait_time:.1f}"),
                                    "info")
                    self._interruptible_sleep(wait_time)
                self.resume_receiver()
                self._safe_call('on_log', _("Switched to RX at slot end"), "info")

            is_complete = (sent_frames_count == total_frames) and not self.stop_requested and not tx_failed
            if is_complete:
                if total_frames == 1:
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
                                _("TX complete: {n}/{m} frames", n=total_frames, m=total_frames))
                self._safe_call('on_toast',
                                _("TX complete: {n}/{m} frames", n=total_frames, m=total_frames),
                                "info")
            else:
                if tx_failed:
                    final_marker = _("TX failed")
                    shown_frames = max(sent_frames_count, 1)
                    current_text = raw_data[:min(shown_frames * 9, len(raw_data))].decode('utf-8', errors='replace')
                    final_text = current_text
                    final_slot_progress = f"{sent_frames_count}/{total_frames}"
                else:
                    final_marker = _("Manual interrupt")
                    current_text = raw_data[:min(sent_frames_count * 9, len(raw_data))].decode('utf-8', errors='replace')
                    final_text = current_text + " [TX interrupted]"
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
                                    _("TX failed: {n}/{m} frames", n=sent_frames_count, m=total_frames))
                    self._safe_call('on_toast',
                                    _("TX failed: {n}/{m} frames", n=sent_frames_count, m=total_frames),
                                    "error")
                else:
                    self._safe_call('on_tx_progress',
                                    _("TX interrupted: {n}/{m} frames", n=sent_frames_count, m=total_frames))
                    self._safe_call('on_toast',
                                    _("TX interrupted: {n}/{m} frames", n=sent_frames_count, m=total_frames),
                                    "warning")

        except Exception as e:
            self._safe_call('on_log', _("TX error: {e}", e=e), "error")
            self._safe_call('on_toast', _("TX error: {e}", e=e), "error")
            import traceback
            traceback.print_exc()
            try:
                self._add_send_history_realtime(
                    freq=tx_freq,
                    frames_count=sent_frames_count,
                    total_frames=total_frames,
                    text=display_text,
                    marker=_("TX failed"),
                    slot_progress=f"{sent_frames_count}/{total_frames}",
                    is_partial=False,
                    session_id=send_session_id,
                    timestamp=self.get_corrected_utc_now(),
                    total_bytes_all=total_bytes_all
                )
            except Exception as ex:
                self._safe_call('on_log',
                                _("Error recording TX failure history: {e}", e=ex),
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
        self._safe_call('on_log', _("Stopping TX..."), "info")
        self.stop_requested = True
        self.audio_out.request_stop()
        if self.transmit_thread and self.transmit_thread.is_alive():
            self.transmit_thread.join(timeout=2.0)
        self.is_transmitting = False
        self.current_send_session_id = None
        if self.receive_paused:
            self.resume_receiver()
        self._safe_call('on_tx_task', False)
        self._safe_call('on_log', _("TX stopped"), "info")
        self._safe_call('on_toast', _("TX stopped"), "info")

    def transmit_single_frame(self, f2, frame_data, tx_freq_hz):
        b72 = int.from_bytes(frame_data, 'big')
        d74 = (f2 << 72) | b72
        f2_temp = (d74 >> 72) & 0x3
        b72_temp = d74 & ((1 << 72) - 1)
        symbols, _unused = pack_transparent_message(f2_temp, b72_temp)
        ft8_data = self.audio_out.create_ft8_wave(symbols, fs=12000, f_base=tx_freq_hz, f_step=6.25, amplitude=1.0)
        self.audio_out.clear_stop_flag()
        return self.audio_out.play_ft8_only(ft8_data, None)

    # ---------- Receive callbacks ----------
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
        dt_str = f"DT:{candidate.dt:.1f}" if candidate.dt else "DT:??"

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
            is_beacon = False
            grid6 = None
            match = re.match(r'^([A-Z0-9]{3,6})\s+([A-R]{2}[0-9]{2}[A-X]{2})$', free_text.strip())
            if match:
                is_beacon = True
                grid6 = match.group(2)
                display_text = f"{match.group(1)} 📡 {grid6}"
            else:
                display_text = free_text

            self._upsert_history_entry(
                direction='recv',
                freq=candidate.fHz,
                snr=candidate.snr,
                frames_count=1,
                total_frames=1,
                text=display_text,
                marker=MARKER_FREE_TEXT,
                slot_progress="1/1",
                is_partial=False,
                session_id=f"free_{slot_start_ts}_{candidate.fHz}_{candidate.f0_idx}",
                crc_status="No checksum",
                timestamp=slot_start_dt,
                source_callsign=None,
                target_callsign=None,
                i3=0,
                is_beacon=is_beacon,
                grid6=grid6,
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
            raw = frame_bytes.rstrip(b'\x00')
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
                i3=6,
                raw_text=text
            )

            if self.audio_in and hasattr(self.audio_in, 'sync_pointer_to_wall_clock'):
                self.audio_in.sync_pointer_to_wall_clock()
                self._safe_call('on_log',
                                _("Cleared audio buffer after single frame (freq {freq}Hz)",
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
                                    _("Created new buffer for freq group {key}Hz, session={sid}",
                                      key=freq_key, sid=session_id),
                                    "debug")
                else:
                    self._safe_call('on_log',
                                    _("Appended frame to freq group {key}Hz", key=freq_key),
                                    "debug")

            if slot_start is not None:
                buffer.set_slot_start_time(slot_start)

            buffer.append_block(frame_bytes, freq, timestamp=self.get_corrected_timestamp())
            self._safe_call('on_buffer_count', len(self.transparent_buffers))
        else:
            self._safe_call('on_log',
                            _("Received reserved frame f2={f2}, ignored", f2=f2),
                            "info")

    def on_buffer_partial(self, freq, snr, frames_count, text, slot_start_time, freq_key, session_id):
        marker = _("Receiving")
        slot_progress = _("Received {n} frames {b} bytes",
                          n=frames_count, b=len(text.encode('utf-8')))
        self._upsert_history_entry(
            direction='recv', freq=freq, snr=snr,
            frames_count=frames_count, total_frames=None,
            text=text, marker=marker, slot_progress=slot_progress,
            is_partial=True, session_id=session_id, crc_status="partial",
            timestamp=slot_start_time,
            source_callsign=None, target_callsign=None,
            i3=6,
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
        slot_progress = _("Received {n} frames {b} bytes",
                          n=frames_count, b=len(text.encode('utf-8')))
        timestamp = buffer.slot_start_time if buffer.slot_start_time is not None else self.get_corrected_utc_now()
        self._upsert_history_entry(
            direction='recv', freq=buffer.freq, snr=buffer.snr,
            frames_count=frames_count, total_frames=None,
            text=text, marker=marker, slot_progress=slot_progress,
            is_partial=False, session_id=buffer.session_id, crc_status=status,
            timestamp=timestamp,
            source_callsign=None, target_callsign=None,
            i3=6,
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
        slot_progress = _("Received {n} frames {b} bytes",
                          n=frames_count, b=len(text.encode('utf-8')))
        marker = _("Receive timeout")
        timestamp = buffer.slot_start_time if buffer.slot_start_time is not None else self.get_corrected_utc_now()
        self._upsert_history_entry(
            direction='recv', freq=buffer.freq, snr=buffer.snr,
            frames_count=frames_count, total_frames=None,
            text=text, marker=marker, slot_progress=slot_progress,
            is_partial=False, session_id=buffer.session_id, crc_status="timeout",
            timestamp=timestamp,
            source_callsign=None, target_callsign=None,
            i3=6,
            raw_text=text
        )
        self._safe_call('on_buffer_count', len(self.transparent_buffers))

    # ---------- History management ----------
    def _extract_source_callsign(self, raw_text):
        if not raw_text:
            return None
        raw_upper = raw_text.strip().upper()
        for length in range(6, 2, -1):
            if len(raw_upper) >= length:
                cand = raw_upper[:length]
                if is_valid_callsign(cand):
                    return cand
        return None

    def _upsert_history_entry(self, direction, freq, snr, frames_count, total_frames,
                              text, marker, slot_progress, is_partial=False, session_id=None,
                              crc_status=None, timestamp=None, source_callsign=None,
                              target_callsign=None, i3=None,
                              is_beacon=False, grid6=None, raw_text=None):
        if timestamp is None:
            timestamp = self.get_corrected_utc_now()

        raw_for_parse = raw_text if raw_text is not None else text

        if direction == 'recv':
            src_candidate = self._extract_source_callsign(raw_for_parse)
            if src_candidate:
                if not self._contact_exists(src_candidate):
                    note = self.utc_from_corrected_ts(self.get_corrected_timestamp()).strftime("%Y-%m-%d %H:%M:%S")
                    self._add_contact(src_candidate, note)
                    self._safe_call('on_log',
                                    _("Auto-saved contact: {call} (from received msg start)",
                                      call=src_candidate),
                                    "auto_contact")
                    self._safe_call('on_toast',
                                    _("Auto-saved contact: {call}", call=src_candidate),
                                    "info")
                source_callsign = src_candidate
            else:
                source_callsign = None
        else:
            source_callsign = None

        target_candidate = None
        if raw_for_parse and len(raw_for_parse) >= 13 and raw_for_parse[6] == '@':
            cand = raw_for_parse[7:13].strip().upper()
            if is_valid_callsign(cand):
                target_candidate = cand
        target_callsign = target_candidate

        is_self_targeted = (target_callsign is not None and target_callsign == self.callsign)

        total_bytes = len(text.encode('utf-8')) if text else 0
        entry = HistoryEntry(
            direction=direction, timestamp=timestamp, freq=freq, snr=snr,
            frames_count=frames_count, total_bytes=total_bytes,
            text=text,
            marker=marker, is_complete=not is_partial, slot_progress=slot_progress,
            is_partial=is_partial, session_id=session_id, crc_status=crc_status,
            source_callsign=source_callsign, target_callsign=target_callsign,
            i3=i3,
            total_frames=total_frames,
            total_bytes_all=None,
            is_beacon=is_beacon,
            grid6=grid6,
            is_self_targeted=is_self_targeted
        )
        self.add_history_entry(entry)

    def _add_send_history_realtime(self, freq, frames_count, total_frames, text, marker, slot_progress,
                                   is_partial=False, session_id=None, timestamp=None,
                                   total_bytes_all=None, is_beacon=False):
        if timestamp is None:
            timestamp = self.get_corrected_utc_now()
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
            is_beacon=is_beacon,
            is_self_targeted=False
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

    # ---------- Contact management ----------
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
                print(f"Load contacts error: {e}")
                self._safe_call('on_toast', _("Load contacts failed: {e}", e=e), "error")

    def _save_contacts(self):
        try:
            with open(self.contact_file, 'w', encoding='utf-8') as f:
                for callsign, note in self.contact_list[:MAX_CONTACTS]:
                    f.write(f"{callsign},{note}\n")
        except Exception as e:
            self._safe_call('on_log', _("Save contacts failed: {e}", e=e), "error")
            self._safe_call('on_toast', _("Save contacts failed: {e}", e=e), "error")

    def _contact_exists(self, callsign):
        callsign = callsign.strip().upper()
        for c, _note in self.contact_list:
            if c == callsign:
                return True
        return False

    def _add_contact(self, callsign, note=""):
        callsign = callsign.strip().upper()
        if not callsign or not is_valid_callsign(callsign):
            self._safe_call('on_toast', _("Callsign {call} invalid", call=callsign), "warning")
            return False
        if self._contact_exists(callsign):
            return True
        if len(self.contact_list) >= MAX_CONTACTS:
            self._safe_call('on_log',
                            _("Contact limit {n} reached, cannot add {call}",
                              n=MAX_CONTACTS, call=callsign),
                            "error")
            self._safe_call('on_toast',
                            _("Contact limit {n} reached", n=MAX_CONTACTS),
                            "error")
            return False
        note_encoded = note.encode('utf-8')
        if len(note_encoded) > MAX_NOTE_BYTES:
            note = note_encoded[:MAX_NOTE_BYTES].decode('utf-8', errors='ignore')
            self._safe_call('on_log',
                            _("Note too long, truncated to {n} bytes", n=MAX_NOTE_BYTES),
                            "warning")
        self.contact_list.append((callsign, note.strip()))
        self._save_contacts()
        self._safe_call('on_contact_updated', self.contact_list)
        self._safe_call('on_toast', _("Added contact {call}", call=callsign), "info")
        return True

    def add_contact(self, callsign, note=""):
        return self._add_contact(callsign, note)

    def delete_contact(self, index):
        if 0 <= index < len(self.contact_list):
            callsign = self.contact_list[index][0]
            del self.contact_list[index]
            self._save_contacts()
            self._safe_call('on_contact_updated', self.contact_list)
            self._safe_call('on_toast', _("Deleted contact {call}", call=callsign), "info")
            return True
        return False

    def update_contact(self, index, new_callsign, new_note):
        if 0 <= index < len(self.contact_list):
            new_callsign = new_callsign.strip().upper()
            if not is_valid_callsign(new_callsign):
                self._safe_call('on_toast',
                                _("Callsign {call} invalid", call=new_callsign),
                                "warning")
                return False
            for i, (c, _note) in enumerate(self.contact_list):
                if i != index and c == new_callsign:
                    self._safe_call('on_toast',
                                    _("Callsign {call} already exists", call=new_callsign),
                                    "warning")
                    return False
            note_encoded = new_note.encode('utf-8')
            if len(note_encoded) > MAX_NOTE_BYTES:
                new_note = note_encoded[:MAX_NOTE_BYTES].decode('utf-8', errors='ignore')
                self._safe_call('on_log',
                                _("Note too long, truncated to {n} bytes", n=MAX_NOTE_BYTES),
                                "warning")
            self.contact_list[index] = (new_callsign, new_note.strip())
            self._save_contacts()
            self._safe_call('on_contact_updated', self.contact_list)
            self._safe_call('on_toast', _("Updated contact {call}", call=new_callsign), "info")
            return True
        return False

    def get_contacts(self):
        return self.contact_list.copy()

    # ---------- Helpers ----------
    def get_wait_time_for_next_slot_start(self):
        t = self.get_corrected_timestamp()
        cycle = self.cycle_seconds
        wait = cycle - (t % cycle)
        if wait < 0.01:
            wait = cycle
        return wait

    def _interruptible_sleep(self, seconds, check_interval=0.1):
        elapsed = 0
        while elapsed < seconds and not self.stop_requested:
            time.sleep(min(check_interval, seconds - elapsed))
            elapsed += check_interval
        return not self.stop_requested

    def pause_receiver(self):
        if self.receive_paused:
            return
        self.receive_paused = True
        self._safe_call('on_log', _("Half-duplex: pause RX, start TX"), "halfduplex")
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
                                        _("Warning clearing buffer before pause: {e}", e=e),
                                        "warning")
                    self.audio_in.stream.stop_stream()
                    self._safe_call('on_log', _("Audio input paused and buffer cleared"), "halfduplex")
            except Exception as e:
                self._safe_call('on_log', _("Pause RX error: {e}", e=e), "error")
                self._safe_call('on_toast', _("Pause RX error: {e}", e=e), "error")

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
                                        _("Warning clearing buffer on resume: {e}", e=e),
                                        "warning")
                    self.audio_in.sync_pointer_to_wall_clock()
                    self._safe_call('on_log', _("Audio input resumed"), "halfduplex")
            except Exception as e:
                self._safe_call('on_log', _("Resume RX error: {e}", e=e), "error")
                self._safe_call('on_toast', _("Resume RX error: {e}", e=e), "error")
        self.receive_paused = False
        self._safe_call('on_log', _("Half-duplex: TX complete, resume RX"), "halfduplex")
        self._safe_call('on_status', False)

    def shutdown(self):
        sys.stdout = self._original_stdout
        sys.stderr = self._original_stderr
        self.stop_transmit()
        self.stop_receiver()
        self.save_config()
        if hasattr(self.audio_out, 'shutdown'):
            self.audio_out.shutdown()


if __name__ == "__main__":
    import tkinter as tk

    def main():
        from gui import GUI
        root = tk.Tk()
        core = Core()
        gui = GUI(root, core)
        core.start_ntp_sync()
        root.protocol("WM_DELETE_WINDOW",
                      lambda: (core.stop_receiver(), core.stop_transmit(), core.shutdown(), root.destroy()))
        root.mainloop()

    main()