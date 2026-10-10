# core_history.py - HistoryMixin：历史记录 + 呼号提取委托
from i18n import _, MARKER_BEACON
from ft8_constants import BEACON_PATTERN
from ft8_callsign import (
    is_valid_callsign, extract_source_callsign, extract_target_callsign,
)
from ft8_models import HistoryEntry


class HistoryMixin:
    def _upsert_history_entry(self, direction, freq, snr, frames_count, total_frames,
                              text, marker, slot_progress, is_partial=False, session_id=None,
                              crc_status=None, timestamp=None, source_callsign=None,
                              target_callsign=None, i3=None,
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
            i3=i3,
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

    # ---------- Contact management ----------
    def _extract_source_callsign(self, raw_text):
        return extract_source_callsign(raw_text)

    def _extract_target_callsign(self, raw_text):
        return extract_target_callsign(raw_text)

    def _parse_message_callsigns(self, raw_text):
        return (extract_source_callsign(raw_text),
                extract_target_callsign(raw_text))

