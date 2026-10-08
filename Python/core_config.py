# core_config.py - ConfigMixin：配置读写
import json

from i18n import _
from ft8_callsign import is_valid_callsign


class ConfigMixin:
    def load_config(self):
        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                config = json.load(f)
            raw_callsign = config.get('callsign', '').strip().upper()
            if is_valid_callsign(raw_callsign):
                self.callsign = raw_callsign
            else:
                self.callsign = ""
                self._safe_call('on_log',
                                _("Invalid callsign: {callsign}, cleared", callsign=raw_callsign),
                                "warning")
                self._safe_call('on_toast', _("Invalid callsign, cleared"), "warning")
            tx_freq = config.get('tx_freq', '1500')
            try:
                val = int(float(tx_freq))
                if 300 <= val <= 3000:
                    self.tx_freq = val
            except Exception:
                pass
            self.preamble_noise_enabled = config.get('preamble_noise', False)
            self._safe_call('on_log', _("Config loaded"), "info")
        except Exception as e:
            self._safe_call('on_log',
                            _("Config load failed: {e}, using defaults", e=e),
                            "error")
            self._safe_call('on_toast', _("Config load failed, using defaults"), "error")
            self._apply_defaults()

    def save_config(self):
        if self.callsign and not is_valid_callsign(self.callsign):
            self._safe_call('on_log', _("Attempted to save invalid callsign, ignored"), "warning")
            self._safe_call('on_toast', _("Invalid callsign, save ignored"), "warning")
            return
        config = {
            'callsign': self.callsign,
            'tx_freq': str(self.tx_freq),
            'preamble_noise': self.preamble_noise_enabled,
        }
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(_("Save config error: {e}", e=e))
            self._safe_call('on_toast', _("Save config failed: {e}", e=e), "error")

    def _apply_defaults(self):
        self.callsign = ""
        self.tx_freq = 1500
        self.preamble_noise_enabled = False

    def set_preamble_noise(self, value):
        self.preamble_noise_enabled = value
        self.save_config()
        state = _("enabled") if value else _("disabled")
        self._safe_call('on_log', _("Preamble noise {state}", state=state), "info")
        self._safe_call('on_toast', _("Preamble noise {state}", state=state), "info")

