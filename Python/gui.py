# gui.py - Merged from gui_base / gui_callbacks / gui_builder / gui_tx_input /
#          gui_history_view / gui_log_view / gui_dialogs / gui_theme
# All code combined into a single file. Chinese comments translated to English.

import os
import sys
import json
import math
import time
import threading
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk, scrolledtext, messagebox
from datetime import datetime

from main import (
    HistoryEntry,
    _,
    MARKER_FREE_TEXT,
    MARKER_BEACON,
    MARKER_INTERRUPT,
    is_valid_callsign,
    BASE_DIR,
)
from transmitter import is_free_text_compatible

# -----------------------------------------------------------------------------
# Theme (from gui_theme.py)
# -----------------------------------------------------------------------------
CONTACT_ALL = "All"

COLOR_BLACK = "#000000"
COLOR_WHITE = "#FFFFFF"
COLOR_RED = "#800000"
COLOR_GREEN = "#008000"
COLOR_BLUE = "#000080"
COLOR_ORANGE = "#808000"
COLOR_PURPLE = "#800080"
COLOR_TEAL = "#008080"

def resource_path(relative_path):
    """Resource locator compatible with dev environment and PyInstaller."""
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    if getattr(sys, 'frozen', False):
        return os.path.join(os.path.dirname(sys.executable), relative_path)
    return os.path.join(os.path.abspath("."), relative_path)

# -----------------------------------------------------------------------------
# Dialog helpers (from gui_dialogs.py)
# -----------------------------------------------------------------------------
def center_window(window, parent):
    window.update_idletasks()
    w, h = window.winfo_width(), window.winfo_height()
    if w > 1 and h > 1:
        x = parent.winfo_x() + (parent.winfo_width() // 2) - (w // 2)
        y = parent.winfo_y() + (parent.winfo_height() // 2) - (h // 2)
        window.geometry(f"+{x}+{y}")

# ============ Contacts dialog ============

class ContactsDialog:
    def __init__(self, gui):
        self.gui = gui
        self.dialog = tk.Toplevel(gui.root)
        self.dialog.title(_("dlg.contacts"))
        self.dialog.geometry("350x400")
        self.dialog.transient(gui.root)
        self.dialog.grab_set()
        center_window(self.dialog, gui.root)

        frame = ttk.Frame(self.dialog, padding="10")
        frame.pack(fill=tk.BOTH, expand=True)

        self.listbox = tk.Listbox(frame, font=gui.label_font)
        self.listbox.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        self.refresh()

        btn_frame = ttk.Frame(frame)
        btn_frame.pack(fill=tk.X, pady=5)
        ttk.Button(btn_frame, text=_("dlg.new"),
                   command=self._add).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text=_("dlg.edit"),
                   command=self._edit).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text=_("dlg.delete"),
                   command=self._delete).pack(side=tk.LEFT, padx=5)
        self.listbox.bind("<Double-Button-1>", lambda e: self._select())

    def refresh(self):
        self.listbox.delete(0, tk.END)
        self.listbox.insert(tk.END, _("dlg.all"))
        for callsign, note in self.gui.contact_list:
            display = f"{callsign}, {note}" if note else callsign
            self.listbox.insert(tk.END, display)

    def _select(self):
        selection = self.listbox.curselection()
        if not selection:
            messagebox.showwarning(_("dlg.info"), _("dlg.select_record"))
            return
        idx = selection[0]
        if idx == 0:
            if not is_valid_callsign(self.gui.core.callsign):
                messagebox.showwarning(
                    _("dlg.invalid_callsign"),
                    _("dlg.callsign_required"))
                return
            self.gui.tx_data_entry.delete(0, tk.END)
            self.gui.tx_data_entry.insert(0, f"{self.gui.core.callsign} ")
            self.gui.tx_data_entry.config(foreground=COLOR_BLACK)
            self.gui._update_input_stats()
            self.dialog.destroy()
            return
        real_idx = idx - 1
        if 0 <= real_idx < len(self.gui.contact_list):
            self.gui._fill_input_with_contact(self.gui.contact_list[real_idx])
            self.dialog.destroy()

    def _add(self):
        d = tk.Toplevel(self.gui.root)
        d.title(_("dlg.new_contact"))
        d.geometry("350x150")
        d.transient(self.gui.root)
        d.grab_set()
        center_window(d, self.gui.root)

        ttk.Label(d, text=_("dlg.callsign_label"), font=self.gui.label_font).grid(
            row=0, column=0, padx=10, pady=10, sticky="e")
        entry_callsign = ttk.Entry(d, width=20, font=self.gui.label_font)
        entry_callsign.grid(row=0, column=1, padx=10, pady=10)

        ttk.Label(d, text=_("dlg.note_label"), font=self.gui.label_font).grid(
            row=1, column=0, padx=10, pady=10, sticky="e")
        entry_note = ttk.Entry(d, width=20, font=self.gui.label_font)
        entry_note.grid(row=1, column=1, padx=10, pady=10)

        def confirm():
            callsign = entry_callsign.get().strip().upper()
            note = entry_note.get().strip()
            if not callsign:
                messagebox.showwarning(_("dlg.warning"), _("dlg.callsign_empty"))
                return
            if not is_valid_callsign(callsign):
                messagebox.showwarning(
                    _("dlg.warning"),
                    _("dlg.callsign_format"))
                return
            if self.gui.core.add_contact(callsign, note):
                self.gui._refresh_contact_list()
                self.refresh()
                d.destroy()
            else:
                messagebox.showwarning(
                    _("dlg.warning"),
                    _("dlg.add_failed"))

        bf = ttk.Frame(d)
        bf.grid(row=2, column=0, columnspan=2, pady=10)
        ttk.Button(bf, text=_("dlg.ok"), command=confirm, width=8).pack(side=tk.LEFT, padx=5)
        ttk.Button(bf, text=_("dlg.cancel"), command=d.destroy, width=8).pack(side=tk.LEFT, padx=5)
        entry_callsign.focus_set()

    def _edit(self):
        selection = self.listbox.curselection()
        if not selection:
            messagebox.showwarning(_("dlg.info"), _("dlg.select_edit"))
            return
        idx = selection[0]
        if idx == 0:
            messagebox.showinfo(_("dlg.info"), _("dlg.callsign_fixed"))
            return
        real_idx = idx - 1
        if real_idx < 0 or real_idx >= len(self.gui.contact_list):
            return
        callsign, note = self.gui.contact_list[real_idx]

        d = tk.Toplevel(self.gui.root)
        d.title(_("dlg.edit_contact"))
        d.geometry("350x150")
        d.transient(self.gui.root)
        d.grab_set()
        center_window(d, self.gui.root)

        ttk.Label(d, text=_("dlg.callsign_label"), font=self.gui.label_font).grid(
            row=0, column=0, padx=10, pady=10, sticky="e")
        entry_callsign = ttk.Entry(d, width=20, font=self.gui.label_font)
        entry_callsign.insert(0, callsign)
        entry_callsign.grid(row=0, column=1, padx=10, pady=10)

        ttk.Label(d, text=_("dlg.note_label"), font=self.gui.label_font).grid(
            row=1, column=0, padx=10, pady=10, sticky="e")
        entry_note = ttk.Entry(d, width=20, font=self.gui.label_font)
        entry_note.insert(0, note)
        entry_note.grid(row=1, column=1, padx=10, pady=10)

        def confirm():
            new_callsign = entry_callsign.get().strip().upper()
            new_note = entry_note.get().strip()
            if not new_callsign:
                messagebox.showwarning(_("dlg.warning"), _("dlg.callsign_empty"))
                return
            if not is_valid_callsign(new_callsign):
                messagebox.showwarning(
                    _("dlg.warning"),
                    _("dlg.callsign_format"))
                return
            if self.gui.core.update_contact(real_idx, new_callsign, new_note):
                self.gui._refresh_contact_list()
                self.refresh()
                d.destroy()
            else:
                messagebox.showwarning(_("dlg.warning"),
                                       _("dlg.update_failed"))

        bf = ttk.Frame(d)
        bf.grid(row=2, column=0, columnspan=2, pady=10)
        ttk.Button(bf, text=_("dlg.ok"), command=confirm, width=8).pack(side=tk.LEFT, padx=5)
        ttk.Button(bf, text=_("dlg.cancel"), command=d.destroy, width=8).pack(side=tk.LEFT, padx=5)
        entry_callsign.focus_set()
        entry_callsign.select_range(0, tk.END)

    def _delete(self):
        selection = self.listbox.curselection()
        if not selection:
            messagebox.showwarning(_("dlg.info"), _("dlg.select_delete"))
            return
        idx = selection[0]
        if idx == 0:
            messagebox.showinfo(_("dlg.info"), _("dlg.callsign_fixed_del"))
            return
        real_idx = idx - 1
        if real_idx < 0 or real_idx >= len(self.gui.contact_list):
            return
        callsign, _note = self.gui.contact_list[real_idx]
        if messagebox.askyesno(_("dlg.confirm_delete"),
                               _("dlg.delete_confirm", callsign=callsign)):
            if self.gui.core.delete_contact(real_idx):
                self.gui._refresh_contact_list()
                self.refresh()
            else:
                messagebox.showwarning(_("dlg.info"), _("dlg.delete_failed"))

