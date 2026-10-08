# ft8_audio_out.py - 带白噪声注入与可中断播放的 AudioOut
import numpy as np
import pyaudio

from transmitter import AudioOut
from i18n import _


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
            print(_("White noise playback exception: {e}", e=e))
            import traceback
            traceback.print_exc()
            return False

    def shutdown(self):
        if self._pyaudio is not None:
            self._pyaudio.terminate()
            self._pyaudio = None
