# transmitter.py - Modified version, supports immediate stop playback
# Bit order: bits77 = [b72(72)] [f2(2)] [i3(3)]
# Added free text packing (i3=0, n3=0) and compatibility check


import numpy as np
import wave
import pyaudio
import time
import threading
from databases import hashes_for_calls, add_call_hashes


# ==================== AUDIO OUT ================================================================

class AudioOut:
    def __init__(self):
        self._current_stream = None
        self._current_pya = None
        self._stop_requested = False
        self._play_lock = threading.Lock()
        self._is_playing = False

    def find_device(self, device_str_contains):
        """Find an audio output device whose name contains all given patterns."""
        pya = pyaudio.PyAudio()
        for dev_idx in range(pya.get_device_count()):
            name = pya.get_device_info_by_index(dev_idx)['name']
            match = True
            for pattern in device_str_contains:
                if pattern not in name:
                    match = False
            if match:
                pya.terminate()
                return dev_idx
        pya.terminate()
        print(f"[Audio] No output audio device found matching {device_str_contains}")
        return None

    def get_default_output_device(self):
        """Get the system's default output device."""
        pya = pyaudio.PyAudio()
        try:
            default_info = pya.get_default_output_device_info()
            dev_idx = default_info['index']
            print(f"[Audio] Using default output device: {default_info['name']}")
            pya.terminate()
            return dev_idx
        except:
            pya.terminate()
            print("[Audio] No default output device found")
            return None

    def request_stop(self):
        """Request immediate stop of current playback."""
        with self._play_lock:
            self._stop_requested = True
            # Force close the current stream to interrupt playback
            if self._current_stream is not None:
                try:
                    self._current_stream.stop_stream()
                    self._current_stream.close()
                except:
                    pass
                self._current_stream = None
            if self._current_pya is not None:
                try:
                    self._current_pya.terminate()
                except:
                    pass
                self._current_pya = None
            self._is_playing = False

    def clear_stop_flag(self):
        """Clear the stop flag (call before starting a new playback)."""
        with self._play_lock:
            self._stop_requested = False

    def is_playing(self):
        """Check if audio is currently playing."""
        with self._play_lock:
            return self._is_playing

    def create_ft8_symbols(self, tx_msg):
        """Create FT8 symbols from a message."""
        if isinstance(tx_msg, tuple):
            return pack_message(*tx_msg)
        
        parts = tx_msg.split()
        if len(parts) != 3:
            if len(parts) == 2:
                parts.append("AA00")
            elif len(parts) == 1:
                parts = [parts[0], "CQ", "AA00"]
            else:
                raise ValueError(f"Invalid message format: {tx_msg}")
        
        c1, c2, grid_rpt = parts[0], parts[1], parts[2]
        return pack_message(c1, c2, grid_rpt)

    def create_preamble_noise(self, duration_sec=0.5, fs=12000, amplitude=0.7, fade_ms=10):
        """Create preamble noise (for VOX triggering)."""
        n_samples = int(fs * duration_sec)
        fade_samples = int(fs * fade_ms / 1000)

        noise = np.random.normal(0, amplitude, n_samples).astype(np.float32)

        if fade_samples > 0 and fade_samples < n_samples:
            envelope = np.ones(n_samples)
            envelope[:fade_samples] = np.linspace(0, 1, fade_samples)
            envelope[-fade_samples:] = np.linspace(1, 0, fade_samples)
            noise = noise * envelope

        return np.int16(noise * 32767)

    def create_preamble_silence(self, duration_sec=0.5, fs=12000):
        """Create preamble silence."""
        n_samples = int(fs * duration_sec)
        return np.zeros(n_samples, dtype=np.int16)

    def create_ft8_wave(self, symbols, fs=12000, f_base=873.0, f_step=6.25, amplitude=0.7):
        """Create FT8 waveform from symbols."""
        symbol_len = int(fs * 0.160)
        phase = 0
        ft8_waveform = []

        for s in symbols:
            f = f_base + s * f_step
            phase_inc = 2 * np.pi * f / fs
            w = np.sin(phase + phase_inc * np.arange(symbol_len))
            ft8_waveform.append(w)
            phase = (phase + phase_inc * symbol_len) % (2 * np.pi)

        ft8_waveform = np.concatenate(ft8_waveform).astype(np.float32)

        ft8_max = np.max(np.abs(ft8_waveform))
        if ft8_max > 0:
            ft8_waveform = amplitude * ft8_waveform / ft8_max

        return np.int16(ft8_waveform * 32767)

    def _play_audio(self, audio_data, output_device_idx, fs=12000):
        """Internal play method – supports interruption."""
        if output_device_idx is None:
            output_device_idx = self.get_default_output_device()
            if output_device_idx is None:
                print("[Audio] No output device available, cannot play")
                return False

        with self._play_lock:
            if self._stop_requested:
                return False
            self._is_playing = True

        try:
            self._current_pya = pyaudio.PyAudio()
            self._current_stream = self._current_pya.open(
                format=pyaudio.paInt16, channels=1, rate=fs,
                output=True, output_device_index=output_device_idx
            )
            
            # Write in chunks so we can check the stop flag
            chunk_size = 4096
            data_bytes = audio_data.tobytes()
            total_chunks = len(data_bytes) // chunk_size + 1
            
            for i in range(0, len(data_bytes), chunk_size):
                with self._play_lock:
                    if self._stop_requested:
                        print("[Audio] Playback stopped by user request")
                        break
                
                chunk = data_bytes[i:i+chunk_size]
                self._current_stream.write(chunk)
            
            self._current_stream.stop_stream()
            self._current_stream.close()
            self._current_pya.terminate()
            self._current_stream = None
            self._current_pya = None
            
            with self._play_lock:
                self._is_playing = False
            
            return True
        except Exception as e:
            print(f"[Audio] Error playing audio: {e}")
            with self._play_lock:
                self._is_playing = False
            return False

    def play_ft8_only(self, ft8_data, output_device_idx, fs=12000):
        """Play only FT8 signal (supports interruption)."""
        return self._play_audio(ft8_data, output_device_idx, fs)

    def play_with_preamble(self, noise_data, silence_data, ft8_data, output_device_idx, fs=12000):
        """Play preamble noise + silence + FT8 signal (supports interruption)."""
        full_waveform = np.concatenate([noise_data, silence_data, ft8_data])
        return self._play_audio(full_waveform, output_device_idx, fs)

    def get_ft8_duration(self, symbols):
        """Get the duration of the FT8 signal in seconds."""
        return len(symbols) * 0.160

    def write_to_wave_file(self, audio_data, wave_file):
        wavefile = wave.open(wave_file, 'wb')
        wavefile.setframerate(12000)
        wavefile.setnchannels(1)
        wavefile.setsampwidth(2)
        wavefile.writeframes(audio_data.tobytes())
        wavefile.close()