# ============ Callsign settings dialog ============

class CallsignDialog:
    def __init__(self, gui):
        self.gui = gui
        d = tk.Toplevel(gui.root)
        d.title(_("dlg.set_callsign"))
        d.geometry("400x230")
        d.transient(gui.root)
        d.grab_set()
        center_window(d, gui.root)

        ttk.Label(d, text=_("dlg.enter_callsign"), font=gui.label_font).pack(pady=(10, 0))
        ttk.Label(d,
                  text=_("dlg.callsign_format_hint"),
                  font=gui.label_font, foreground=COLOR_TEAL).pack()

        var = tk.StringVar(value=gui.core.callsign)
        entry = ttk.Entry(d, textvariable=var, width=20, font=gui.label_font)
        entry.pack(pady=8)
        error_label = ttk.Label(d, text="", foreground=COLOR_RED, font=gui.label_font)
        error_label.pack()

        def update(*_args):
            val = var.get().strip().upper()
            if val != var.get():
                var.set(val)
            ok = is_valid_callsign(val)
            error_label.config(
                text=_(u"\u2713 Correct") if ok else _(u"\u274c Invalid format (3~7 chars, must contain digit)"),
                foreground=COLOR_GREEN if ok else COLOR_RED)

        def apply():
            val = var.get().strip().upper()
            if not is_valid_callsign(val):
                messagebox.showerror(_("dlg.invalid"),
                                     _(u"\u274c Invalid format (3~7 chars, must contain digit)"))
                return
            gui.core.callsign = val
            gui.core.save_config()
            gui.callsign_btn.config(text=val)
            d.destroy()

        var.trace('w', update)
        entry.bind("<Return>", lambda e: apply())
        bf = ttk.Frame(d)
        bf.pack(pady=10)
        ttk.Button(bf, text=_("dlg.ok"), command=apply, width=8).pack(side=tk.LEFT, padx=5)
        ttk.Button(bf, text=_("dlg.cancel"), command=d.destroy, width=8).pack(side=tk.LEFT, padx=5)
        entry.focus_set()
        update()

# ============ About dialog ============

class AboutDialog:
    def __init__(self, gui):
        d = tk.Toplevel(gui.root)
        d.title(_("dlg.about_title"))
        d.geometry("680x540")
        d.transient(gui.root)
        d.grab_set()
        center_window(d, gui.root)

        frame = ttk.Frame(d, padding="10")
        frame.pack(fill=tk.BOTH, expand=True)
        text = scrolledtext.ScrolledText(frame, wrap=tk.WORD, font=gui.label_font)
        text.pack(fill=tk.BOTH, expand=True)
        text.insert("1.0", _("app.about"))
        text.config(state=tk.DISABLED)

        bf = ttk.Frame(frame)
        bf.pack(fill=tk.X, pady=(8, 0))

        def copy_about():
            gui.root.clipboard_clear()
            gui.root.clipboard_append(text.get("1.0", tk.END))

        ttk.Button(bf, text=_("dlg.copy"), command=copy_about, width=10).pack(side=tk.RIGHT, padx=5)
        ttk.Button(bf, text=_("dlg.cancel"), command=d.destroy, width=10).pack(side=tk.RIGHT)

