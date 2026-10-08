# core_rx.py - RxMixin：接收回调 / 透明帧缓冲
from i18n import _, MARKER_FREE_TEXT, MARKER_SINGLE
from ft8_constants import FREQ_GROUP_TOLERANCE, PROTOCOL_PAD_BYTE
from ft8_models import TransparentBuffer


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

    # ---------- Callsign parsing ----------
    # ---------- Callsign parsing ----------
