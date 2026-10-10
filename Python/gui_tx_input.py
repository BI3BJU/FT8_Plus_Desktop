# gui_tx_input.py - TxInputMixin：TX 输入区 / 频率 / beacon 按钮
import math
import threading
import tkinter as tk
from tkinter import messagebox

from transmitter import is_free_text_compatible
from ft8_callsign import is_valid_callsign
from i18n import _
from gui_theme import (
    COLOR_BLACK, COLOR_RED, COLOR_GREEN, COLOR_BLUE, COLOR_GRAY,
)


class TxInputMixin:
    def _find_contact_note(self, callsign):
        """Return the stored note for a contact, or None if not found."""
        if not callsign:
            return None
        target = callsign.strip().upper()
        for c, note in self.contact_list:
            if c.strip().upper() == target:
                return note or None
        return None

    def _fill_input_with_contact(self, contact):
        if not is_valid_callsign(self.core.callsign):
            messagebox.showwarning(_("Invalid Callsign"),
                                   _("Current station callsign is invalid, cannot fill. Please update callsign first."))
            return
        self.tx_data_entry.delete(0, tk.END)
        self.tx_data_entry.insert(0, f"{self.core.callsign} {contact[0]} ")
        self.tx_data_entry.config(foreground=COLOR_BLACK)
        self._update_input_stats()

    def _show_tx_menu(self, event):
        try:
            self.tx_context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.tx_context_menu.grab_release()

    def _tx_copy(self):
        try:
            selected = self.tx_data_entry.selection_get()
            if selected:
                self.root.clipboard_clear()
                self.root.clipboard_append(selected)
        except tk.TclError:
            pass

    def _tx_paste(self):
        try:
            clipboard = self.root.clipboard_get()
            if clipboard:
                self.tx_data_entry.delete(0, tk.END)
                self.tx_data_entry.insert(0, clipboard)
                self._on_entry_focus_out(None)
                self._update_input_stats()
        except tk.TclError:
            pass

    def _tx_clear(self):
        self.tx_data_entry.delete(0, tk.END)
        self._update_input_stats()
        self._on_entry_focus_out(None)

    def _update_tx_button(self, is_active):
        if is_active:
            self.tx_action_btn.config(text=_("Stop"), bg=COLOR_RED)
        else:
            self.tx_action_btn.config(text=_("Transmit"), bg=COLOR_GREEN)

    def _on_tx_action(self):
        if self.core.is_transmitting:
            self.core.stop_transmit()
        else:
            data = self.tx_data_entry.get()
            if data == self._placeholder_text:
                data = ""
            data = data.strip()
            if not data:
                messagebox.showwarning(_("Warning"),
                                       _("Please enter data (cannot be empty)"))
                return
            try:
                freq = int(self.tx_freq_var.get())
            except ValueError:
                freq = self.core.tx_freq
            self.core.transmit_text(data, freq)

    def _toggle_beacon(self):
        """Toggle beacon mode.

        On start: read the input field (or auto-generate a 13-char beacon text
        from the local callsign). Input field is NOT filled here; it will be
        filled by Core at each slot start via on_beacon_fill, and cleared by
        on_beacon_clear after each TX completes.

        Button color is updated immediately in this method (synchronous),
        so the visual state changes without waiting for Core's callback,
        which may be delayed by the blocking cleanup performed inside
        Core.stop_beacon().
        """
        if self.core.beacon_active:
            # Update the button immediately for instant visual feedback.
            self.beacon_btn.config(bg=COLOR_BLACK)
            self.beacon_btn.update_idletasks()
            # Run the blocking cleanup in a background thread so the GUI
            # stays responsive. stop_beacon() may join the TX thread and
            # the beacon worker, which can take up to ~7s if a beacon
            # transmission is currently in progress.
            threading.Thread(
                target=self.core.stop_beacon, daemon=True
            ).start()
            return

        data = self.tx_data_entry.get()
        if data == self._placeholder_text:
            data = ""
        data = data.strip()

        if not data:
            if not is_valid_callsign(self.core.callsign):
                messagebox.showwarning(_("Invalid Callsign"),
                                       _("Current station callsign is invalid, cannot start beacon. Please update callsign first."))
                return
            call = self.core.callsign
            # Beacon text format: "<CALL> PLUS" (single space separator)
            beacon_text = f"{call} PLUS"
        else:
            beacon_text = data

        try:
            freq = int(self.tx_freq_var.get())
        except ValueError:
            freq = self.core.tx_freq

        # Update the button immediately so the user sees instant feedback.
        self.beacon_btn.config(bg=COLOR_GREEN)
        self.core.start_beacon(beacon_text, freq)

    def _on_freq_changed(self, event=None):
        try:
            val = int(self.tx_freq_var.get())
        except Exception:
            val = self.core.tx_freq
        if val < self.core.fixed_freq_start:
            val = self.core.fixed_freq_start
        elif val > self.core.fixed_freq_end:
            val = self.core.fixed_freq_end
        self.tx_freq_var.set(str(val))
        self.core.tx_freq = val
        self.core.save_config()

    def _on_entry_focus_in(self, event):
        current = self.tx_data_entry.get()
        if current == self._placeholder_text:
            self.tx_data_entry.delete(0, tk.END)
            self.tx_data_entry.config(foreground=COLOR_BLACK)
        self._update_input_stats()

    def _on_entry_focus_out(self, event):
        current = self.tx_data_entry.get().strip()
        if current == "":
            self.tx_data_entry.delete(0, tk.END)
            self.tx_data_entry.insert(0, self._placeholder_text)
            self.tx_data_entry.config(foreground=COLOR_GRAY)
        else:
            self.tx_data_entry.delete(0, tk.END)
            self.tx_data_entry.insert(0, current)
            self.tx_data_entry.config(foreground=COLOR_BLACK)
        self._update_input_stats()

    def _update_input_stats(self, event=None):
        data = self.tx_data_entry.get()
        if data == self._placeholder_text:
            data = ""
        if not data.strip():
            self.byte_count_label.config(text=_("Bytes: 0"), foreground=COLOR_BLACK)
            self.frame_count_label.config(text=_("Frames: 0"), foreground=COLOR_BLACK)
            return

        if is_free_text_compatible(data):
            self.byte_count_label.config(text=_("Free text (i3=0)"), foreground=COLOR_BLUE)
            self.frame_count_label.config(text=_("Single frame"), foreground=COLOR_BLUE)
            return

        encoded = data.encode('utf-8')
        byte_count = len(encoded)
        if byte_count <= 9:
            frame_count = 1
        else:
            payload_len = byte_count + 2
            frame_count = math.ceil(payload_len / 9)
        if byte_count <= self.core.max_raw_data_bytes:
            self.byte_count_label.config(
                text=_("Bytes: {n}/{max}", n=byte_count, max=self.core.max_raw_data_bytes),
                foreground=COLOR_GREEN)
            self.frame_count_label.config(text=_("Frames: {n}", n=frame_count), foreground=COLOR_GREEN)
        else:
            self.byte_count_label.config(
                text=_("Bytes: {n}/{max} (exceeded!)", n=byte_count, max=self.core.max_raw_data_bytes),
                foreground=COLOR_RED)
            self.frame_count_label.config(
                text=_("Frames: {n} (exceeded!)", n=frame_count), foreground=COLOR_RED)

    def _update_buffer_display(self, count):
        if count > 0:
            self.buffer_status_var.set(_("Active groups: {n}", n=count))
        else:
            self.buffer_status_var.set(_("No active buffer"))

