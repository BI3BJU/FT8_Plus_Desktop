# core_beacon.py - BeaconMixin：信标
import threading
import time

from i18n import _


class BeaconMixin:
    def start_beacon(self, text, freq):
        """Start periodic beacon transmission.

        The beacon wakes up at each slot boundary, asks the GUI to fill the
        input field with the beacon text (if empty), then transmits. After
        each transmission, it asks the GUI to clear the input field, then
        waits for the next 4-minute cycle before transmitting again.

        Resets stop_requested so a previous manual stop does not abort the
        new beacon immediately.
        """
        if self.beacon_active:
            return
        self.beacon_active = True
        self.beacon_stop_requested = False
        self.stop_requested = False
        self.beacon_text = text
        self.beacon_freq = freq
        self.beacon_thread = threading.Thread(target=self._beacon_worker, daemon=True)
        self.beacon_thread.start()
        self._safe_call('on_log', _("Beacon started: {text}", text=text), "info")
        self._safe_call('on_toast', _("Beacon started"), "info")
        self._safe_call('on_beacon_state', True)

    def stop_beacon(self):
        """Stop the beacon loop and abort any in-progress transmission.

        The GUI is notified immediately so its beacon button color updates
        without waiting for the blocking cleanup below (which may take up to
        a few seconds due to stop_transmit + thread join).
        """
        if not self.beacon_active:
            return
        # Flip state and notify GUI first, so the button color changes
        # instantly. The blocking cleanup happens afterwards.
        self.beacon_active = False
        self.beacon_stop_requested = True
        self._safe_call('on_beacon_state', False)

        if self.is_transmitting:
            self.stop_transmit()
        if self.beacon_thread and self.beacon_thread.is_alive():
            self.beacon_thread.join(timeout=5.0)
        self.beacon_thread = None
        self.beacon_stop_requested = False

        self._safe_call('on_log', _("Beacon stopped"), "info")
        self._safe_call('on_toast', _("Beacon stopped"), "info")

    def _beacon_worker(self):
        cycle = self.cycle_seconds
        t = self.get_corrected_timestamp()
        next_slot = int(t // cycle) * cycle + cycle  # first slot boundary

        try:
            while not self.beacon_stop_requested and not self.stop_requested:
                # Wake up 1s early if preamble noise is enabled
                wake_time = next_slot - 1.0 if self.preamble_noise_enabled else next_slot
                wait = wake_time - self.get_corrected_timestamp()
                if wait > 0:
                    if not self._interruptible_sleep(wait):
                        break
                if self.beacon_stop_requested or self.stop_requested:
                    break

                # Ask GUI to fill the input field at slot start
                self._safe_call('on_beacon_fill', self.beacon_text)

                # Transmit aligned to the current slot boundary
                self.transmit_text(self.beacon_text, self.beacon_freq, start_slot=next_slot)

                # Wait for the transmission to complete
                while self.is_transmitting and not self.beacon_stop_requested and not self.stop_requested:
                    time.sleep(0.1)
                if self.beacon_stop_requested or self.stop_requested:
                    break

                # Ask GUI to clear the input field after TX completes
                self._safe_call('on_beacon_clear')

                # Next beacon is 16 slots later (4 minutes at 15 s/slot).
                # 1 TX slot + 15 idle slots = 16 slots = 240 s = 4 min.
                next_slot += 16 * cycle
        except Exception as e:
            self._safe_call('on_log', _("Beacon error: {e}", e=e), "error")
        finally:
            # Unconditionally reset beacon state so the beacon can be
            # started again regardless of how the loop exited.
            self.beacon_active = False
            self.beacon_thread = None
            self.beacon_stop_requested = False
            self._safe_call('on_beacon_state', False)

    # ---------- Transmit ----------