# -----------------------------------------------------------------------------
# GuiBase (from gui_base.py)
# -----------------------------------------------------------------------------
class GuiBase:
    def __init__(self, root, core):
        self.root = root
        self.core = core
        self.root.title(_("app.title"))
        try:
            self.root.iconbitmap(resource_path('logo.ico'))
        except Exception:
            pass
        self.root.minsize(640, 480)
        self.root.geometry("640x480")

        self.status_log_path = str(BASE_DIR / "status.txt")
        self.history_log_path = str(BASE_DIR / "history.txt")
        self.max_log_lines = 100

        self.core.set_callbacks(
            on_log=self._on_log,
            on_history=self._on_history,
            on_status=self._on_status,
            on_tx_task=self._on_tx_task,
            on_buffer_count=self._on_buffer_count,
            on_tx_progress=self._on_tx_progress,
            on_slot_update=self._on_slot_update,
            on_time_display=self._on_time_display,
            on_contact_updated=self._on_contact_updated,
            on_beacon_fill=self._on_beacon_fill,
            on_beacon_clear=self._on_beacon_clear,
            on_beacon_state=self._on_beacon_state,
            on_beacon_tx_request=self._on_beacon_tx_request,
            on_toast=self._on_toast,
        )

        self.tx_freq_var = tk.StringVar(value=str(self.core.tx_freq))
        self.preamble_noise_var = tk.BooleanVar(value=self.core.preamble_noise_enabled)
        self.time_var = tk.StringVar()
        self.slot_var = tk.StringVar(value=_("gui.waiting_sync"))
        self.next_tx_var = tk.StringVar(value="--")
        self.tx_status_var = tk.StringVar(value="")
        self.buffer_status_var = tk.StringVar(value=_("gui.no_active_buffer"))

        self.contact_list = []
        self._beacon_tx_active = False

        self._build_ui()

        self.root.bind("<Configure>", self._on_window_resize)

        self._history_first_timestamp = {}

        self._load_history_log()
        self._load_status_log()

        self._update_clock()
        self._update_slot_timer()

        self.core.start_receiver()

        self._refresh_contact_list()

    def _center_window(self, window, parent=None):
        center_window(window, parent or self.root)

    def _show_contacts_dialog(self):
        ContactsDialog(self)

    def _edit_callsign(self):
        CallsignDialog(self)

    def _show_about(self):
        AboutDialog(self)

    def _on_window_resize(self, event):
        if event.widget == self.root:
            width, height = event.width, event.height
            base_size = 9
            w_factor = (width - 800) // 80
            h_factor = (height - 450) // 50
            new_size = max(9, min(18, base_size + min(w_factor, h_factor)))
            if hasattr(self, 'history_font'):
                self.history_font.configure(size=new_size)
            if hasattr(self, 'status_font'):
                self.status_font.configure(size=new_size)
            if hasattr(self, 'button_font'):
                self.button_font.configure(size=new_size)
            if hasattr(self, 'label_font'):
                self.label_font.configure(size=new_size)

    def _update_clock(self):
        now = self.core.get_corrected_utc_now()
        self.time_var.set(now.strftime("%Y-%m-%d %H:%M:%S") + " UTC")
        self.root.after(1000, self._update_clock)

    def _update_slot_timer(self):
        if self.core.is_running:
            t = self.core.get_corrected_timestamp()
            cycle = self.core.cycle_seconds
            time_in_cycle = t % cycle
            wait = cycle - time_in_cycle
            if wait < 0.01:
                wait = 0
            self.slot_var.set(_("gui.slot_progress", x=f"{time_in_cycle:.1f}", y=cycle))
            if wait < 0.1:
                self.next_tx_var.set(_("gui.tx_now"))
            else:
                self.next_tx_var.set(f"{wait:.1f}s")
        self.root.after(200, self._update_slot_timer)

# -----------------------------------------------------------------------------
# CallbacksMixin (from gui_callbacks.py)
# -----------------------------------------------------------------------------
class CallbacksMixin:
    def _on_log(self, msg, tag):
        self.root.after(0, lambda: self._insert_log(msg, tag))

    def _on_toast(self, msg, tag="info"):
        # Toast messages are routed to the status log so they are
        # not silently dropped when no native toast is available.
        self.root.after(0, lambda: self._insert_log(msg, tag))

    def _on_history(self, entry):
        self.root.after(0, lambda: self._add_history_entry(entry))

    def _on_status(self, is_tx):
        self.root.after(0, lambda: self._update_led_status(is_tx))

    def _on_tx_task(self, is_active):
        # Clear the input field after any transmission finishes.
        # The beacon path also signals _beacon_tx_done_event so the
        # beacon worker can move on to the next slot.
        if not is_active:
            if getattr(self, '_beacon_tx_active', False):
                self.root.after(0, self._finish_beacon_tx)
            else:
                self.root.after(0, self._clear_beacon_input)
        self.root.after(0, lambda: self._update_tx_button(is_active))

    def _on_beacon_tx_request(self, text, freq, next_slot):
        """Core requests beacon TX. Check input field: if empty, fill and transmit; otherwise skip."""
        self.root.after(0, lambda: self._handle_beacon_tx_request(text, freq, next_slot))

    def _handle_beacon_tx_request(self, text, freq, next_slot):
        current = self.tx_data_entry.get()
        if current != self._placeholder_text and current.strip():
            # Input field has content; skip this beacon TX (show content for debugging).
            self._insert_log(
                _("beacon.skipped",
                  text=current.strip()[:40]),
                "info"
            )
            self.core._beacon_tx_done_event.set()
            return
        # Input field is empty; fill in beacon text
        self.tx_data_entry.delete(0, tk.END)
        self.tx_data_entry.insert(0, text)
        self.tx_data_entry.config(foreground=COLOR_BLACK)
        self._update_input_stats()
        # Mark this as beacon TX
        self._beacon_tx_active = True
        # Call core to transmit
        self.core.transmit_text(text, freq, start_slot=next_slot)
        # Safety check: if transmit_text returns early due to is_transmitting /
        # is_running, the on_tx_task callback will not be triggered. In that
        # case notify Core that this beacon cycle is done, to avoid the beacon
        # thread waiting forever on _beacon_tx_done_event.
        if not self.core.is_transmitting:
            self._beacon_tx_active = False
            self._clear_beacon_input()
            self.core._beacon_tx_done_event.set()

    def _finish_beacon_tx(self):
        self._clear_beacon_input()
        self._beacon_tx_active = False
        self.core._beacon_tx_done_event.set()

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
        self.tx_data_entry.config(foreground=COLOR_TEAL)
        self._update_input_stats()

    def _update_led_status(self, is_tx):
        if is_tx:
            self.led_label.config(text=_("gui.transmit"), bg=COLOR_GREEN, fg=COLOR_WHITE)
        else:
            self.led_label.config(text=_("gui.receive"), bg=COLOR_BLACK, fg=COLOR_WHITE)

    def _refresh_contact_list(self):
        self.contact_list = self.core.get_contacts()