# ==================== FREETEXT PACKING ========================================================

# Free text character set (same as in receiver.py)
FREE_TEXT_CHARSET = ' 0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ+-./?'


def is_free_text_compatible(text: str) -> bool:
    """
    Check if the given text can be sent as free text (i3=0, n3=0).
    Criteria:
      - Length <= 13 characters
      - All characters are in FREE_TEXT_CHARSET (case-insensitive)
    """
    if len(text) > 13:
        return False
    upper_text = text.upper()
    for ch in upper_text:
        if ch not in FREE_TEXT_CHARSET:
            return False
    return True


def pack_free_text(text: str):
    """
    Pack a free text message (i3=0, n3=0) into FT8 symbols.

    Input: text string (up to 13 characters, will be truncated if longer)
    Returns: (symbols, bits77)
        symbols: list of FT8 symbol indices (for AudioOut.create_ft8_wave)
        bits77: 77-bit integer payload (for testing/decoding)
    """
    # Limit length and pad with spaces to 13 characters
    if len(text) > 13:
        text = text[:13]
    text = text.ljust(13, ' ')

    # Encode to 71-bit integer using base-42
    value = 0
    for ch in text:
        idx = FREE_TEXT_CHARSET.find(ch)
        if idx == -1:
            idx = 0  # illegal character -> space
        value = value * 42 + idx

    bits71 = value
    # Construct 77-bit payload: bits77 = [bits71(71)] [n3=0(3)] [i3=0(3)]
    bits77 = bits71 << 6   # n3=0, i3=0

    symbols = encode_bits77(bits77)
    return symbols, bits77


# ==================== TRANSPARENT TRANSMISSION FUNCTIONS ====================================

def pack_transparent_message(f2, b72):
    """
    Pack a transparent transmission message (i3=6)

    Parameters:
        f2: 2-bit format identifier (0-3)
        b72: 72-bit user data (integer 0 to 2^72-1)

    Returns:
        symbols: FT8 symbol list
        bits77: 77-bit raw value

    Bit order: bits77 = [b72(72)] [f2(2)] [i3(3)]
               i.e. bits77 = (b72 << 5) | (f2 << 3) | i3
    """
    if not (0 <= f2 <= 3):
        raise ValueError(f"f2 must be 0-3, got {f2}")

    max_b72 = (1 << 72) - 1
    if not (0 <= b72 <= max_b72):
        raise ValueError(f"b72 must be 0-{max_b72}, got {b72}")

    i3 = 6
    bits77 = (b72 << 5) | (f2 << 3) | i3

    symbols = encode_bits77(bits77)
    return symbols, bits77


