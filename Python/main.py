# main.py - 兼容重导出 + 程序启动
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 向后兼容：from main import Core / HistoryEntry / TransparentBuffer / is_valid_callsign / crc8 ...
from core import Core, StdoutRedirector
from ft8_models import HistoryEntry, TransparentBuffer, UTF8StreamDecoder
from ft8_callsign import (
    is_valid_callsign,
    extract_source_callsign,
    extract_target_callsign,
    parse_message_callsigns,
)
from ft8_crc import crc8
from ft8_audio_out import CustomAudioOut
from ft8_constants import (
    MAX_RAW_DATA_BYTES, MAX_TOTAL_BYTES, MAX_FRAMES,
    FIXED_MAX_HISTORY, FIXED_MAX_MESSAGES,
    FIXED_FREQ_START, FIXED_FREQ_END,
    FIXED_DELAY_SLOTS, FIXED_DELAY_SECONDS,
    MAX_ACTIVE_BUFFERS, MAX_CONTACTS, MAX_NOTE_BYTES,
    FREQ_GROUP_TOLERANCE, PROTOCOL_PAD_BYTE, PROTOCOL_EOT_BYTE,
    BEACON_PATTERN,
)

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


if __name__ == "__main__":
    import tkinter as tk

    def main():
        from gui import GUI
        root = tk.Tk()
        core = Core()
        gui = GUI(root, core)
        core.start_ntp_sync()
        root.protocol("WM_DELETE_WINDOW",
                      lambda: (core.stop_receiver(), core.stop_transmit(),
                               core.shutdown(), root.destroy()))
        root.mainloop()

    main()
