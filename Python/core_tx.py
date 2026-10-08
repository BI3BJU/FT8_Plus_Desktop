# core_tx.py - TxMixin：发送（自由文本 / 透明帧 / 中断）
import time
import threading

from i18n import _, MARKER_FREE_TEXT, MARKER_SINGLE, MARKER_BEACON, MARKER_INTERRUPT
from ft8_constants import PROTOCOL_PAD_BYTE, PROTOCOL_EOT_BYTE, BEACON_PATTERN
from ft8_crc import crc8
from transmitter import (
    pack_transparent_message, pack_free_text, is_free_text_compatible,
)


class TxMixin:
    def transmit_text(self, text, freq, start_slot=None):
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
        threading.Thread(target=self._transmit_worker,
                         args=(text, freq, start_slot), daemon=True).start()

    def _transmit_worker(self, text, freq, start_slot=None):
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
                self._send_free_text(filtered_str, freq, start_slot=start_slot)
                return

            raw_data = filtered_str.encode('utf-8')
            raw_len = len(raw_data)
            if raw_len > self.max_raw_data_bytes:
                raise ValueError(_("UTF-8 encoded {n} bytes, exceeds {max} bytes limit",
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
                    raise ValueError(_("Data too long: {n} frames needed, exceeds {max} limit",
                                       n=len(blocks), max=self.max_frames))
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
                self._safe_call('on_log', _("Single frame mode: f2=0, 0x20 padding, no CRC8/EOT"), "info")
            else:
                self._safe_call('on_log', _("Multi frame mode: f2=1, 9 bytes per frame"), "info")
                self._safe_call('on_log', _("Payload = raw + 0x20 padding + CRC8 + EOT(0x04)"), "info")

            self._transmit_frames(frames, freq, total_frames, display_text, raw_data,
                                  start_slot=start_slot)

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

    def _send_free_text(self, text, freq, start_slot=None):
        # FT8 free-text (i3=0) only carries the 42-char uppercase set.
        # Normalize to uppercase here, before logging / history / packing,
        # so the displayed text matches what is actually transmitted and
        # received. Lowercase letters would otherwise be encoded as spaces
        # by pack_free_text() (find() returns -1 for chars outside the set).
        text = text.upper()
        session_id = f"free_send_{int(time.time()*1000)}"
        raw_data = text.encode('utf-8')
        total_bytes_all = len(raw_data)

        # Detect beacon text: <CALL>+{1,}PLUS
        is_beacon = bool(BEACON_PATTERN.match(text.strip())) if text else False
        free_text_marker = MARKER_BEACON if is_beacon else MARKER_FREE_TEXT

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
                marker=free_text_marker,
                slot_progress="0/1",
                is_partial=True,
                session_id=session_id,
                timestamp=slot_start_dt,
                total_bytes_all=total_bytes_all
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
                    marker=free_text_marker,
                    slot_progress="1/1",
                    is_partial=False,
                    session_id=session_id,
                    timestamp=slot_start_dt,
                    total_bytes_all=total_bytes_all
                )
            elif self.stop_requested:
                # Manual stop: mark entry red with stable token.
                self._safe_call('on_log', _("TX stopped by user"), "info")
                self._safe_call('on_toast', _("TX stopped"), "warning")
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
                    total_bytes_all=total_bytes_all
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
                total_bytes_all=total_bytes_all
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

        # Detect beacon text
        is_beacon = bool(BEACON_PATTERN.match(display_text.strip())) if display_text else False

        self._safe_call('on_tx_progress',
                        _("Waiting slot... (total {n} frames)", n=total_frames))

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
                    # Manual stop (by user): use stable code token so the
                    # GUI can reliably color the entry red regardless of
                    # the current language.
                    final_marker = MARKER_INTERRUPT
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