# -----------------------------------------------------------------------------
# BuilderMixin (from gui_builder.py)
# -----------------------------------------------------------------------------
class BuilderMixin:
    def _build_ui(self):
        main_frame = ttk.Frame(self.root, padding="5")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(0, weight=1)

        vertical_container = ttk.Frame(main_frame)
        vertical_container.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        main_frame.rowconfigure(0, weight=1)
        vertical_container.columnconfigure(0, weight=1)

        vertical_container.rowconfigure(0, weight=0)
        vertical_container.rowconfigure(1, weight=1)
        vertical_container.rowconfigure(2, weight=0)
        vertical_container.rowconfigure(3, weight=1)

        # Font sizes aligned with the Java (Android) version:
        #   history  11pt  (Java history = 14sp)
        #   status   13pt  (Java UTC/LED = 18sp / 14sp)
        #   button   12pt  (Java buttons = 12sp)
        #   label    11pt  (Java labels  = 12sp)
        # Consolas (monospace) is kept on purpose to match the Java
        # Typeface.MONOSPACE look and to keep the 60-char history
        # wrap correctly aligned.
        self.history_font = tkfont.Font(family="Consolas", size=11)
        self.status_font = tkfont.Font(family="Consolas", size=13, weight="bold")
        self.button_font = tkfont.Font(family="Consolas", size=12, weight="bold")
        self.label_font = tkfont.Font(family="Consolas", size=11)

        top_container = ttk.Frame(vertical_container)
        top_container.grid(row=0, column=0, sticky="ew", pady=(0, 2))
        top_container.columnconfigure(0, weight=1)

        time_row_frame = ttk.Frame(top_container)
        time_row_frame.grid(row=0, column=0, sticky="ew", pady=(0, 2))
        time_row_frame.columnconfigure(0, weight=1)
        ttk.Label(time_row_frame, textvariable=self.time_var,
                  font=self.status_font, anchor="center").grid(row=0, column=0, sticky="ew")

        top_frame = tk.Frame(top_container, bg=COLOR_WHITE)
        top_frame.grid(row=1, column=0, sticky="ew", pady=(0, 0))
        for c in range(4):
            top_frame.columnconfigure(c, weight=1)

        self.led_label = tk.Label(top_frame, text=_("gui.receive"), font=self.status_font,
                                  fg=COLOR_WHITE, bg=COLOR_BLACK, anchor="center")
        self.led_label.grid(row=0, column=0, sticky="nsew", padx=0, pady=0)

        self.callsign_btn = tk.Button(top_frame, text=self.core.callsign or _("gui.empty_callsign"),
                                      command=self._edit_callsign,
                                      bg=COLOR_PURPLE, fg=COLOR_WHITE,
                                      font=self.button_font, relief="flat")
        self.callsign_btn.grid(row=0, column=1, sticky="nsew", padx=0, pady=0)

        self.contacts_btn = tk.Button(top_frame, text=_("dlg.contacts"),
                                      command=self._show_contacts_dialog,
                                      bg=COLOR_ORANGE, fg=COLOR_WHITE,
                                      font=self.button_font, relief="flat")
        self.contacts_btn.grid(row=0, column=2, sticky="nsew", padx=0, pady=0)

        self.about_btn = tk.Button(top_frame, text=_("gui.about"),
                                   command=self._show_about,
                                   bg=COLOR_TEAL, fg=COLOR_WHITE,
                                   font=self.button_font, relief="flat")
        self.about_btn.grid(row=0, column=3, sticky="nsew", padx=0, pady=0)

        history_frame = ttk.LabelFrame(vertical_container, text="", padding="5")
        history_frame.grid(row=1, column=0, sticky="nsew", pady=(0, 2))
        history_container = ttk.Frame(history_frame)
        history_container.pack(fill=tk.BOTH, expand=True, padx=5, pady=2)

        self.history_text = tk.Text(history_container, wrap=tk.WORD,
                                    font=self.history_font, bg=COLOR_WHITE)
        scrollbar = ttk.Scrollbar(history_container, orient=tk.VERTICAL, command=self.history_text.yview)
        self.history_text.configure(yscrollcommand=scrollbar.set)
        self.history_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # ---------- History area color scheme ----------
        self.history_text.tag_config("recv_receiving_header", foreground=COLOR_BLACK, font=self.history_font)
        self.history_text.tag_config("recv_receiving_text", foreground=COLOR_BLACK)

        self.history_text.tag_config("recv_free_text_header", foreground=COLOR_BLACK, font=self.history_font)
        self.history_text.tag_config("recv_free_text_text", foreground=COLOR_BLACK)

        self.history_text.tag_config("recv_frame_ok_header", foreground=COLOR_BLACK, font=self.history_font)
        self.history_text.tag_config("recv_frame_ok_text", foreground=COLOR_BLACK)

        self.history_text.tag_config("recv_fail_header", foreground=COLOR_RED, font=self.history_font)
        self.history_text.tag_config("recv_fail_text", foreground=COLOR_RED)

        self.history_text.tag_config("send_sending_header", foreground=COLOR_GREEN, font=self.history_font)
        self.history_text.tag_config("send_sending_text", foreground=COLOR_GREEN)

        self.history_text.tag_config("send_complete_header", foreground=COLOR_GREEN, font=self.history_font)
        self.history_text.tag_config("send_complete_text", foreground=COLOR_GREEN)

        self.history_text.tag_config("send_fail_header", foreground=COLOR_RED, font=self.history_font)
        self.history_text.tag_config("send_fail_text", foreground=COLOR_RED)

        # ---------- Beacon tags ----------
        # Sent beacon: all green (header + body).
        # Received beacon: all orange (header + body).
        self.history_text.tag_config("beacon_send_header", foreground=COLOR_GREEN, font=self.history_font)
        self.history_text.tag_config("beacon_send_text", foreground=COLOR_GREEN)
        self.history_text.tag_config("beacon_recv_header", foreground=COLOR_BLACK, font=self.history_font)
        self.history_text.tag_config("beacon_recv_text", foreground=COLOR_BLACK)

        self.history_text.tag_config("contact_note", foreground=COLOR_BLACK, font=self.history_font)
        self.history_text.tag_config("self_header", foreground=COLOR_BLUE, font=self.history_font)
        self.history_text.tag_config("self_highlight", foreground=COLOR_BLUE, font=self.history_font, underline=True)

        self.history_text.tag_config("history_left", justify='left')
        self.history_text.tag_config("history_right", justify='right')

        self.history_text.config(state=tk.DISABLED)

        self.history_context_menu = tk.Menu(self.root, tearoff=0)
        self.history_context_menu.add_command(label=_("dlg.copy"), command=self._copy_history)
        self.history_context_menu.add_separator()
        self.history_context_menu.add_command(label=_("menu.clear"), command=self._clear_history)
        self.history_text.bind("<Button-3>", self._show_history_menu)

        tx_container = ttk.LabelFrame(vertical_container, text="", padding="5")
        tx_container.grid(row=2, column=0, sticky="ew", pady=2)
        tx_container.columnconfigure(0, weight=1)

        data_row = ttk.Frame(tx_container)
        data_row.grid(row=0, column=0, sticky=(tk.W, tk.E), padx=5, pady=5)
        data_row.columnconfigure(0, weight=1)

        # Beacon button: left-aligned, same size as the TX button.
        # Closed state: black background. Active state: green background.
        self.beacon_btn = tk.Button(data_row, text=_("beacon"), command=self._toggle_beacon,
                                    width=8, bg=COLOR_BLACK, fg=COLOR_WHITE,
                                    relief="raised", font=self.button_font)
        self.beacon_btn.pack(side=tk.LEFT, padx=2)

        self.tx_data_entry = ttk.Entry(data_row, width=50, font=self.label_font)
        self.tx_data_entry.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)

        self.tx_action_btn = tk.Button(data_row, text=_("gui.transmit"), command=self._on_tx_action,
                                       width=8, bg=COLOR_GREEN, fg=COLOR_WHITE, relief="raised",
                                       font=self.button_font)
        self.tx_action_btn.pack(side=tk.RIGHT, padx=2)

        self._placeholder_text = _("gui.placeholder")
        self.tx_data_entry.insert(0, self._placeholder_text)
        self.tx_data_entry.config(foreground=COLOR_TEAL)
        self.tx_data_entry.bind("<FocusIn>", self._on_entry_focus_in)
        self.tx_data_entry.bind("<FocusOut>", self._on_entry_focus_out)
        self.tx_data_entry.bind("<KeyRelease>", self._update_input_stats)

        self.tx_context_menu = tk.Menu(self.root, tearoff=0)
        self.tx_context_menu.add_command(label=_("dlg.copy"), command=self._tx_copy)
        self.tx_context_menu.add_command(label=_("menu.paste"), command=self._tx_paste)
        self.tx_context_menu.add_command(label=_("menu.clear"), command=self._tx_clear)
        self.tx_data_entry.bind("<Button-3>", self._show_tx_menu)

        stats_row = ttk.Frame(tx_container)
        stats_row.grid(row=1, column=0, sticky=(tk.W, tk.E), padx=5, pady=2)
        self.byte_count_label = ttk.Label(stats_row, text=_("gui.bytes"), foreground=COLOR_BLACK,
                                          font=self.label_font)
        self.byte_count_label.pack(side=tk.LEFT, padx=5)
        self.frame_count_label = ttk.Label(stats_row, text=_("gui.frames"), foreground=COLOR_BLACK,
                                           font=self.label_font)
        self.frame_count_label.pack(side=tk.LEFT, padx=20)

        ttk.Label(stats_row, text=_("gui.freq_hz"), font=self.label_font).pack(side=tk.LEFT, padx=(20, 5))
        freq_spinbox = tk.Spinbox(stats_row, from_=self.core.fixed_freq_start, to=self.core.fixed_freq_end,
                                  textvariable=self.tx_freq_var, width=8, increment=1,
                                  command=self._on_freq_changed,
                                  font=self.label_font)
        freq_spinbox.pack(side=tk.LEFT, padx=5)
        freq_spinbox.bind("<FocusOut>", self._on_freq_changed)
        freq_spinbox.bind("<Return>", self._on_freq_changed)
        ttk.Label(stats_row, text=_("gui.freq_range"), font=self.label_font).pack(side=tk.LEFT, padx=5)

        chk_noise = tk.Checkbutton(stats_row, text=_("gui.noise"), variable=self.preamble_noise_var,
                                   command=lambda: self.core.set_preamble_noise(self.preamble_noise_var.get()),
                                   font=self.label_font)
        chk_noise.pack(side=tk.LEFT, padx=10)

        display_frame = ttk.LabelFrame(vertical_container, text="", padding="5")
        display_frame.grid(row=3, column=0, sticky="nsew", pady=(2,0))
        self.display_text = scrolledtext.ScrolledText(display_frame, wrap=tk.WORD,
                                                      font=self.label_font, foreground=COLOR_BLACK)
        self.display_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=2)
        self.display_text.tag_config("info", foreground=COLOR_BLACK)
        self.display_text.tag_config("decode", foreground=COLOR_BLACK)
        self.display_text.tag_config("error", foreground=COLOR_BLACK)
        self.display_text.tag_config("tx", foreground=COLOR_BLACK)
        self.display_text.tag_config("halfduplex", foreground=COLOR_BLACK)
        self.display_text.tag_config("transparent", foreground=COLOR_BLACK)
        self.display_text.tag_config("auto_contact", foreground=COLOR_BLACK)

        self.display_context_menu = tk.Menu(self.root, tearoff=0)
        self.display_context_menu.add_command(label=_("dlg.copy"), command=self._copy_display)
        self.display_context_menu.add_separator()
        self.display_context_menu.add_command(label=_("menu.clear"), command=self._clear_display)
        self.display_text.bind("<Button-3>", self._show_display_menu)

        self._update_input_stats()

