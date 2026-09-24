# gui.py - GUI layer (i18n enabled)

import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, simpledialog
import tkinter.font as tkfont
import threading
import time
import math
import os
import re
import webbrowser
import sys
import json
from datetime import datetime
from main import Core, HistoryEntry, TransparentBuffer, is_valid_callsign, is_valid_grid6, grid6_to_latlon
from transmitter import is_free_text_compatible
from i18n import _, init as i18n_init, MARKER_FREE_TEXT


def resource_path(relative_path):
    """获取资源的绝对路径，兼容开发环境和 PyInstaller 单文件/单目录模式。"""
    # PyInstaller 单文件模式：资源被解压到 _MEIPASS 临时目录
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    # PyInstaller 单目录模式：资源在 exe 同目录
    if getattr(sys, 'frozen', False):
        return os.path.join(os.path.dirname(sys.executable), relative_path)
    # 开发环境：资源在源码目录
    return os.path.join(os.path.abspath("."), relative_path)


CONTACT_ALL = "All"

# ========== Unified color table (prefer light background) ==========
COLOR_BLACK   = "#000000"
COLOR_RED     = "#CC0000"
COLOR_MAROON  = "#800000"
COLOR_GREEN   = "#008000"
COLOR_BLUE    = "#0000FF"
COLOR_NAVY    = "#000080"
COLOR_INDIGO  = "#4B0082"
COLOR_YELLOW  = "#666600"
COLOR_TEAL    = "#006666"
COLOR_MAGENTA = "#CC00CC"
COLOR_GRAY    = "#666666"
COLOR_ORANGE  = "#993300"
COLOR_PINK    = "#C71585"
COLOR_PURPLE  = "#660066"
COLOR_BROWN   = "#A52A2A"
COLOR_WHITE   = "#FFFFFF"