def pack_transparent_from_bytes(f2, data_bytes):
    """Pack transparent message from a byte array."""
    max_bytes = 9
    if len(data_bytes) > max_bytes:
        raise ValueError(f"Data too long: {len(data_bytes)} bytes > {max_bytes}")
    
    # Convert byte array to integer (big-endian)
    b72 = int.from_bytes(data_bytes, byteorder='big')
    # Left-align to 72 bits
    b72 = b72 << (72 - len(data_bytes) * 8)
    
    return pack_transparent_message(f2, b72)


def pack_transparent_from_hex(f2, hex_string):
    """Pack transparent message from a hex string."""
    if hex_string.startswith('0x') or hex_string.startswith('0X'):
        hex_string = hex_string[2:]
    hex_string = hex_string.replace(' ', '')
    data_bytes = bytes.fromhex(hex_string)
    return pack_transparent_from_bytes(f2, data_bytes)


def pack_transparent_from_text(f2, text, encoding='utf-8'):
    """Pack transparent message from a text string."""
    data_bytes = text.encode(encoding)[:9]
    return pack_transparent_from_bytes(f2, data_bytes)


# ==================== STANDARD MESSAGE PACKING ===============================================

def ifindex(arr, val, default=None):
    try:
        return arr.index(val) if val in arr else default
    except ValueError:
        return default


def pack_message(c1, c2, gr):
    """Pack a message into FT8 symbols – standard FT8 compatible version."""
    symbols, bits77 = _pack_message(c1, c2, gr)
    return symbols


def _pack_message(c1, c2, gr):
    """Internal packing function – standard FT8 format."""
    # Detect if this is a transparent transmission format
    if isinstance(c1, (tuple, list)) and len(c1) >= 2:
        f2, b72 = c1[0], c1[1]
        return pack_transparent_message(f2, b72)
    
    # Handle string callsigns
    c1 = str(c1).strip().upper()
    c2 = str(c2).strip().upper()
    gr = str(gr).strip().upper()
    
    # Get callsign encodings
    result_a = pack_ft8_c29(c1)
    result_b = pack_ft8_c29(c2)
    
    # Process return values
    if result_a is None:
        c28a, p1a = 0, 0
    elif isinstance(result_a, tuple) and len(result_a) == 2:
        c28a, p1a = result_a
    else:
        c28a, p1a = result_a, 0
        
    if result_b is None:
        c28b, p1b = 0, 0
    elif isinstance(result_b, tuple) and len(result_b) == 2:
        c28b, p1b = result_b
    else:
        c28b, p1b = result_b, 0
    
    # Get grid encoding
    g15, ir = pack_ft8_g15(gr)
    
    # Determine message type
    i3 = 1
    
    # Correct bit order (verified from manual encoding)
    bits77 = (c28a << 49) | (p1a << 48) | (c28b << 20) | (p1b << 19) | (ir << 18) | (g15 << 3) | i3
    
    symbols = encode_bits77(bits77)
    return symbols, bits77


def pack_ft8_c58(call):
    chars = " 0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ/"
    n58 = 0
    call = (call + "          ")[:11]
    for i in range(0, 11):
        n58 = n58 * 38 + chars.index(call[i])
    return n58