# -----------------------------------------------------------------------------
# TxInputMixin (from gui_tx_input.py)
# -----------------------------------------------------------------------------
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
            messagebox.showwarning(_("dlg.invalid_callsign"),
                                   _("dlg.callsign_required"))
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
            self.tx_action_btn.config(text=_("gui.stop"), bg=COLOR_RED)
        else:
            self.tx_action_btn.config(text=_("gui.transmit"), bg=COLOR_GREEN)

    def _on_tx_action(self):
        if self.core.is_transmitting:
            self.core.stop_transmit()
        else:
            data = self.tx_data_entry.get()
            if data == self._placeholder_text:
                data = ""
            data = data.strip()
            if not data:
                messagebox.showwarning(_("dlg.warning"),
                                       _("tx.empty"))
                return
            try:
                freq = int(self.tx_freq_var.get())
            except ValueError:
                freq = self.core.tx_freq
            self.core.transmit_text(data, freq)

    def _toggle_beacon(self):
        """Toggle beacon mode.

        Beacon text is ALWAYS "<CALL> PLUS" (never uses input field content
        as beacon text). The input field is only used by the per-slot
        handler _handle_beacon_tx_request to decide whether to skip a
        transmission: if the field already contains user content at slot
        start, that beacon slot is skipped; otherwise the field is filled
        with the beacon text and transmission proceeds. After a successful
        transmission the input field is automatically cleared.

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

        # Beacon text is fixed to "<CALL> PLUS". The input field content
        # is NOT used as beacon text; it only controls skip-or-not at
        # each slot start via _handle_beacon_tx_request.
        if not is_valid_callsign(self.core.callsign):
            messagebox.showwarning(_("dlg.invalid_callsign"),
                                   _("dlg.callsign_required_beacon"))
            return
        call = self.core.callsign
        beacon_text = f"{call} PLUS"

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
            self.tx_data_entry.config(foreground=COLOR_TEAL)
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
            self.byte_count_label.config(text=_("gui.bytes"), foreground=COLOR_BLACK)
            self.frame_count_label.config(text=_("gui.frames"), foreground=COLOR_BLACK)
            return

        if is_free_text_compatible(data):
            self.byte_count_label.config(text=_("gui.free_text_i3"), foreground=COLOR_BLUE)
            self.frame_count_label.config(text=_("gui.single_frame"), foreground=COLOR_BLUE)
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
                text=_("gui.bytes_n", n=byte_count, max=self.core.max_raw_data_bytes),
                foreground=COLOR_GREEN)
            self.frame_count_label.config(text=_("gui.frames_n", n=frame_count), foreground=COLOR_GREEN)
        else:
            self.byte_count_label.config(
                text=_("gui.bytes_exceeded", n=byte_count, max=self.core.max_raw_data_bytes),
                foreground=COLOR_RED)
            self.frame_count_label.config(
                text=_("gui.frames_exceeded", n=frame_count), foreground=COLOR_RED)

    def _update_buffer_display(self, count):
        if count > 0:
            self.buffer_status_var.set(_("gui.active_groups", n=count))
        else:
            self.buffer_status_var.set(_("gui.no_active_buffer"))

# -----------------------------------------------------------------------------
# HistoryViewMixin (from gui_history_view.py)
# -----------------------------------------------------------------------------
class HistoryViewMixin:
    def _write_history_entry_to_file(self, entry):
        data = {
            'ts': entry.timestamp.strftime("%Y-%m-%d %H:%M:%S") if entry.timestamp else None,
            'dir': entry.direction,
            'freq': entry.freq,
            'text': entry.text,
            'marker': entry.marker,
            'partial': entry.is_partial,
            'crc': entry.crc_status,
            'src': entry.source_callsign,
            'tgt': entry.target_callsign,
            'frames': entry.frames_count,
            'total': entry.total_frames if entry.total_frames is not None else 1,
            'note': getattr(entry, 'contact_note', None),
        }
        line = json.dumps(data, ensure_ascii=False)
        self._append_text_line(self.history_log_path, line)

    def _load_history_log(self):
        if not os.path.exists(self.history_log_path):
            return
        try:
            with open(self.history_log_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            lines = lines[-self.max_log_lines:]
            idx = 0
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    timestamp = None
                    if data.get('ts'):
                        try:
                            timestamp = datetime.strptime(data['ts'], "%Y-%m-%d %H:%M:%S")
                        except Exception:
                            timestamp = datetime.now()
                    idx += 1
                    session_id = f"load_{idx}_{int(time.time()*1000)}_{data.get('ts', '')}"
                    entry = HistoryEntry(
                        direction=data.get('dir', 'recv'),
                        timestamp=timestamp,
                        freq=data.get('freq', 0),
                        snr=None,
                        frames_count=data.get('frames', 0),
                        total_bytes=len(data.get('text', '').encode('utf-8')),
                        text=data.get('text', ''),
                        marker=data.get('marker', ''),
                        is_complete=not data.get('partial', True),
                        slot_progress=None,
                        is_partial=data.get('partial', False),
                        session_id=session_id,
                        crc_status=data.get('crc'),
                        source_callsign=data.get('src'),
                        target_callsign=data.get('tgt'),
                        i3=None,
                        total_frames=data.get('total', 1),
                        total_bytes_all=len(data.get('text', '').encode('utf-8')),
                        contact_note=data.get('note'),
                    )
                    self.core.history_entries.append(entry)
                    self._append_history_entry(entry)
                except json.JSONDecodeError:
                    continue
        except Exception as e:
            print(f"Failed to load history log: {e}")

    def _add_history_entry(self, entry):
        self._append_history_entry(entry)
        self.history_text.see(tk.END)
        if not entry.is_partial:
            self._write_history_entry_to_file(entry)

    def _get_history_tags(self, entry):
        # Determine if this is a failed reception (CRC fail or timeout)
        is_recv_fail = False
        if entry.direction == 'recv':
            if entry.crc_status and ("fail" in entry.crc_status.lower() or "timeout" in entry.crc_status.lower()):
                is_recv_fail = True
            elif entry.marker and ("fail" in str(entry.marker).lower() or "timeout" in str(entry.marker).lower()):
                is_recv_fail = True

        # Sent messages
        if entry.direction == 'send':
            if entry.marker == MARKER_BEACON:
                return "beacon_send_header", "beacon_send_text"
            if entry.marker == MARKER_INTERRUPT:
                return "send_fail_header", "send_fail_text"
            if entry.is_partial:
                return "send_sending_header", "send_sending_text"
            else:
                if entry.marker and any(kw in entry.marker for kw in ("Interrupted", "Exception", "Cancel", "Fail")):
                    return "send_fail_header", "send_fail_text"
                else:
                    return "send_complete_header", "send_complete_text"

        # Received messages: beacon orange, failed red, default black.
        if entry.direction == 'recv':
            if entry.marker == MARKER_BEACON:
                return "beacon_recv_header", "beacon_recv_text"
            if is_recv_fail:
                return "recv_fail_header", "recv_fail_text"
            else:
                return "recv_frame_ok_header", "recv_frame_ok_text"

        # Fallback
        return "recv_frame_ok_header", "recv_frame_ok_text"

    def _append_history_entry(self, entry):
        self.history_text.config(state=tk.NORMAL)
        tag_name = f"hist_{entry.direction}_{entry.session_id}"
        ranges = self.history_text.tag_ranges(tag_name)

        if ranges:
            start_pos = ranges[0]
            self.history_text.delete(ranges[0], ranges[-1])
        else:
            start_pos = self.history_text.index("end")

        align_tag = "history_right" if entry.direction == 'send' else "history_left"

        header_tag, content_tag = self._get_history_tags(entry)

        # Determine whether the local station's own callsign is involved.
        is_me_involved = False
        if entry.direction == 'recv' and self.core.callsign:
            is_me_involved = (
                entry.source_callsign == self.core.callsign or
                entry.target_callsign == self.core.callsign
            )

        # Determine if reception failed (for color priority)
        is_recv_fail = False
        if entry.direction == 'recv':
            if entry.crc_status and ("fail" in entry.crc_status.lower() or "timeout" in entry.crc_status.lower()):
                is_recv_fail = True
            elif entry.marker and ("fail" in str(entry.marker).lower() or "timeout" in str(entry.marker).lower()):
                is_recv_fail = True

        if is_me_involved and not is_recv_fail:
            header_tag = "self_header"

        pos = start_pos
        total_chars = 0

        def insert_text(text, tags=()):
            nonlocal pos, total_chars
            if not text:
                return
            new_tags = tags + (align_tag,) if isinstance(tags, tuple) else (align_tag,)
            self.history_text.insert(pos, text, new_tags)
            total_chars += len(text)
            pos = self.history_text.index(f"{start_pos} + {total_chars} chars")

        timestamp_to_use = entry.timestamp
        if entry.direction == 'send' and entry.session_id:
            if entry.session_id not in self._history_first_timestamp:
                self._history_first_timestamp[entry.session_id] = entry.timestamp
            else:
                timestamp_to_use = self._history_first_timestamp[entry.session_id]

        time_str = timestamp_to_use.strftime("%Y-%m-%d %H:%M:%S") if timestamp_to_use else ""

        dir_str = "[TX]" if entry.direction == 'send' else "[RX]"

        # Determine type tag (four types: beacon, free text, single, continuous).
        # Identify a receive-side continuous-frame entry from the protocol
        # fields i3=6 and f2=1, and show it as "Continuous" from the
        # very first frame, even before the second frame arrives.
        is_rx_continuous = (
            entry.direction == 'recv'
            and entry.i3 == 6
            and getattr(entry, 'f2', None) == 1
        )
        if entry.marker == MARKER_BEACON:
            type_tag = _("beacon")
        elif entry.marker == MARKER_FREE_TEXT:
            type_tag = _("gui.free_text_tag")
        elif is_rx_continuous or entry.frames_count > 1 or (entry.total_frames and entry.total_frames > 1):
            type_tag = _("gui.continuous")
        else:
            type_tag = _("gui.single")
        type_str = f"[{type_tag}]"
        freq_str = f"[{entry.freq:.0f}Hz]" if entry.freq is not None else ""

        status_str = ""
        if entry.direction == 'send' and entry.marker == MARKER_INTERRUPT:
            status_str = f"[{_('gui.manual_stop')}]"
        elif type_tag == _("gui.continuous"):
            if entry.direction == 'recv':
                if entry.is_partial:
                    status_str = f"[{_('rx.receiving')}]"
                else:
                    if entry.crc_status in ("CRC OK", "No checksum", "No_checksum"):
                        status_str = f"[{_('gui.crc_ok')}]"
                    elif entry.crc_status in ("CRC fail", "CRC失败") or "CRC失败" in str(entry.crc_status):
                        status_str = f"[{_('gui.crc_failed')}]"
                    elif entry.crc_status in ("Timeout", "timeout"):
                        status_str = f"[{_('rx.timeout')}]"
                    else:
                        status_str = f"[{entry.marker}]"
            else:
                if entry.is_partial:
                    status_str = f"[{_('gui.sending')}]"
                else:
                    if entry.marker and any(kw in entry.marker for kw in ("Interrupted", "Exception", "Cancel", "Fail")):
                        status_str = f"[{_('gui.interrupted')}]"
                    else:
                        status_str = f"[{_('gui.send_complete')}]"

        progress_str = ""
        if type_tag == _("gui.continuous"):
            if entry.direction == 'recv':
                # Match Java version: show RX progress whenever more
                # than one frame is involved. This covers both partial
                # (receiving) and completed RX entries.
                if entry.frames_count > 1:
                    progress_str = "[" + _("rx.received_frames",
                                           n=entry.frames_count, b=entry.total_bytes) + "]"
            else:
                # TX: keep the original condition based on total_frames.
                if entry.total_frames is not None and entry.total_frames > 1:
                    total_f = entry.total_frames if entry.total_frames is not None else 1
                    total_b = entry.total_bytes_all if entry.total_bytes_all is not None else entry.total_bytes
                    progress_str = _("gui.frames_progress",
                                     n=entry.frames_count, m=total_f, b=entry.total_bytes, tb=total_b)

        header_parts = [f"[{time_str}]", dir_str, type_str, freq_str, status_str, progress_str]
        header_parts = [p for p in header_parts if p]
        header = ' '.join(header_parts).strip()

        insert_text(header + "\n", (header_tag, tag_name))

        # Contact-note line, only for received messages whose sender is known.
        # For received beacon entries, use the beacon orange color so the
        # note line matches the header and body color.
        if entry.direction == 'recv' and entry.source_callsign:
            note = getattr(entry, 'contact_note', None)
            if not note:
                note = self._find_contact_note(entry.source_callsign)
            if note:
                # Match the Java version: render the note with the
                # same tag as the body text so it inherits the same
                # color (black / red / green / blue), instead of
                # always being black.
                insert_text(f"[{note}]\n", (content_tag, tag_name))

        # Body text: for beacon entries display only the callsign.
        # Sent beacon: local callsign. Received beacon: source callsign.
        # For manual-stop entries: show the raw text as it was.
        if entry.marker == MARKER_BEACON:
            if entry.direction == 'recv':
                beacon_call = entry.source_callsign or "?"
            else:
                beacon_call = self.core.callsign or "?"
            display_text = beacon_call
        else:
            display_text = entry.text

        for line in self._wrap_text(display_text, 60):
            insert_text(line + "\n", (content_tag, tag_name))

        end_pos = self.history_text.index(f"{start_pos} + {total_chars} chars")
        self.history_text.tag_add(align_tag, start_pos, end_pos)
        self.history_text.tag_raise(align_tag)

        if is_me_involved and not is_recv_fail:
            self.history_text.tag_add("self_highlight", start_pos, end_pos)
            self.history_text.tag_raise("self_highlight")

        self.history_text.config(state=tk.DISABLED)
        self.history_text.see(tk.END)

    def _refresh_history_display(self):
        self._history_first_timestamp.clear()
        self.history_text.config(state=tk.NORMAL)
        self.history_text.delete(1.0, tk.END)
        for entry in self.core.history_entries:
            self._append_history_entry(entry)
        self.history_text.config(state=tk.DISABLED)

    def _wrap_text(self, text, width):
        return [text[i:i+width] for i in range(0, len(text), width)] if text else [""]

    def _show_history_menu(self, event):
        try:
            self.history_context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.history_context_menu.grab_release()

    def _copy_history(self):
        try:
            text = self.history_text.get(tk.SEL_FIRST, tk.SEL_LAST)
        except tk.TclError:
            text = self.history_text.get("1.0", tk.END)
        if text:
            self.root.clipboard_clear()
            self.root.clipboard_append(text)

    def _clear_history(self):
        self.core.history_entries.clear()
        self._history_first_timestamp.clear()
        self._refresh_history_display()
        if os.path.exists(self.history_log_path):
            try:
                os.remove(self.history_log_path)
            except Exception as e:
                self._insert_log(_("gui.history_delete_failed", e=e), "error")
        self._insert_log(_("gui.history_cleared"), "info")

# -----------------------------------------------------------------------------
# LogViewMixin (from gui_log_view.py)
# -----------------------------------------------------------------------------
class LogViewMixin:
    def _append_text_line(self, path, line):
        try:
            with open(path, 'a', encoding='utf-8') as f:
                f.write(line + '\n')
            with open(path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            if len(lines) > self.max_log_lines:
                lines = lines[-self.max_log_lines:]
                with open(path, 'w', encoding='utf-8') as f:
                    f.writelines(lines)
        except Exception as e:
            print(f"Failed to write log file {path}: {e}")

    def _append_status_log(self, msg):
        self._append_text_line(self.status_log_path, msg)

    def _load_status_log(self):
        if not os.path.exists(self.status_log_path):
            return
        try:
            with open(self.status_log_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            lines = lines[-self.max_log_lines:]
            if lines:
                self.display_text.config(state=tk.NORMAL)
                for line in lines:
                    self.display_text.insert(tk.END, line)
                self.display_text.config(state=tk.DISABLED)
                self.display_text.see(tk.END)
        except Exception as e:
            print(f"Failed to load status log: {e}")

    def _insert_log(self, msg, tag):
        if msg and not msg.startswith('['):
            corrected_now = self.core.get_corrected_utc_now()
            timestamp = corrected_now.strftime("%Y-%m-%d %H:%M:%S")
            msg = f"[{timestamp}] {msg}"

        self.display_text.config(state=tk.NORMAL)
        self.display_text.insert(tk.END, msg + "\n", tag)
        self.display_text.see(tk.END)
        max_lines = self.core.fixed_max_messages
        while True:
            try:
                line_count = int(self.display_text.index('end-1c').split('.')[0])
                if line_count > max_lines:
                    self.display_text.delete("1.0", "2.0")
                else:
                    break
            except Exception:
                break
        self.display_text.config(state=tk.DISABLED)

        self._append_status_log(msg)

    def _show_display_menu(self, event):
        try:
            self.display_context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.display_context_menu.grab_release()

    def _copy_display(self):
        try:
            text = self.display_text.get(tk.SEL_FIRST, tk.SEL_LAST)
        except tk.TclError:
            text = self.display_text.get("1.0", tk.END)
        if text:
            self.root.clipboard_clear()
            self.root.clipboard_append(text)

    def _clear_display(self):
        self.display_text.config(state=tk.NORMAL)
        self.display_text.delete("1.0", tk.END)
        self.display_text.config(state=tk.DISABLED)
        if os.path.exists(self.status_log_path):
            try:
                os.remove(self.status_log_path)
            except Exception as e:
                self.display_text.config(state=tk.NORMAL)
                self.display_text.insert(tk.END, _("gui.status_delete_failed", e=e) + "\n", "error")
                self.display_text.config(state=tk.DISABLED)
        self._insert_log(_("gui.status_cleared"), "info")

# -----------------------------------------------------------------------------
# GUI assembly (from gui.py)
# -----------------------------------------------------------------------------
class GUI(CallbacksMixin, BuilderMixin, TxInputMixin, HistoryViewMixin,
          LogViewMixin, GuiBase):
    """FT8 Plus GUI. Functionality is split across mixins."""
    pass

__all__ = ["GUI"]