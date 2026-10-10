# core_receiver.py - ReceiverMixin：接收机启停 / 半双工
import time

from i18n import _
from receiver import AudioIn, Receiver


class ReceiverMixin:
    def start_receiver(self):
        try:
            freq_start = self.fixed_freq_start
            freq_end = self.fixed_freq_end
            if freq_start >= freq_end:
                self._safe_call('on_log', _("Error: start freq must be less than end freq"), "error")
                self._safe_call('on_toast', _("Freq range error"), "error")
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
            self._safe_call('on_log', _("Start error: {e}", e=e), "error")
            self._safe_call('on_toast', _("Receiver start failed: {e}", e=e), "error")
            print(_("Start error: {e}", e=e))

    def stop_receiver(self):
        self._safe_call('on_log', _("Stopping receiver..."), "info")
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

    # ---------- Beacon ----------
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