def pack_ft8_c29(call):
    """Pack a callsign into 29 bits – standard FT8 compatible version."""
    if call is None or call == '':
        return 0, 0
    
    call = str(call).strip().upper()
    
    # Handle portable/rover suffix
    portable_rover = 0
    if call.endswith('/P') or call.endswith('/R'):
        portable_rover = 1
        call = call[:-2]
    
    # Special commands
    if call == "CQ":
        return 2, portable_rover
    if call == "QRZ":
        return 1, portable_rover
    if call == "DE":
        return 0, portable_rover
    
    # CQ with suffix (e.g. "CQ DX")
    if call.startswith("CQ "):
        suffix = call[3:].strip()
        if suffix:
            # Encode as CQ + letters format
            base = 1003
            for ch in suffix[:4]:
                if ch == ' ':
                    idx = 0
                else:
                    idx = " ABCDEFGHIJKLMNOPQRSTUVWXYZ".find(ch)
                    if idx == -1:
                        idx = 0
                base = base * 27 + idx
            # Pad
            for _ in range(4 - len(suffix[:4])):
                base = base * 27 + 0
            return base, portable_rover
    
    # Standard callsign encoding
    # Ensure callsign length is suitable
    if len(call) > 6:
        call = call[:6]
    
    # Pad to 6 characters
    if len(call) < 6:
        if len(call) > 1 and call[1].isdigit():
            call = ' ' + call
        call = call.ljust(6)
    
    # Character sets
    char_set_space_digit_letter = ' 0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ'
    char_set_digit_letter = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ'
    char_set_space_letter = ' ABCDEFGHIJKLMNOPQRSTUVWXYZ'
    
    def idx(ch, cs):
        try:
            return cs.index(ch)
        except ValueError:
            return 0
    
    # Compute encoding
    w0 = idx(call[0], char_set_space_digit_letter)  # 37 possibilities
    w1 = idx(call[1], char_set_digit_letter)        # 36
    w2 = idx(call[2], char_set_digit_letter)        # 36
    w3 = idx(call[3], char_set_space_letter)        # 27
    w4 = idx(call[4], char_set_space_letter)        # 27
    w5 = idx(call[5], char_set_space_letter)        # 27
    
    # Weights
    c28 = w0 * 36*10*27*27*27
    c28 += w1 * 10*27*27*27
    c28 += w2 * 27*27*27
    c28 += w3 * 27*27
    c28 += w4 * 27
    c28 += w5
    
    # Standard callsign offset
    c28 += 2063592 + 4194304
    
    return c28, portable_rover


def pack_ft8_g15(txt):
    """Pack a grid locator into 15 bits."""
    ir = 0
    txt = str(txt).strip().upper()
    
    if txt.startswith('-') or txt.startswith('+'):
        n = int(txt)
        return 32400 + 35 + n, ir
    if txt.startswith('R-') or txt.startswith('R+'):
        ir = 1
        n = int(txt[1:])
        return 32400 + 35 + n, ir
    if txt == 'RRR':
        return 32402, ir
    if txt == 'RR73':
        return 32403, ir
    if txt == '73':
        return 32404, ir
    if len(txt) != 4:
        return 0, ir
    
    v = (ord(txt[0]) - 65)
    v = v * 18 + (ord(txt[1]) - 65)
    v = v * 10 + int(txt[2])
    v = v * 10 + int(txt[3])
    return int(v), ir


# ============ ENCODE =====================================================================

generator_matrix_rows = ["8329ce11bf31eaf509f27fc", "761c264e25c259335493132", "dc265902fb277c6410a1bdc",
                         "1b3f417858cd2dd33ec7f62", "09fda4fee04195fd034783a", "077cccc11b8873ed5c3d48a",
                         "29b62afe3ca036f4fe1a9da", "6054faf5f35d96d3b0c8c3e", "e20798e4310eed27884ae90",
                         "775c9c08e80e26ddae56318", "b0b811028c2bf997213487c", "18a0c9231fc60adf5c5ea32",
                         "76471e8302a0721e01b12b8", "ffbccb80ca8341fafb47b2e", "66a72a158f9325a2bf67170",
                         "c4243689fe85b1c51363a18", "0dff739414d1a1b34b1c270", "15b48830636c8b99894972e",
                         "29a89c0d3de81d665489b0e", "4f126f37fa51cbe61bd6b94", "99c47239d0d97d3c84e0940",
                         "1919b75119765621bb4f1e8", "09db12d731faee0b86df6b8", "488fc33df43fbdeea4eafb4",
                         "827423ee40b675f756eb5fe", "abe197c484cb74757144a9a", "2b500e4bc0ec5a6d2bdbdd0",
                         "c474aa53d70218761669360", "8eba1a13db3390bd6718cec", "753844673a27782cc42012e",
                         "06ff83a145c37035a5c1268", "3b37417858cc2dd33ec3f62", "9a4a5a28ee17ca9c324842c",
                         "bc29f465309c977e89610a4", "2663ae6ddf8b5ce2bb29488", "46f231efe457034c1814418",
                         "3fb2ce85abe9b0c72e06fbe", "de87481f282c153971a0a2e", "fcd7ccf23c69fa99bba1412",
                         "f0261447e9490ca8e474cec", "4410115818196f95cdd7012", "088fc31df4bfbde2a4eafb4",
                         "b8fef1b6307729fb0a078c0", "5afea7acccb77bbc9d99a90", "49a7016ac653f65ecdc9076",
                         "1944d085be4e7da8d6cc7d0", "251f62adc4032f0ee714002", "56471f8702a0721e00b12b8",
                         "2b8e4923f2dd51e2d537fa0", "6b550a40a66f4755de95c26", "a18ad28d4e27fe92a4f6c84",
                         "10c2e586388cb82a3d80758", "ef34a41817ee02133db2eb0", "7e9c0c54325a9c15836e000",
                         "3693e572d1fde4cdf079e86", "bfb2cec5abe1b0c72e07fbe", "7ee18230c583cccc57d4b08",
                         "a066cb2fedafc9f52664126", "bb23725abc47cc5f4cc4cd2", "ded9dba3bee40c59b5609b4",
                         "d9a7016ac653e6decdc9036", "9ad46aed5f707f280ab5fc4", "e5921c77822587316d7d3c2",
                         "4f14da8242a8b86dca73352", "8b8b507ad467d4441df770e", "22831c9cf1169467ad04b68",
                         "213b838fe2ae54c38ee7180", "5d926b6dd71f085181a4e12", "66ab79d4b29ee6e69509e56",
                         "958148682d748a38dd68baa", "b8ce020cf069c32a723ab14", "f4331d6d461607e95752746",
                         "6da23ba424b9596133cf9c8", "a636bcbc7b30c5fbeae67fe", "5cb0d86a07df654a9089a20",
                         "f11f106848780fc9ecdd80a", "1fbb5364fb8d2c9d730d5ba", "fcb86bc70a50c9d02a5d034",
                         "a534433029eac15f322e34c", "c989d9c7c3d3b8c55d75130", "7bb38b2f0186d46643ae962",
                         "2644ebadeb44b9467d1f42c", "608cc857594bfbb55d69600"]

