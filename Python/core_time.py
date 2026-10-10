# core_time.py - TimeMixin：NTP 与时间校正
import threading
import time
from datetime import datetime

try:
    import ntplib
    _NTP_AVAILABLE = True
except ImportError:
    _NTP_AVAILABLE = False
    ntplib = None

from i18n import _


class TimeMixin:
    def start_ntp_sync(self):
        if self._ntp_synced:
            return
        threading.Thread(target=self._sync_ntp, daemon=True).start()

    def _sync_ntp(self):
        if not _NTP_AVAILABLE:
            self._safe_call('on_log', _("ntplib not installed, NTP unavailable. Run: pip install ntplib"), "warning")
            self._safe_call('on_toast', _("ntplib not installed, cannot sync time"), "warning")
            return

        servers = ['cn.pool.ntp.org', 'pool.ntp.org']
        for server in servers:
            try:
                client = ntplib.NTPClient()
                response = client.request(server, version=3, timeout=3)
                ntp_timestamp = response.tx_time
                system_timestamp = time.time()
                offset = ntp_timestamp - system_timestamp
                self._time_offset = offset
                self._ntp_synced = True
                self._safe_call('on_log',
                                _("NTP sync OK (server {server}), offset {offset:.3f}s",
                                  server=server, offset=offset),
                                "info")
                self._safe_call('on_toast',
                                _("Time calibrated (offset {offset:.3f}s)", offset=offset),
                                "info")
                return
            except Exception as e:
                self._safe_call('on_log',
                                _("NTP sync failed ({server}): {e}", server=server, e=e),
                                "warning")
        self._time_offset = 0.0
        self._safe_call('on_log', _("NTP sync failed, using system time"), "warning")

    def get_corrected_timestamp(self):
        return time.time() + self._time_offset

    def get_corrected_utc_now(self):
        return self.utc_from_corrected_ts(self.get_corrected_timestamp())

    def utc_from_corrected_ts(self, corrected_ts):
        return datetime.utcfromtimestamp(corrected_ts)

    # ---------- Configuration ----------