class GUI:
    def __init__(self, root, core):
        self.root = root
        self.core = core
        self.root.title(_("FT8 Plus 1.0"))
        try:
            self.root.iconbitmap(resource_path('logo.ico'))
        except Exception:
            pass
        self.root.minsize(640, 480)
        self.root.geometry("640x480")

        self.status_log_path = "status.txt"
        self.history_log_path = "history.txt"
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
        )

        self.tx_freq_var = tk.StringVar(value=str(self.core.tx_freq))
        self.preamble_noise_var = tk.BooleanVar(value=self.core.preamble_noise_enabled)
        self.time_var = tk.StringVar()
        self.slot_var = tk.StringVar(value=_("Waiting for sync..."))
        self.next_tx_var = tk.StringVar(value="--")
        self.tx_status_var = tk.StringVar(value="")
        self.buffer_status_var = tk.StringVar(value=_("No active buffer"))

        self.contact_list = []

        self._build_ui()

        self.root.bind("<Configure>", self._on_window_resize)

        self._history_first_timestamp = {}

        self._load_history_log()
        self._load_status_log()

        self._update_clock()
        self._update_slot_timer()

        self.core.start_receiver()

        self._refresh_contact_list()

        self.core.set_input_availability_callback(self._is_input_available_for_beacon)
        self.core.set_fill_input_callback(self._fill_input)

    def _center_window(self, window, parent=None):
        if parent is None:
            parent = self.root
        window.update_idletasks()
        width = window.winfo_width()
        height = window.winfo_height()
        if width > 1 and height > 1:
            x = parent.winfo_x() + (parent.winfo_width() // 2) - (width // 2)
            y = parent.winfo_y() + (parent.winfo_height() // 2) - (height // 2)
            window.geometry(f"+{x}+{y}")

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

        self.history_font = tkfont.Font(family="Consolas", size=9)
        self.status_font = tkfont.Font(family="Consolas", size=12, weight="bold")
        self.button_font = tkfont.Font(family="Consolas", size=12, weight="bold")
        self.label_font = tkfont.Font(family="Consolas", size=10)

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
        for c in range(5):
            top_frame.columnconfigure(c, weight=1)

        self.led_label = tk.Label(top_frame, text=_("Receive"), font=self.status_font,
                                  fg=COLOR_WHITE, bg=COLOR_BLACK, anchor="center")
        self.led_label.grid(row=0, column=0, sticky="nsew", padx=0, pady=0)

        self.callsign_btn = tk.Button(top_frame, text=self.core.callsign or _("(empty)"),
                                      command=self._edit_callsign,
                                      bg=COLOR_BLUE, fg=COLOR_WHITE,
                                      font=self.button_font, relief="flat")
        self.callsign_btn.grid(row=0, column=1, sticky="nsew", padx=0, pady=0)

        self.grid_btn = tk.Button(top_frame, text=_("Grid"),
                                  command=self._set_grid,
                                  bg=COLOR_ORANGE, fg=COLOR_WHITE,
                                  font=self.button_font, relief="flat")
        self.grid_btn.grid(row=0, column=2, sticky="nsew", padx=0, pady=0)
        self.grid_btn.config(text=self.core.grid6 or _("Grid"))

        self.contacts_btn = tk.Button(top_frame, text=_("Contacts"),
                                      command=self._show_contacts_dialog,
                                      bg=COLOR_MAGENTA, fg=COLOR_WHITE,
                                      font=self.button_font, relief="flat")
        self.contacts_btn.grid(row=0, column=3, sticky="nsew", padx=0, pady=0)

        self.about_btn = tk.Button(top_frame, text=_("About"),
                                   command=self._show_about,
                                   bg=COLOR_GRAY, fg=COLOR_WHITE,
                                   font=self.button_font, relief="flat")
        self.about_btn.grid(row=0, column=4, sticky="nsew", padx=0, pady=0)

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

        self.history_text.tag_config("recv_beacon_ok_header", foreground=COLOR_BLUE, font=self.history_font)
        self.history_text.tag_config("recv_beacon_ok_text", foreground=COLOR_BLUE)

        self.history_text.tag_config("beacon_clickable", foreground=COLOR_BLUE, underline=False)
        self.history_text.tag_bind("beacon_clickable", "<Button-1>", self._on_beacon_click)

        self.history_text.tag_config("self_highlight", foreground=COLOR_ORANGE, underline=False)

        self.history_text.tag_config("history_left", justify='left')
        self.history_text.tag_config("history_right", justify='right')

        self.history_text.config(state=tk.DISABLED)

        self.history_context_menu = tk.Menu(self.root, tearoff=0)
        self.history_context_menu.add_command(label=_("Copy"), command=self._copy_history)
        self.history_context_menu.add_separator()
        self.history_context_menu.add_command(label=_("Clear"), command=self._clear_history)
        self.history_text.bind("<Button-3>", self._show_history_menu)

        tx_container = ttk.LabelFrame(vertical_container, text="", padding="5")
        tx_container.grid(row=2, column=0, sticky="ew", pady=2)
        tx_container.columnconfigure(0, weight=1)

        data_row = ttk.Frame(tx_container)
        data_row.grid(row=0, column=0, sticky=(tk.W, tk.E), padx=5, pady=5)
        data_row.columnconfigure(1, weight=1)

        self.beacon_btn = tk.Button(data_row, text="📡",
                                    command=self._toggle_beacon,
                                    bg=COLOR_GRAY, relief="raised",
                                    font=self.button_font, width=6)
        self.beacon_btn.pack(side=tk.LEFT, padx=(0, 5))

        self.tx_data_entry = ttk.Entry(data_row, width=50, font=self.label_font)
        self.tx_data_entry.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)

        self.tx_action_btn = tk.Button(data_row, text=_("Transmit"), command=self._on_tx_action,
                                       width=8, bg=COLOR_GREEN, fg=COLOR_WHITE, relief="raised",
                                       font=self.button_font)
        self.tx_action_btn.pack(side=tk.RIGHT, padx=2)

        self._placeholder_text = _("Max 574 bytes UTF-8, auto frame (CRC8+EOT)")
        self.tx_data_entry.insert(0, self._placeholder_text)
        self.tx_data_entry.config(foreground=COLOR_GRAY)
        self.tx_data_entry.bind("<FocusIn>", self._on_entry_focus_in)
        self.tx_data_entry.bind("<FocusOut>", self._on_entry_focus_out)
        self.tx_data_entry.bind("<KeyRelease>", self._update_input_stats)

        self.tx_context_menu = tk.Menu(self.root, tearoff=0)
        self.tx_context_menu.add_command(label=_("Copy"), command=self._tx_copy)
        self.tx_context_menu.add_command(label=_("Paste"), command=self._tx_paste)
        self.tx_context_menu.add_command(label=_("Clear"), command=self._tx_clear)
        self.tx_data_entry.bind("<Button-3>", self._show_tx_menu)

        stats_row = ttk.Frame(tx_container)
        stats_row.grid(row=1, column=0, sticky=(tk.W, tk.E), padx=5, pady=2)
        self.byte_count_label = ttk.Label(stats_row, text=_("Bytes: 0"), foreground=COLOR_BLACK,
                                          font=self.label_font)
        self.byte_count_label.pack(side=tk.LEFT, padx=5)
        self.frame_count_label = ttk.Label(stats_row, text=_("Frames: 0"), foreground=COLOR_BLACK,
                                           font=self.label_font)
        self.frame_count_label.pack(side=tk.LEFT, padx=20)

        ttk.Label(stats_row, text=_("Freq (Hz):"), font=self.label_font).pack(side=tk.LEFT, padx=(20, 5))
        freq_spinbox = tk.Spinbox(stats_row, from_=self.core.fixed_freq_start, to=self.core.fixed_freq_end,
                                  textvariable=self.tx_freq_var, width=8, increment=1,
                                  command=self._on_freq_changed,
                                  font=self.label_font)
        freq_spinbox.pack(side=tk.LEFT, padx=5)
        freq_spinbox.bind("<FocusOut>", self._on_freq_changed)
        freq_spinbox.bind("<Return>", self._on_freq_changed)
        ttk.Label(stats_row, text=_("(300-3000)"), font=self.label_font).pack(side=tk.LEFT, padx=5)

        chk_noise = tk.Checkbutton(stats_row, text=_("noise"), variable=self.preamble_noise_var,
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
        self.display_text.tag_config("auto_contact", foreground=COLOR_BLUE)

        self.display_context_menu = tk.Menu(self.root, tearoff=0)
        self.display_context_menu.add_command(label=_("Copy"), command=self._copy_display)
        self.display_context_menu.add_separator()
        self.display_context_menu.add_command(label=_("Clear"), command=self._clear_display)
        self.display_text.bind("<Button-3>", self._show_display_menu)

        self._update_input_stats()

    def _is_input_available_for_beacon(self, beacon_text):
        current = self.tx_data_entry.get()
        stripped = current.strip()
        return stripped == "" or current == self._placeholder_text or stripped == beacon_text

    def _fill_input(self, text):
        self.tx_data_entry.delete(0, tk.END)
        self.tx_data_entry.insert(0, text)
        self.tx_data_entry.config(foreground=COLOR_BLACK)
        self._update_input_stats()

    def _toggle_beacon(self):
        self.core.toggle_beacon()
        if self.core.beacon_enabled:
            self.beacon_btn.config(bg=COLOR_GREEN)
        else:
            self.beacon_btn.config(bg=COLOR_GRAY)

    def _set_grid(self):
        dialog = tk.Toplevel(self.root)
        dialog.title(_("Set Maidenhead Grid"))
        dialog.geometry("400x160")
        dialog.transient(self.root)
        dialog.grab_set()
        self._center_window(dialog)

        ttk.Label(dialog, text=_("Enter 6-char Maidenhead grid (e.g. OM89EW):"),
                  font=self.label_font).pack(pady=(10,5))
        entry = ttk.Entry(dialog, width=20, font=self.label_font)
        entry.pack(pady=5)
        entry.insert(0, self.core.grid6)
        error_label = ttk.Label(dialog, text="", foreground=COLOR_RED, font=self.label_font)
        error_label.pack()

        def apply():
            grid = entry.get().strip().upper()
            if grid and not is_valid_grid6(grid):
                error_label.config(text=_("❌ Invalid format, expected 2 letters + 2 digits + 2 letters"))
                return
            self.core.set_grid6(grid)
            if grid:
                self.grid_btn.config(text=grid)
            else:
                self.grid_btn.config(text=_("Grid"))
            self.core.save_config()
            dialog.destroy()

        button_frame = ttk.Frame(dialog)
        button_frame.pack(pady=10)
        ttk.Button(button_frame, text=_("OK"), command=apply, width=8).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text=_("Cancel"), command=dialog.destroy, width=8).pack(side=tk.LEFT, padx=5)
        entry.focus_set()
        entry.select_range(0, tk.END)

    def _update_led_status(self, is_tx):
        if is_tx:
            self.led_label.config(text=_("Transmit"), bg=COLOR_GREEN, fg=COLOR_WHITE)
        else:
            self.led_label.config(text=_("Receive"), bg=COLOR_BLACK, fg=COLOR_WHITE)

    def _refresh_contact_list(self):
        self.contact_list = self.core.get_contacts()

    def _show_contacts_dialog(self):
        dialog = tk.Toplevel(self.root)
        dialog.title(_("Contacts"))
        dialog.geometry("350x400")
        dialog.transient(self.root)
        dialog.grab_set()
        self._center_window(dialog)

        frame = ttk.Frame(dialog, padding="10")
        frame.pack(fill=tk.BOTH, expand=True)

        listbox = tk.Listbox(frame, font=self.label_font)
        listbox.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        self._refresh_contact_listbox(listbox)

        btn_frame = ttk.Frame(frame)
        btn_frame.pack(fill=tk.X, pady=5)
        ttk.Button(btn_frame, text=_("New"), command=lambda: self._add_contact_dialog(dialog, listbox)).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text=_("Edit"), command=lambda: self._edit_contact_dialog(dialog, listbox)).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text=_("Delete"), command=lambda: self._delete_contact(dialog, listbox)).pack(side=tk.LEFT, padx=5)

        listbox.bind("<Double-Button-1>", lambda e: self._select_contact(dialog, listbox))

    def _refresh_contact_listbox(self, listbox):
        listbox.delete(0, tk.END)
        listbox.insert(tk.END, _("All"))
        for callsign, note in self.contact_list:
            display = f"{callsign}, {note}" if note else callsign
            listbox.insert(tk.END, display)

    def _select_contact(self, dialog, listbox):
        selection = listbox.curselection()
        if not selection:
            messagebox.showwarning(_("Info"), _("Please select a record first"))
            return
        idx = selection[0]
        if idx == 0:
            if not is_valid_callsign(self.core.callsign):
                messagebox.showwarning(_("Invalid Callsign"),
                                       _("Current station callsign is invalid, cannot fill. Please update callsign first."))
                return
            self.tx_data_entry.delete(0, tk.END)
            self.tx_data_entry.insert(0, f"{self.core.callsign}:")
            self.tx_data_entry.config(foreground=COLOR_BLACK)
            self._update_input_stats()
            dialog.destroy()
            return
        real_idx = idx - 1
        if real_idx < 0 or real_idx >= len(self.contact_list):
            return
        contact = self.contact_list[real_idx]
        self._fill_input_with_contact(contact)
        dialog.destroy()

    def _add_contact_dialog(self, parent, listbox):
        dialog = tk.Toplevel(self.root)
        dialog.title(_("New Contact"))
        dialog.geometry("350x150")
        dialog.transient(self.root)
        dialog.grab_set()
        self._center_window(dialog)

        ttk.Label(dialog, text=_("Callsign:"), font=self.label_font).grid(row=0, column=0, padx=10, pady=10, sticky="e")
        entry_callsign = ttk.Entry(dialog, width=20, font=self.label_font)
        entry_callsign.grid(row=0, column=1, padx=10, pady=10)

        ttk.Label(dialog, text=_("Note:"), font=self.label_font).grid(row=1, column=0, padx=10, pady=10, sticky="e")
        entry_note = ttk.Entry(dialog, width=20, font=self.label_font)
        entry_note.grid(row=1, column=1, padx=10, pady=10)

        def confirm():
            callsign = entry_callsign.get().strip().upper()
            note = entry_note.get().strip()
            if not callsign:
                messagebox.showwarning(_("Warning"), _("Callsign cannot be empty"))
                return
            if not is_valid_callsign(callsign):
                messagebox.showwarning(_("Warning"),
                                       _("Invalid callsign format (must be 3~6 chars, with at least one digit)"))
                return
            if self.core.add_contact(callsign, note):
                self._refresh_contact_list()
                self._refresh_contact_listbox(listbox)
                dialog.destroy()
            else:
                messagebox.showwarning(_("Warning"),
                                       _("Add failed (limit reached or callsign exists)"))

        button_frame = ttk.Frame(dialog)
        button_frame.grid(row=2, column=0, columnspan=2, pady=10)
        ttk.Button(button_frame, text=_("OK"), command=confirm, width=8).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text=_("Cancel"), command=dialog.destroy, width=8).pack(side=tk.LEFT, padx=5)

        entry_callsign.focus_set()

    def _edit_contact_dialog(self, parent, listbox):
        selection = listbox.curselection()
        if not selection:
            messagebox.showwarning(_("Info"), _("Please select a contact to edit"))
            return
        idx = selection[0]
        if idx == 0:
            messagebox.showinfo(_("Info"), _("\"All\" is fixed, cannot edit"))
            return
        real_idx = idx - 1
        if real_idx < 0 or real_idx >= len(self.contact_list):
            return
        callsign, note = self.contact_list[real_idx]

        dialog = tk.Toplevel(self.root)
        dialog.title(_("Edit Contact"))
        dialog.geometry("350x150")
        dialog.transient(self.root)
        dialog.grab_set()
        self._center_window(dialog)

        ttk.Label(dialog, text=_("Callsign:"), font=self.label_font).grid(row=0, column=0, padx=10, pady=10, sticky="e")
        entry_callsign = ttk.Entry(dialog, width=20, font=self.label_font)
        entry_callsign.insert(0, callsign)
        entry_callsign.grid(row=0, column=1, padx=10, pady=10)

        ttk.Label(dialog, text=_("Note:"), font=self.label_font).grid(row=1, column=0, padx=10, pady=10, sticky="e")
        entry_note = ttk.Entry(dialog, width=20, font=self.label_font)
        entry_note.insert(0, note)
        entry_note.grid(row=1, column=1, padx=10, pady=10)

        def confirm():
            new_callsign = entry_callsign.get().strip().upper()
            new_note = entry_note.get().strip()
            if not new_callsign:
                messagebox.showwarning(_("Warning"), _("Callsign cannot be empty"))
                return
            if not is_valid_callsign(new_callsign):
                messagebox.showwarning(_("Warning"),
                                       _("Invalid callsign format (must be 3~6 chars, with at least one digit)"))
                return
            if self.core.update_contact(real_idx, new_callsign, new_note):
                self._refresh_contact_list()
                self._refresh_contact_listbox(listbox)
                dialog.destroy()
            else:
                messagebox.showwarning(_("Warning"),
                                       _("Update failed (callsign may exist)"))

        button_frame = ttk.Frame(dialog)
        button_frame.grid(row=2, column=0, columnspan=2, pady=10)
        ttk.Button(button_frame, text=_("OK"), command=confirm, width=8).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text=_("Cancel"), command=dialog.destroy, width=8).pack(side=tk.LEFT, padx=5)

        entry_callsign.focus_set()
        entry_callsign.select_range(0, tk.END)

    def _delete_contact(self, parent, listbox):
        selection = listbox.curselection()
        if not selection:
            messagebox.showwarning(_("Info"), _("Please select a contact to delete"))
            return
        idx = selection[0]
        if idx == 0:
            messagebox.showinfo(_("Info"), _("\"All\" is fixed, cannot delete"))
            return
        real_idx = idx - 1
        if real_idx < 0 or real_idx >= len(self.contact_list):
            return
        callsign, note = self.contact_list[real_idx]
        if messagebox.askyesno(_("Confirm Delete"),
                               _("Delete contact {callsign}?", callsign=callsign)):
            if self.core.delete_contact(real_idx):
                self._refresh_contact_list()
                self._refresh_contact_listbox(listbox)
            else:
                messagebox.showwarning(_("Info"), _("Delete failed"))

    def _fill_input_with_contact(self, contact):
        if not is_valid_callsign(self.core.callsign):
            messagebox.showwarning(_("Invalid Callsign"),
                                   _("Current station callsign is invalid, cannot fill. Please update callsign first."))
            return
        self.tx_data_entry.delete(0, tk.END)
        self.tx_data_entry.insert(0, f"{self.core.callsign}@{contact[0]} ")
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

    def _edit_callsign(self):
        dialog = tk.Toplevel(self.root)
        dialog.title(_("Set Callsign"))
        dialog.geometry("400x230")
        dialog.transient(self.root)
        dialog.grab_set()
        self._center_window(dialog)

        ttk.Label(dialog, text=_("Enter your callsign"), font=self.label_font).pack(pady=(10,0))
        ttk.Label(dialog, text=_("Format: 3~6 chars, contains at least one digit, letters/digits only"),
                  font=self.label_font, foreground=COLOR_GRAY).pack()
        var = tk.StringVar(value=self.core.callsign)
        entry = ttk.Entry(dialog, textvariable=var, width=20, font=self.label_font)
        entry.pack(pady=8)
        error_label = ttk.Label(dialog, text="", foreground=COLOR_RED, font=self.label_font)
        error_label.pack()

        def validate(v):
            if not is_valid_callsign(v):
                return False, _("❌ Invalid format (3~6 chars, must contain digit)")
            return True, _("✓ Correct")

        def update(*args):
            val = var.get().strip().upper()
            if val != var.get():
                var.set(val)
            ok, msg = validate(val)
            error_label.config(text=msg, foreground=COLOR_GREEN if ok else COLOR_RED)

        def apply():
            val = var.get().strip().upper()
            ok, msg = validate(val)
            if not ok:
                messagebox.showerror(_("Invalid"), msg)
                return
            self.core.callsign = val
            self.core.save_config()
            self.callsign_btn.config(text=val)
            dialog.destroy()

        var.trace('w', update)
        entry.bind("<Return>", lambda e: apply())
        button_frame = ttk.Frame(dialog)
        button_frame.pack(pady=10)
        ttk.Button(button_frame, text=_("OK"), command=apply, width=8).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text=_("Cancel"), command=dialog.destroy, width=8).pack(side=tk.LEFT, padx=5)
        entry.focus_set()
        update()

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

    def _write_history_entry_to_file(self, entry):
        data = {
            'ts': entry.timestamp.strftime("%Y-%m-%d %H:%M:%S") if entry.timestamp else None,
            'dir': entry.direction,
            'freq': entry.freq,
            'text': entry.text,
            'marker': entry.marker,
            'partial': entry.is_partial,
            'crc': entry.crc_status,
            'beacon': entry.is_beacon,
            'grid': entry.grid6,
            'src': entry.source_callsign,
            'tgt': entry.target_callsign,
            'frames': entry.frames_count,
            'total': entry.total_frames if entry.total_frames is not None else 1,
        }
        line = json.dumps(data, ensure_ascii=False)
        self._append_text_line(self.history_log_path, line)

    def _append_status_log(self, msg):
        self._append_text_line(self.status_log_path, msg)

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
                        is_beacon=data.get('beacon', False),
                        grid6=data.get('grid')
                    )
                    self.core.history_entries.append(entry)
                    self._append_history_entry(entry)
                except json.JSONDecodeError:
                    continue
        except Exception as e:
            print(f"Failed to load history log: {e}")

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

    def _add_history_entry(self, entry):
        self._append_history_entry(entry)
        self.history_text.see(tk.END)
        if not entry.is_partial:
            self._write_history_entry_to_file(entry)

    def _get_history_tags(self, entry):
        if entry.direction == 'recv':
            if entry.is_partial:
                return "recv_receiving_header", "recv_receiving_text"
            else:
                if entry.crc_status in ("CRC OK", "No checksum", "No_checksum") or entry.crc_status is None:
                    if entry.is_beacon:
                        return "recv_beacon_ok_header", "recv_beacon_ok_text"
                    elif entry.marker == MARKER_FREE_TEXT:
                        return "recv_free_text_header", "recv_free_text_text"
                    else:
                        return "recv_frame_ok_header", "recv_frame_ok_text"
                else:
                    return "recv_fail_header", "recv_fail_text"
        else:
            if entry.is_partial:
                return "send_sending_header", "send_sending_text"
            else:
                if entry.marker and any(kw in entry.marker for kw in ("Interrupted", "Exception", "Cancel", "Fail")):
                    return "send_fail_header", "send_fail_text"
                else:
                    return "send_complete_header", "send_complete_text"

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

        if entry.is_beacon:
            type_tag = _("Beacon")
        elif entry.marker == MARKER_FREE_TEXT:
            type_tag = _("Free text")
        elif entry.direction == 'recv' and entry.is_partial:
            type_tag = _("Continuous")
        else:
            if entry.frames_count > 1 or (entry.total_frames and entry.total_frames > 1):
                type_tag = _("Continuous")
            else:
                type_tag = _("Single")
        type_str = f"[{type_tag}]"
        freq_str = f"[{entry.freq:.0f}Hz]" if entry.freq is not None else ""

        status_str = ""
        if type_tag == _("Continuous"):
            if entry.direction == 'recv':
                if entry.is_partial:
                    status_str = f"[{_('Receiving')}]"
                else:
                    if entry.crc_status in ("CRC OK", "No checksum", "No_checksum"):
                        status_str = f"[{_('CRC OK')}]"
                    elif entry.crc_status in ("CRC fail", "CRC失败") or "CRC失败" in str(entry.crc_status):
                        status_str = f"[{_('CRC failed')}]"
                    elif entry.crc_status in ("Timeout", "timeout"):
                        status_str = f"[{_('Receive timeout')}]"
                    else:
                        status_str = f"[{entry.marker}]"
            else:
                if entry.is_partial:
                    status_str = f"[{_('Sending')}]"
                else:
                    if entry.marker and any(kw in entry.marker for kw in ("Interrupted", "Exception", "Cancel", "Fail")):
                        status_str = f"[{_('Interrupted')}]"
                    else:
                        status_str = f"[{_('Send complete')}]"

        progress_str = ""
        if type_tag == _("Continuous") and entry.total_frames is not None and entry.total_frames > 1:
            if entry.direction == 'recv':
                progress_str = "[" + _("Received {n} frames {b} bytes",
                                       n=entry.frames_count, b=entry.total_bytes) + "]"
            else:
                total_f = entry.total_frames if entry.total_frames is not None else 1
                total_b = entry.total_bytes_all if entry.total_bytes_all is not None else entry.total_bytes
                progress_str = _("[{n}/{m} frames] [{b}/{tb} bytes]",
                                 n=entry.frames_count, m=total_f, b=entry.total_bytes, tb=total_b)

        header_parts = [f"[{time_str}]", dir_str, type_str, freq_str, status_str, progress_str]
        header_parts = [p for p in header_parts if p]
        header = ' '.join(header_parts).strip()

        insert_text(header + "\n", (header_tag, tag_name))

        display_text = entry.text

        if entry.is_beacon and entry.grid6 and entry.direction == 'recv':
            match = re.match(r'^([A-Z0-9]{3,6})\s+📡\s+([A-R]{2}[0-9]{2}[A-X]{2})$', display_text)
            if match:
                callsign_part = match.group(1)
                grid_part = match.group(2)
                plain_part = f"{callsign_part} 📡 "
                insert_text(plain_part, (content_tag, tag_name))
                grid_text = grid_part + "\n"
                self.history_text.insert(pos, grid_text, ("beacon_clickable", tag_name, align_tag))
                total_chars += len(grid_text)
                pos = self.history_text.index(f"{start_pos} + {total_chars} chars")
                self.history_text.tag_bind("beacon_clickable", "<Button-1>",
                                           lambda e, g=grid_part: self._open_map(g))
            else:
                for line in self._wrap_text(display_text, 60):
                    insert_text(line + "\n", (content_tag, tag_name))
        else:
            for line in self._wrap_text(display_text, 60):
                insert_text(line + "\n", (content_tag, tag_name))

        end_pos = self.history_text.index(f"{start_pos} + {total_chars} chars")
        self.history_text.tag_add(align_tag, start_pos, end_pos)
        self.history_text.tag_raise(align_tag)

        if entry.direction == 'recv' and entry.is_self_targeted:
            self.history_text.tag_add("self_highlight", start_pos, end_pos)

        self.history_text.config(state=tk.DISABLED)
        self.history_text.see(tk.END)

    def _open_map(self, grid):
        if not grid or not is_valid_grid6(grid):
            return
        try:
            lat, lon = grid6_to_latlon(grid)
        except Exception as e:
            self._insert_log(_("Grid conversion failed: {e}", e=e), "error")
            return
        lat_str = f"{lat:.6f}"
        lon_str = f"{lon:.6f}"
        bing_url = f'https://www.bing.com/maps?q={lat_str},{lon_str}&lvl=15&style=h'
        webbrowser.open_new_tab(bing_url)
        self._insert_log(_("Opened Bing Maps: {url}", url=bing_url), "info")

    def _on_beacon_click(self, event):
        pass

    def _refresh_history_display(self):
        self._history_first_timestamp.clear()
        self.history_text.config(state=tk.NORMAL)
        self.history_text.delete(1.0, tk.END)
        for entry in self.core.history_entries:
            self._append_history_entry(entry)
        self.history_text.config(state=tk.DISABLED)

    def _wrap_text(self, text, width):
        return [text[i:i+width] for i in range(0, len(text), width)] if text else [""]

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
            self.slot_var.set(_("Slot: {x}s / {y}s", x=f"{time_in_cycle:.1f}", y=cycle))
            if wait < 0.1:
                self.next_tx_var.set(_("Transmit now!"))
            else:
                self.next_tx_var.set(f"{wait:.1f}s")
        self.root.after(200, self._update_slot_timer)

    def _show_history_menu(self, event):
        try:
            self.history_context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.history_context_menu.grab_release()

    def _show_display_menu(self, event):
        try:
            self.display_context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.display_context_menu.grab_release()

    def _copy_history(self):
        try:
            text = self.history_text.get(tk.SEL_FIRST, tk.SEL_LAST)
        except tk.TclError:
            text = self.history_text.get("1.0", tk.END)
        if text:
            self.root.clipboard_clear()
            self.root.clipboard_append(text)

    def _copy_display(self):
        try:
            text = self.display_text.get(tk.SEL_FIRST, tk.SEL_LAST)
        except tk.TclError:
            text = self.display_text.get("1.0", tk.END)
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
                self._insert_log(_("Failed to delete history file: {e}", e=e), "error")
        self._insert_log(_("History cleared, deleted history.txt"), "info")

    def _clear_display(self):
        self.display_text.config(state=tk.NORMAL)
        self.display_text.delete("1.0", tk.END)
        self.display_text.config(state=tk.DISABLED)
        if os.path.exists(self.status_log_path):
            try:
                os.remove(self.status_log_path)
            except Exception as e:
                self.display_text.config(state=tk.NORMAL)
                self.display_text.insert(tk.END, _("Failed to delete status file: {e}", e=e) + "\n", "error")
                self.display_text.config(state=tk.DISABLED)
        self._insert_log(_("Status cleared, deleted status.txt"), "info")

    def _show_about(self):
        dialog = tk.Toplevel(self.root)
        dialog.title(_("About FT8 Plus 1.0 Protocol Demo"))
        dialog.geometry("680x540")
        dialog.transient(self.root)
        dialog.grab_set()
        self._center_window(dialog)

        frame = ttk.Frame(dialog, padding="10")
        frame.pack(fill=tk.BOTH, expand=True)

        text = scrolledtext.ScrolledText(frame, wrap=tk.WORD, font=self.label_font)
        text.pack(fill=tk.BOTH, expand=True)

        about_text = _("about.text")
        text.insert("1.0", about_text)
        text.config(state=tk.DISABLED)

        btn_frame = ttk.Frame(frame)
        btn_frame.pack(fill=tk.X, pady=(8, 0))

        def copy_about():
            content = text.get("1.0", tk.END)
            self.root.clipboard_clear()
            self.root.clipboard_append(content)

        ttk.Button(btn_frame, text=_("Copy"), command=copy_about, width=10).pack(side=tk.RIGHT, padx=5)
        ttk.Button(btn_frame, text=_("Cancel"), command=dialog.destroy, width=10).pack(side=tk.RIGHT)