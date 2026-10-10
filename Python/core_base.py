# core_base.py - CoreBase：__init__ / 基础工具 / StdoutRedirector
import sys
import threading
import time

from i18n import _
from ft8_constants import (
    MAX_RAW_DATA_BYTES, MAX_TOTAL_BYTES, MAX_FRAMES,
    FIXED_MAX_HISTORY, FIXED_MAX_MESSAGES,
    FIXED_FREQ_START, FIXED_FREQ_END,
    FIXED_DELAY_SLOTS, FIXED_DELAY_SECONDS,
    MAX_ACTIVE_BUFFERS,
)
from ft8_audio_out import CustomAudioOut


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
        self.beacon_text = ""
        self.beacon_freq = 1500

        self.config_file = "config.txt"
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
    def set_callbacks(self, **kwargs):
        for key, func in kwargs.items():
            if key in self._callbacks:
                self._callbacks[key] = func

    def _safe_call(self, key, *args, **kwargs):
        func = self._callbacks.get(key)
        if func:
            func(*args, **kwargs)

    # ---------- Receiver ----------
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