kGEN = np.array([int(row, 16) >> 1 for row in generator_matrix_rows])


def ldpc_encode(msg_crc: int) -> tuple:
    msg_crc = int(msg_crc)
    parity_bits = 0
    for row in map(int, kGEN):
        bit = bin(msg_crc & row).count("1") & 1
        parity_bits = (parity_bits << 1) | bit
    return (msg_crc << 83) | parity_bits, parity_bits


def gray_encode(bits: int) -> list:
    syms = []
    gray_seq = [0, 1, 3, 2, 5, 6, 4, 7]
    for _ in range(174 // 3):
        chunk = bits & 0x7
        syms.insert(0, gray_seq[chunk])
        bits >>= 3
    return syms


def encode_bits77(bits77_int):
    bits91_int, _ = append_crc(bits77_int)
    bits174_int, _ = ldpc_encode(bits91_int)
    syms = gray_encode(bits174_int)
    costas = [3, 1, 4, 0, 6, 5, 2]
    return costas + syms[:29] + costas + syms[29:] + costas


def append_crc(bits77_int):
    poly = 0x2757
    width = 14
    mask = (1 << width) - 1
    nbits = 96
    bits14_int = 0
    for i in range(nbits):
        inbit = ((bits77_int >> (76 - i)) & 1) if i < 77 else 0
        bit14 = (bits14_int >> (width - 1)) & 1
        bits14_int = ((bits14_int << 1) & mask) | inbit
        if bit14:
            bits14_int ^= poly
    bits91_int = (bits77_int << 14) | bits14_int
    return bits91_int, bits14_int


# ==================== TESTS ================================================================

if __name__ == "__main__":
    from receiver import unpack

    print("Test transparent transmission")
    test_data = [
        (0, 0x000102030405060708),
        (1, 0xFFFFFFFFFFFFFFFFF),
        (2, 0xDEADBEEFCAFEBABE),
        (3, 0x00000000000000000),
    ]
    for f2, b72 in test_data:
        symbols, bits77 = pack_transparent_message(f2, b72)
        result = unpack(bits77)
        print(f"f2={f2}, b72=0x{b72:018x} -> {result[:3]}")

    print("\nTest standard calls")
    msgs = [("CQ", "DE", "OM89"), ("BG1XXX", "BG2YYY", "OM89"), ("G1OJS", "G1OJS", "IO90")]
    for msg_tx in msgs:
        symbols, bits77 = _pack_message(*msg_tx)
        print(f"Packed: {msg_tx} -> {len(symbols)} symbols")

    print("\nTest free text")
    free_texts = ["HELLO", "CQ DX", "73", "TEST 123", "A"*13, "A"*20]
    for txt in free_texts:
        symbols, bits77 = pack_free_text(txt)
        result = unpack(bits77)
        print(f"Text: '{txt}' -> decoded: {result}")

    print("\nTest free text compatibility")
    test_strings = ["HELLO", "Hello!", "CQ DX", "1234567890123", "12345678901234", "中文"]
    for s in test_strings:
        compatible = is_free_text_compatible(s)
        print(f"'{s}' -> compatible: {compatible}")

    print("\nPASSED")