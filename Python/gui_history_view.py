# gui_history_view.py - HistoryViewMixin：历史显示
import os
import json
import time
import tkinter as tk
from datetime import datetime

from main import HistoryEntry
from i18n import _, MARKER_FREE_TEXT, MARKER_BEACON, MARKER_INTERRUPT


class HistoryViewMixin:
    def _write_history_entry_to_file(self, entry):
        data = {
            'ts': entry.timestamp.strftime("%Y-%m-%d %H:%M:%S") if entry.timestamp else None,
            'dir': entry.direction,
            'freq': entry.freq,
            'text': entry.text,
            'marker': entry.marker,
            'partial': entry.is_partial,
            'crc': entry.crc_status,
            'src': entry.source_callsign,
            'tgt': entry.target_callsign,
            'frames': entry.frames_count,
            'total': entry.total_frames if entry.total_frames is not None else 1,
            'note': getattr(entry, 'contact_note', None),
        }
        line = json.dumps(data, ensure_ascii=False)
        self._append_text_line(self.history_log_path, line)

    def _load_history_log(self):
        if not os.path.exists(self.history_log_path):
            return
        try:
            with open(self.history_log_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            lines = lines[-self.max_log_lines:]
            idx = 0
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    timestamp = None
                    if data.get('ts'):
                        try:
                            timestamp = datetime.strptime(data['ts'], "%Y-%m-%d %H:%M:%S")
                        except Exception:
                            timestamp = datetime.now()
                    idx += 1
                    session_id = f"load_{idx}_{int(time.time()*1000)}_{data.get('ts', '')}"
                    entry = HistoryEntry(
                        direction=data.get('dir', 'recv'),
                        timestamp=timestamp,
                        freq=data.get('freq', 0),
                        snr=None,
                        frames_count=data.get('frames', 0),
                        total_bytes=len(data.get('text', '').encode('utf-8')),
                        text=data.get('text', ''),
                        marker=data.get('marker', ''),
                        is_complete=not data.get('partial', True),
                        slot_progress=None,
                        is_partial=data.get('partial', False),
                        session_id=session_id,
                        crc_status=data.get('crc'),
                        source_callsign=data.get('src'),
                        target_callsign=data.get('tgt'),
                        i3=None,
                        total_frames=data.get('total', 1),
                        total_bytes_all=len(data.get('text', '').encode('utf-8')),
                        contact_note=data.get('note'),
                    )
                    self.core.history_entries.append(entry)
                    self._append_history_entry(entry)
                except json.JSONDecodeError:
                    continue
        except Exception as e:
            print(f"Failed to load history log: {e}")

    def _add_history_entry(self, entry):
        self._append_history_entry(entry)
        self.history_text.see(tk.END)
        if not entry.is_partial:
            self._write_history_entry_to_file(entry)

    def _get_history_tags(self, entry):
        # Beacon takes precedence over other markers.
        # Sent beacon: all green (header + body).
        # Received beacon: all orange (header + body).
        if entry.marker == MARKER_BEACON:
            if entry.direction == 'recv':
                return "beacon_recv_header", "beacon_recv_text"
            else:
                return "beacon_send_header", "beacon_send_text"
        # Manual stop (any TX): red.
        if entry.direction == 'send' and entry.marker == MARKER_INTERRUPT:
            return "send_fail_header", "send_fail_text"
        if entry.direction == 'recv':
            if entry.is_partial:
                return "recv_receiving_header", "recv_receiving_text"
            else:
                if entry.crc_status in ("CRC OK", "No checksum", "No_checksum") or entry.crc_status is None:
                    if entry.marker == MARKER_FREE_TEXT:
                        return "recv_free_text_header", "recv_free_text_text"
                    else:
                        return "recv_frame_ok_header", "recv_frame_ok_text"
                else:
                    return "recv_fail_header", "recv_fail_text"
        else:
            if entry.is_partial:
                return "send_sending_header", "send_sending_text"
            else:
                if entry.marker and any(kw in entry.marker for kw in ("Interrupted", "Exception", "Cancel", "Fail")):
                    return "send_fail_header", "send_fail_text"
                else:
                    return "send_complete_header", "send_complete_text"

    def _append_history_entry(self, entry):
        self.history_text.config(state=tk.NORMAL)
        tag_name = f"hist_{entry.direction}_{entry.session_id}"
        ranges = self.history_text.tag_ranges(tag_name)

        if ranges:
            start_pos = ranges[0]
            self.history_text.delete(ranges[0], ranges[-1])
        else:
            start_pos = self.history_text.index("end")

        align_tag = "history_right" if entry.direction == 'send' else "history_left"

        header_tag, content_tag = self._get_history_tags(entry)

        # Determine whether the local station's own callsign is involved.
        # Beacon entries keep their dedicated color; skip self-highlight.
        is_me_involved = False
        if entry.direction == 'recv' and self.core.callsign and entry.marker != MARKER_BEACON:
            is_me_involved = (
                entry.source_callsign == self.core.callsign or
                entry.target_callsign == self.core.callsign
            )
        if is_me_involved:
            header_tag = "self_header"

        pos = start_pos
        total_chars = 0

        def insert_text(text, tags=()):
            nonlocal pos, total_chars
            if not text:
                return
            new_tags = tags + (align_tag,) if isinstance(tags, tuple) else (align_tag,)
            self.history_text.insert(pos, text, new_tags)
            total_chars += len(text)
            pos = self.history_text.index(f"{start_pos} + {total_chars} chars")

        timestamp_to_use = entry.timestamp
        if entry.direction == 'send' and entry.session_id:
            if entry.session_id not in self._history_first_timestamp:
                self._history_first_timestamp[entry.session_id] = entry.timestamp
            else:
                timestamp_to_use = self._history_first_timestamp[entry.session_id]

        time_str = timestamp_to_use.strftime("%Y-%m-%d %H:%M:%S") if timestamp_to_use else ""

        dir_str = "[TX]" if entry.direction == 'send' else "[RX]"

        # Header type tag.
        # - beacon (complete): 📡
        # - manually stopped (any TX): "Manual stop" status tag
        # - free text / single / continuous: normal
        if entry.marker == MARKER_BEACON:
            type_tag = "📡"
        elif entry.marker == MARKER_FREE_TEXT:
            type_tag = _("Free text")
        elif entry.direction == 'recv' and entry.is_partial:
            type_tag = _("Continuous")
        elif entry.direction == 'send' and entry.marker == MARKER_INTERRUPT:
            type_tag = _("Manual stop")
        else:
            if entry.frames_count > 1 or (entry.total_frames and entry.total_frames > 1):
                type_tag = _("Continuous")
            else:
                type_tag = _("Single")
        type_str = f"[{type_tag}]"
        freq_str = f"[{entry.freq:.0f}Hz]" if entry.freq is not None else ""

        status_str = ""
        if entry.direction == 'send' and entry.marker == MARKER_INTERRUPT:
            status_str = f"[{_('Manual stop')}]"
        elif type_tag == _("Continuous"):
            if entry.direction == 'recv':
                if entry.is_partial:
                    status_str = f"[{_('Receiving')}]"
                else:
                    if entry.crc_status in ("CRC OK", "No checksum", "No_checksum"):
                        status_str = f"[{_('CRC OK')}]"
                    elif entry.crc_status in ("CRC fail", "CRC失败") or "CRC失败" in str(entry.crc_status):
                        status_str = f"[{_('CRC failed')}]"
                    elif entry.crc_status in ("Timeout", "timeout"):
                        status_str = f"[{_('Receive timeout')}]"
                    else:
                        status_str = f"[{entry.marker}]"
            else:
                if entry.is_partial:
                    status_str = f"[{_('Sending')}]"
                else:
                    if entry.marker and any(kw in entry.marker for kw in ("Interrupted", "Exception", "Cancel", "Fail")):
                        status_str = f"[{_('Interrupted')}]"
                    else:
                        status_str = f"[{_('Send complete')}]"

        progress_str = ""
        if type_tag == _("Continuous") and entry.total_frames is not None and entry.total_frames > 1:
            if entry.direction == 'recv':
                progress_str = "[" + _("Received {n} frames {b} bytes",
                                       n=entry.frames_count, b=entry.total_bytes) + "]"
            else:
                total_f = entry.total_frames if entry.total_frames is not None else 1
                total_b = entry.total_bytes_all if entry.total_bytes_all is not None else entry.total_bytes
                progress_str = _("[{n}/{m} frames] [{b}/{tb} bytes]",
                                 n=entry.frames_count, m=total_f, b=entry.total_bytes, tb=total_b)

        header_parts = [f"[{time_str}]", dir_str, type_str, freq_str, status_str, progress_str]
        header_parts = [p for p in header_parts if p]
        header = ' '.join(header_parts).strip()

        insert_text(header + "\n", (header_tag, tag_name))

        # Contact-note line, only for received messages whose sender is known.
        # For received beacon entries, use the beacon orange color so the
        # note line matches the header and body color.
        if entry.direction == 'recv' and entry.source_callsign:
            note = getattr(entry, 'contact_note', None)
            if not note:
                note = self._find_contact_note(entry.source_callsign)
            if note:
                note_tag = "beacon_recv_text" if entry.marker == MARKER_BEACON else "contact_note"
                insert_text(f"[{note}]\n", (note_tag, tag_name))

        # Body text: for beacon entries display only the callsign.
        # Sent beacon: local callsign. Received beacon: source callsign.
        # For manual-stop entries: show the raw text as it was.
        if entry.marker == MARKER_BEACON:
            if entry.direction == 'recv':
                beacon_call = entry.source_callsign or "?"
            else:
                beacon_call = self.core.callsign or "?"
            display_text = beacon_call
        else:
            display_text = entry.text

        for line in self._wrap_text(display_text, 60):
            insert_text(line + "\n", (content_tag, tag_name))

        end_pos = self.history_text.index(f"{start_pos} + {total_chars} chars")
        self.history_text.tag_add(align_tag, start_pos, end_pos)
        self.history_text.tag_raise(align_tag)

        if is_me_involved:
            self.history_text.tag_add("self_highlight", start_pos, end_pos)
            self.history_text.tag_raise("self_highlight")

        self.history_text.config(state=tk.DISABLED)
        self.history_text.see(tk.END)

    def _refresh_history_display(self):
        self._history_first_timestamp.clear()
        self.history_text.config(state=tk.NORMAL)
        self.history_text.delete(1.0, tk.END)
        for entry in self.core.history_entries:
            self._append_history_entry(entry)
        self.history_text.config(state=tk.DISABLED)

    def _wrap_text(self, text, width):
        return [text[i:i+width] for i in range(0, len(text), width)] if text else [""]

    def _show_history_menu(self, event):
        try:
            self.history_context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.history_context_menu.grab_release()

    def _copy_history(self):
        try:
            text = self.history_text.get(tk.SEL_FIRST, tk.SEL_LAST)
        except tk.TclError:
            text = self.history_text.get("1.0", tk.END)
        if text:
            self.root.clipboard_clear()
            self.root.clipboard_append(text)

    def _clear_history(self):
        self.core.history_entries.clear()
        self._history_first_timestamp.clear()
        self._refresh_history_display()
        if os.path.exists(self.history_log_path):
            try:
                os.remove(self.history_log_path)
            except Exception as e:
                self._insert_log(_("Failed to delete history file: {e}", e=e), "error")
        self._insert_log(_("History cleared, deleted history.txt"), "info")

