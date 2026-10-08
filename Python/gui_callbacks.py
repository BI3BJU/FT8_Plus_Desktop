# gui_callbacks.py - CallbacksMixin：Core -> GUI 回调
import tkinter as tk

from i18n import _
from gui_theme import COLOR_BLACK, COLOR_GREEN, COLOR_GRAY, COLOR_WHITE


class CallbacksMixin:
    def _on_log(self, msg, tag):
        self.root.after(0, lambda: self._insert_log(msg, tag))

    def _on_history(self, entry):
        self.root.after(0, lambda: self._add_history_entry(entry))

    def _on_status(self, is_tx):
        self.root.after(0, lambda: self._update_led_status(is_tx))

    def _on_tx_task(self, is_active):
        self.root.after(0, lambda: self._update_tx_button(is_active))

    def _on_buffer_count(self, count):
        self.root.after(0, lambda: self._update_buffer_display(count))

    def _on_tx_progress(self, progress):
        self.root.after(0, lambda: self.tx_status_var.set(progress))

    def _on_slot_update(self, slot_info):
        pass

    def _on_time_display(self, time_str):
        self.root.after(0, lambda: self.time_var.set(time_str))

    def _on_contact_updated(self, contact_list):
        self.root.after(0, lambda: self._refresh_contact_list())

    def _on_beacon_fill(self, text):
        """Callback from Core at slot start to fill the TX input field."""
        self.root.after(0, lambda: self._fill_beacon_input(text))

    def _on_beacon_clear(self):
        """Callback from Core after a beacon TX completes to clear the input."""
        self.root.after(0, self._clear_beacon_input)

    def _on_beacon_state(self, is_active):
        """Callback from Core when the beacon state changes.

        Used as an authoritative state sync, e.g. when Core stops the beacon
        from an internal path (shutdown, error, receiver stop) that the GUI
        did not directly trigger.
        """
        self.root.after(0, lambda: self._update_beacon_button(is_active))

    def _update_beacon_button(self, is_active):
        if is_active:
            self.beacon_btn.config(bg=COLOR_GREEN)
        else:
            self.beacon_btn.config(bg=COLOR_BLACK)

    def _fill_beacon_input(self, text):
        """Fill the TX input field only when it is empty or shows placeholder."""
        current = self.tx_data_entry.get()
        if current == self._placeholder_text or not current.strip():
            self.tx_data_entry.delete(0, tk.END)
            self.tx_data_entry.insert(0, text)
            self.tx_data_entry.config(foreground=COLOR_BLACK)
            self._update_input_stats()

    def _clear_beacon_input(self):
        """Clear the TX input field and restore the placeholder text."""
        self.tx_data_entry.delete(0, tk.END)
        self.tx_data_entry.insert(0, self._placeholder_text)
        self.tx_data_entry.config(foreground=COLOR_GRAY)
        self._update_input_stats()

    def _update_led_status(self, is_tx):
        if is_tx:
            self.led_label.config(text=_("Transmit"), bg=COLOR_GREEN, fg=COLOR_WHITE)
        else:
            self.led_label.config(text=_("Receive"), bg=COLOR_BLACK, fg=COLOR_WHITE)

    def _refresh_contact_list(self):
        self.contact_list = self.core.get_contacts()

