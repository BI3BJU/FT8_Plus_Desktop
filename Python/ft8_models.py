# ft8_models.py - UTF-8 流解码 / 透明帧缓冲 / 历史条目
import threading
import time

from ft8_crc import crc8
from ft8_constants import PROTOCOL_EOT_BYTE, PROTOCOL_PAD_BYTE


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
                 i3=None, total_frames=None, total_bytes_all=None,
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
        self.total_frames = total_frames
        self.total_bytes_all = total_bytes_all
        self.is_self_targeted = is_self_targeted
        self.contact_note = contact_note


