# gui.py - Merged from gui_base / gui_callbacks / gui_builder / gui_tx_input /
#          gui_history_view / gui_log_view / gui_dialogs / gui_theme
# All code combined into a single file. Chinese comments translated to English.

import os
import sys
import json
import math
import time
import urllib.request
import threading
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk, scrolledtext, messagebox
from datetime import datetime
from collections import deque

from main import (
    HistoryEntry,
    _,
    MARKER_FREE_TEXT,
    MARKER_BEACON,
    MARKER_INTERRUPT,
    is_valid_callsign,
    is_valid_grid8,
    pack_location_message,
    BASE_DIR,
)
from transmitter import is_free_text_compatible

# -----------------------------------------------------------------------------
# System location (Windows Location API via winsdk)
# -----------------------------------------------------------------------------
# The Windows Runtime geolocation API is optional. If winsdk is not
# installed or the platform is not Windows, the import fails silently
# and _get_system_location_blocking() raises a RuntimeError when called.
# winsdk is imported lazily inside _get_system_location_blocking() so
# that importing gui.py stays fast when the location service is unused.
_WINSDK_AVAILABLE = None  # None = not probed yet


def _winsdk_available():
    # Probe the optional winsdk package once and cache the result.
    global _WINSDK_AVAILABLE
    if _WINSDK_AVAILABLE is None:
        try:
            from winsdk.windows.devices.geolocation import (  # noqa: F401
                Geolocator, PositionAccuracy, GeolocationAccessStatus,
            )
            _WINSDK_AVAILABLE = True
        except Exception:
            _WINSDK_AVAILABLE = False
    return _WINSDK_AVAILABLE

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

# TX action button symbols. Background colors are unchanged;
# only the label switches between TX and Stop.
SYMBOL_TX = "\u25B6"    # ▶ BLACK RIGHT-POINTING TRIANGLE
SYMBOL_STOP = "\u25A0"  # ■ BLACK SQUARE


def _get_system_location_blocking(timeout: float = 15.0):
    """Return (lat, lon) from the OS default (fused) location stack.

    Uses the default Windows Geolocator (fused: GPS / Wi-Fi / cellular /
    IP, at the OS's discretion). Raises on failure:
      - RuntimeError         : winsdk not installed or not on Windows
      - PermissionError      : location access denied by the OS
      - asyncio.TimeoutError : the request timed out
      - ValueError           : the OS returned a default / (0,0) coord
    """
    if not _winsdk_available():
        raise RuntimeError(_("gui.location_no_winsdk"))

    from winsdk.windows.devices.geolocation import (
        Geolocator, PositionAccuracy, GeolocationAccessStatus,
    )
    import asyncio

    async def _run():
        status = await Geolocator.request_access_async()
        if status != GeolocationAccessStatus.ALLOWED:
            raise PermissionError(_("gui.location_denied"))

        locator = Geolocator()
        locator.desired_accuracy = PositionAccuracy.DEFAULT
        locator.report_interval = 0  # one-shot request

        pos = await asyncio.wait_for(locator.get_geoposition_async(), timeout)
        coord = pos.coordinate

        lat = float(coord.point.position.latitude)
        lon = float(coord.point.position.longitude)
        if lat == 0.0 and lon == 0.0:
            raise ValueError(_("gui.location_invalid"))
        return lat, lon

    return asyncio.run(_run())


def lat_lon_to_grid8(lat: float, lon: float) -> str:
    A = ord('A')
    a = ord('a')
    lon = lon + 180.0
    lat = lat + 90.0
    f_lon = int(lon / 20.0)
    f_lat = int(lat / 10.0)
    lon -= f_lon * 20.0
    lat -= f_lat * 10.0
    s_lon = int(lon / 2.0)
    s_lat = int(lat / 1.0)
    lon -= s_lon * 2.0
    lat -= s_lat * 1.0
    sub_lon = int(lon * 12.0)
    sub_lat = int(lat * 24.0)
    lon -= sub_lon * (1.0 / 12.0)
    lat -= sub_lat * (1.0 / 24.0)
    ext_lon = int(lon * 120.0)
    ext_lat = int(lat * 240.0)

    return (f"{chr(A + f_lon)}{chr(A + f_lat)}{s_lon}{s_lat}"
            f"{chr(a + sub_lon)}{chr(a + sub_lat)}{ext_lon}{ext_lat}")


def grid8_to_lat_lon(grid: str) -> tuple:
    if len(grid) != 8:
        raise ValueError("Grid must be exactly 8 characters long")
    grid = grid.upper()
    lon = (ord(grid[0]) - ord('A')) * 20.0 - 180.0
    lat = (ord(grid[1]) - ord('A')) * 10.0 - 90.0
    lon += int(grid[2]) * 2.0
    lat += int(grid[3]) * 1.0
    lon += (ord(grid[4].lower()) - ord('a')) * (1.0 / 12.0)
    lat += (ord(grid[5].lower()) - ord('a')) * (1.0 / 24.0)
    lon += int(grid[6]) * (1.0 / 120.0)
    lat += int(grid[7]) * (1.0 / 240.0)
    lon += 1.0 / 240.0
    lat += 1.0 / 480.0
    return lat, lon

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
                text=_("dlg.callsign_correct") if ok else _("dlg.callsign_invalid_hint"),
                foreground=COLOR_GREEN if ok else COLOR_RED)

        def apply():
            val = var.get().strip().upper()
            if not is_valid_callsign(val):
                messagebox.showerror(_("dlg.invalid"),
                                     _("dlg.callsign_invalid_hint"))
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

# ============ Grid settings dialog ============

class GridDialog:
    """Dialog for viewing / editing the station's 8-char Maidenhead grid.

    The grid may be empty. It can be typed manually or derived from the
    OS default location via the "Get system location" button.
    """

    def __init__(self, gui):
        self.gui = gui
        d = tk.Toplevel(gui.root)
        d.title(_("dlg.set_grid"))
        d.geometry("420x260")
        d.transient(gui.root)
        d.grab_set()
        center_window(d, gui.root)

        ttk.Label(d, text=_("dlg.enter_grid"), font=gui.label_font).pack(pady=(10, 0))
        ttk.Label(d, text=_("dlg.grid_format_hint"),
                  font=gui.label_font, foreground=COLOR_TEAL).pack()

        var = tk.StringVar(value=gui.core.grid or "")
        entry = ttk.Entry(d, textvariable=var, width=20, font=gui.label_font)
        entry.pack(pady=8)
        status_label = ttk.Label(d, text="", foreground=COLOR_RED, font=gui.label_font)
        status_label.pack()

        fetch_btn = ttk.Button(d, text=_("dlg.get_location"))
        fetch_btn.pack(pady=4)

        def update(*_args):
            val = var.get().strip().upper()
            if val != var.get():
                var.set(val)
            if val == "":
                status_label.config(text=_("dlg.grid_empty_ok"),
                                    foreground=COLOR_GREEN)
                return
            ok = is_valid_grid8(val)
            status_label.config(
                text=_("dlg.callsign_correct") if ok else _("dlg.grid_invalid_hint"),
                foreground=COLOR_GREEN if ok else COLOR_RED)

        def apply_grid_value(grid):
            var.set(grid)
            update()

        def fetch_location():
            fetch_btn.config(state=tk.DISABLED)
            status_label.config(text=_("gui.location_fetching"),
                                foreground=COLOR_BLUE)

            def worker():
                try:
                    lat, lon = _get_system_location_blocking(timeout=15.0)
                    grid = lat_lon_to_grid8(lat, lon)
                    d.after(0, lambda g=grid: apply_grid_value(g))
                except Exception as e:
                    # Bind the exception text before scheduling; Python 3
                    # deletes `e` when the except block exits.
                    err = str(e)
                    d.after(0, lambda m=err: status_label.config(
                        text=_("gui.location_failed") + f": {m}",
                        foreground=COLOR_RED))
                finally:
                    d.after(0, lambda: fetch_btn.config(state=tk.NORMAL))

            threading.Thread(target=worker, daemon=True).start()

        fetch_btn.config(command=fetch_location)

        def apply():
            val = var.get().strip().upper()
            if val and not is_valid_grid8(val):
                messagebox.showerror(_("dlg.invalid"),
                                     _("dlg.grid_invalid_hint"))
                return
            gui.core.grid = val
            gui.core.save_config()
            gui._update_grid_button()
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
        # Independent retention limits for the two log files.
        self.max_history_log_lines = 100
        self.max_status_log_lines = 100
        # Cached line counts for the two log files. Used by
        # _append_text_line to avoid calling readlines() on
        # every append; see the comment there.
        self._log_line_counts = {}

        self.core.set_callbacks(
            on_log=self._on_log,
            on_history=self._on_history,
            on_status=self._on_status,
            on_tx_task=self._on_tx_task,
            on_contact_updated=self._on_contact_updated,
            on_beacon_state=self._on_beacon_state,
            on_beacon_tx_request=self._on_beacon_tx_request,
            on_toast=self._on_toast,
        )

        self.tx_freq_var = tk.StringVar(value=str(self.core.tx_freq))
        self.preamble_noise_var = tk.BooleanVar(value=self.core.preamble_noise_enabled)
        self.time_var = tk.StringVar()

        self.contact_list = []
        self._beacon_tx_active = False

        self._build_ui()

        self.root.bind("<Configure>", self._on_window_resize)
        self.root.bind("<Button-3>", self._on_global_right_click)

        self._history_first_timestamp = {}

        self._load_history_log()
        self._load_status_log()

        self._update_clock()

        self.core.start_receiver()

        self._refresh_contact_list()

    def _center_window(self, window, parent=None):
        center_window(window, parent or self.root)

    def _on_global_right_click(self, event):
        # Dispatch the right-click to the menu of the clicked region.
        # Only the history view, the status view and the TX input
        # field open a context menu; clicks anywhere else are
        # ignored on purpose.
        widget = event.widget
        if widget is self.history_text:
            self._show_history_menu(event)
        elif widget is self.display_text:
            self._show_display_menu(event)
        elif widget is self.tx_data_entry:
            self._show_tx_menu(event)

    def _show_contacts_dialog(self):
        ContactsDialog(self)

    def _edit_callsign(self):
        CallsignDialog(self)

    def _edit_grid(self):
        GridDialog(self)

    def _update_grid_button(self):
        self.grid_btn.config(text=self.core.grid or _("gui.grid"))

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
        if current.strip():
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

    def _on_contact_updated(self, contact_list):
        self.root.after(0, lambda: self._refresh_contact_list())

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

    def _clear_beacon_input(self):
        """Clear the TX input field."""
        self.tx_data_entry.delete(0, tk.END)
        self._update_input_stats()

    def _update_led_status(self, is_tx):
        # Color-only indicator: TX green, RX black. No text is set.
        if is_tx:
            self.led_label.config(bg=COLOR_GREEN)
        else:
            self.led_label.config(bg=COLOR_BLACK)

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
        # LED (col 0) and About (col 4) are fixed narrow columns.
        # Callsign / grid / contacts share the remaining width equally.
        top_frame.columnconfigure(0, weight=0)
        top_frame.columnconfigure(1, weight=1)
        top_frame.columnconfigure(2, weight=1)
        top_frame.columnconfigure(3, weight=1)
        top_frame.columnconfigure(4, weight=0)

        # Color-only status indicator: no text, fixed narrow width.
        self.led_label = tk.Label(top_frame, text="", font=self.status_font,
                                  fg=COLOR_WHITE, bg=COLOR_BLACK, anchor="center",
                                  width=2)
        self.led_label.grid(row=0, column=0, sticky="nsew", padx=0, pady=0)

        self.callsign_btn = tk.Button(top_frame, text=self.core.callsign or _("gui.empty_callsign"),
                                      command=self._edit_callsign,
                                      bg=COLOR_BLUE, fg=COLOR_WHITE,
                                      font=self.button_font, relief="flat")
        self.callsign_btn.grid(row=0, column=1, sticky="nsew", padx=0, pady=0)

        self.grid_btn = tk.Button(top_frame, text=self.core.grid or _("gui.grid"),
                                  command=self._edit_grid,
                                  bg=COLOR_PURPLE, fg=COLOR_WHITE,
                                  font=self.button_font, relief="flat")
        self.grid_btn.grid(row=0, column=2, sticky="nsew", padx=0, pady=0)

        # Contacts button: U+1F465 (busts in silhouette).
        self.contacts_btn = tk.Button(top_frame, text=_("gui.contacts"),
                                      command=self._show_contacts_dialog,
                                      bg=COLOR_ORANGE, fg=COLOR_WHITE,
                                      font=self.button_font, relief="flat")
        self.contacts_btn.grid(row=0, column=3, sticky="nsew", padx=0, pady=0)

        # About button: info emoji, fixed narrow width.
        self.about_btn = tk.Button(top_frame, text="\u2139\ufe0f",
                                   command=self._show_about,
                                   bg=COLOR_TEAL, fg=COLOR_WHITE,
                                   font=self.button_font, relief="flat",
                                   width=3)
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

        tx_container = ttk.LabelFrame(vertical_container, text="", padding="5")
        tx_container.grid(row=2, column=0, sticky="ew", pady=2)
        tx_container.columnconfigure(0, weight=1)

        data_row = ttk.Frame(tx_container)
        data_row.grid(row=0, column=0, sticky=(tk.W, tk.E), padx=5, pady=5)
        data_row.columnconfigure(0, weight=1)

        # Beacon button: left-aligned, same size as the TX button.
        # Closed state: black background. Active state: green background.
        # Beacon button: U+1F4E1 (satellite antenna).
        self.beacon_btn = tk.Button(data_row, text="\U0001F4E1", command=self._toggle_beacon,
                                    width=4, bg=COLOR_BLACK, fg=COLOR_WHITE,
                                    relief="raised", font=self.button_font)
        self.beacon_btn.pack(side=tk.LEFT, padx=2)

        self.tx_data_entry = ttk.Entry(data_row, width=50, font=self.label_font)
        self.tx_data_entry.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)

        # Transmit button: Green background + TX symbol, same width as beacon.
        # The label switches between SYMBOL_TX and SYMBOL_STOP in
        # _update_tx_button(); the background color is unchanged.
        self.tx_action_btn = tk.Button(data_row, text=SYMBOL_TX, command=self._on_tx_action,
                                       width=3, bg=COLOR_GREEN, fg=COLOR_WHITE, relief="raised",
                                       font=self.button_font)
        self.tx_action_btn.pack(side=tk.RIGHT, padx=2)

        self.tx_data_entry.bind("<KeyRelease>", self._update_input_stats)

        self.tx_context_menu = tk.Menu(self.root, tearoff=0)
        self.tx_context_menu.add_command(label=_("dlg.copy"), command=self._tx_copy)
        self.tx_context_menu.add_command(label=_("menu.paste"), command=self._tx_paste)
        self.tx_context_menu.add_command(label=_("menu.clear"), command=self._tx_clear)

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
        # Always copy the full input text, ignoring any selection.
        text = self.tx_data_entry.get()
        if text:
            self.root.clipboard_clear()
            self.root.clipboard_append(text)

    def _tx_paste(self):
        try:
            clipboard = self.root.clipboard_get()
            if clipboard:
                self.tx_data_entry.delete(0, tk.END)
                self.tx_data_entry.insert(0, clipboard)
                self._update_input_stats()
        except tk.TclError:
            pass

    def _tx_clear(self):
        self.tx_data_entry.delete(0, tk.END)
        self._update_input_stats()

    def _update_tx_button(self, is_active):
        if is_active:
            # Stop: Red background, stop symbol
            self.tx_action_btn.config(text=SYMBOL_STOP, bg=COLOR_RED)
        else:
            # Transmit: Green background, TX symbol
            self.tx_action_btn.config(text=SYMBOL_TX, bg=COLOR_GREEN)

    def _on_tx_action(self):
        if self.core.is_transmitting:
            self.core.stop_transmit()
        else:
            data = self.tx_data_entry.get().strip()
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

        # Beacon payload is the location message (C2+C37+G31 packed
        # into 13 Base42 chars). Requires a valid callsign and a
        # non-empty 8-char Maidenhead grid.
        if not is_valid_callsign(self.core.callsign):
            messagebox.showwarning(_("dlg.invalid_callsign"),
                                   _("dlg.callsign_required_beacon"))
            return
        if not self.core.grid or not is_valid_grid8(self.core.grid):
            messagebox.showwarning(_("dlg.invalid"),
                                   _("dlg.grid_required_beacon"))
            return
        beacon_text = pack_location_message(self.core.callsign,
                                            self.core.grid)
        if beacon_text is None:
            messagebox.showwarning(_("dlg.invalid"),
                                   _("dlg.grid_required_beacon"))
            return

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
        
        # Only save to disk if the frequency was actually changed.
        if self.core.tx_freq != val:
            self.core.tx_freq = val
            self.core.save_config()

    def _update_input_stats(self, event=None):
        data = self.tx_data_entry.get()
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
            # Only keep the last N lines; avoid loading the whole file.
            with open(self.history_log_path, 'r', encoding='utf-8') as f:
                lines = deque(f, maxlen=self.max_history_log_lines)
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

        # Beacon entries render "CALL GRID"; legacy "<CALL> PLUS"
        # entries fall back to displaying the callsign only.
        loc_grid = None
        loc_call = None
        if entry.marker == MARKER_BEACON:
            parts = entry.text.strip().split() if entry.text else []
            if (len(parts) == 2 and is_valid_callsign(parts[0])
                    and is_valid_grid8(parts[1].upper())):
                display_text = f"{parts[0]} {parts[1]}"
                loc_grid = parts[1]
                loc_call = parts[0]
            else:
                if entry.direction == 'recv':
                    display_text = entry.source_callsign or entry.text or "?"
                else:
                    display_text = self.core.callsign or entry.text or "?"
        else:
            display_text = entry.text

        for line in self._wrap_text(display_text, 60):
            insert_text(line + "\n", (content_tag, tag_name))

        end_pos = self.history_text.index(f"{start_pos} + {total_chars} chars")
        self.history_text.tag_add(align_tag, start_pos, end_pos)
        self.history_text.tag_raise(align_tag)

        if loc_grid is not None:
            loc_tag = f"loc_{entry.session_id}"
            self.history_text.tag_add(loc_tag, start_pos, end_pos)
            self.history_text.tag_bind(
                loc_tag, "<Button-1>",
                lambda e, g=loc_grid, c=loc_call:
                    self._open_location(g, c))
            self.history_text.tag_bind(
                loc_tag, "<Enter>",
                lambda e: self.history_text.config(cursor="hand2"))
            self.history_text.tag_bind(
                loc_tag, "<Leave>",
                lambda e: self.history_text.config(cursor=""))

        if is_me_involved and not is_recv_fail:
            self.history_text.tag_add("self_highlight", start_pos, end_pos)
            self.history_text.tag_raise("self_highlight")

        self.history_text.config(state=tk.DISABLED)
        self.history_text.see(tk.END)


    def _open_location(self, grid, label=None, event=None):
        try:
            lat, lon = grid8_to_lat_lon(grid)
            lat_f = float(lat)
            lon_f = float(lon)
        except Exception as e:
            self._insert_log(_("gui.invalid_grid", grid=grid, e=e), "error")
            return

        geo_uri = f"geo:{lat_f:.6f},{lon_f:.6f}"
        import subprocess
        import webbrowser

        opened = False
        if sys.platform.startswith("win"):
            has_real_handler = False
            try:
                import winreg
                with winreg.OpenKey(
                        winreg.HKEY_CLASSES_ROOT,
                        r"geo\shell\open\command") as key:
                    value, _ = winreg.QueryValueEx(key, "")
                    if (value
                            and "ms-windows-store" not in value.lower()
                            and "windows.applicationmodel.store"
                            not in value.lower()):
                        has_real_handler = True
            except Exception:
                pass
            if has_real_handler:
                try:
                    os.startfile(geo_uri)
                    opened = True
                except Exception:
                    opened = False
        elif sys.platform == "darwin":
            try:
                subprocess.Popen(["open", geo_uri],
                                 stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL)
                opened = True
            except Exception:
                opened = False
        else:
            try:
                subprocess.Popen(["xdg-open", geo_uri],
                                 stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL)
                opened = True
            except Exception:
                opened = False

        if not opened:
            # Bing treats `q=lat,lon` as a search query, rewrites it
            # to `search?q=...`, and drops the marker. Use `cp` for
            # the map center and `sp=point.*` for the actual pin.
            # The pin label is the beacon callsign.
            marker_label = (label or "MyPoint").strip() or "MyPoint"
            bing_url = (
                "https://cn.bing.com/maps"
                f"?cp={lat_f:.6f}~{lon_f:.6f}"
                "&lvl=14"
                f"&sp=point.{lat_f:.6f}_{lon_f:.6f}_{marker_label}")
            webbrowser.open(bing_url)

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
        # Always copy the full history text, ignoring any selection.
        text = self.history_text.get("1.0", tk.END)
        if text:
            self.root.clipboard_clear()
            self.root.clipboard_append(text)

    def _clear_history(self):
        self.core.history_entries.clear()
        self._history_first_timestamp.clear()
        self._refresh_history_display()
        # Truncate the history file to 0 bytes; keep the file itself
        # so subsequent appends do not fail.
        try:
            with open(self.history_log_path, 'w', encoding='utf-8'):
                pass
            # Reset the cached line count to zero after truncating.
            self._log_line_counts[self.history_log_path] = 0
        except Exception as e:
            self._insert_log(_("gui.history_delete_failed", e=e), "error")
        self._insert_log(_("gui.history_cleared"), "info")

# -----------------------------------------------------------------------------
# LogViewMixin (from gui_log_view.py)
# -----------------------------------------------------------------------------
class LogViewMixin:
    def _append_text_line(self, path, line):
        # History and status logs use independent retention limits.
        if path == self.history_log_path:
            max_lines = self.max_history_log_lines
        else:
            max_lines = self.max_status_log_lines
        # Trim with hysteresis and a cached line count. The
        # original version called readlines() and rewrote the
        # whole file on every append once the limit was hit,
        # which made every TX/RX entry cost O(N) disk I/O.
        # This version only rewrites after count exceeds
        # max_lines + trim_batch, so the cost is amortized
        # O(1) per append.
        trim_batch = max(50, max_lines // 10)
        try:
            count = self._log_line_counts.get(path)
            if count is None:
                # Treat a missing log file as an empty file. The following
                # 'a' mode open will create it automatically.
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        count = sum(1 for _ in f)
                except FileNotFoundError:
                    count = 0
            with open(path, 'a', encoding='utf-8') as f:
                f.write(line + '\n')
            count += 1
            if count > max_lines + trim_batch:
                with open(path, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
                lines = lines[-max_lines:]
                with open(path, 'w', encoding='utf-8') as f:
                    f.writelines(lines)
                count = len(lines)
            self._log_line_counts[path] = count
        except Exception:
            # Do not use print() here. sys.stdout may be redirected to
            # the UI log, and printing could trigger an infinite loop
            # of error messages if the file keeps failing to write.
            pass

    def _append_status_log(self, msg):
        self._append_text_line(self.status_log_path, msg)

    def _load_status_log(self):
        if not os.path.exists(self.status_log_path):
            return
        try:
            # Only keep the last N lines; avoid loading the whole file.
            with open(self.status_log_path, 'r', encoding='utf-8') as f:
                lines = deque(f, maxlen=self.max_status_log_lines)
            if lines:
                self.display_text.config(state=tk.NORMAL)
                for line in lines:
                    self.display_text.insert(tk.END, line)
                self.display_text.config(state=tk.DISABLED)
                self.display_text.see(tk.END)
        except Exception as e:
            print(f"Failed to load status log: {e}")

    def _insert_log(self, msg, tag, write_to_file=True):
        if msg and not msg.startswith('['):
            corrected_now = self.core.get_corrected_utc_now()
            timestamp = corrected_now.strftime("%Y-%m-%d %H:%M:%S")
            msg = f"[{timestamp}] {msg}"

        self.display_text.config(state=tk.NORMAL)
        self.display_text.insert(tk.END, msg + "\n", tag)
        self.display_text.see(tk.END)
        # Batch trimming: only delete head lines after the total
        # line count exceeds max_lines + trim_batch. The
        # original loop called index('end-1c') and
        # delete("1.0", "2.0") on every append, both of which
        # are O(total length) in Tk Text and cause visible
        # jank once the buffer fills up. This version deletes
        # a whole batch at once, amortizing the cost.
        max_lines = self.core.fixed_max_messages
        trim_batch = max(50, max_lines // 10)
        try:
            line_count = int(self.display_text.index('end-1c').split('.')[0])
            if line_count > max_lines + trim_batch:
                excess = line_count - max_lines
                self.display_text.delete("1.0", f"{excess + 1}.0")
        except Exception:
            pass
        self.display_text.config(state=tk.DISABLED)

        if write_to_file:
            self._append_status_log(msg)

    def _show_display_menu(self, event):
        try:
            self.display_context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.display_context_menu.grab_release()

    def _copy_display(self):
        # Always copy the full status text, ignoring any selection.
        text = self.display_text.get("1.0", tk.END)
        if text:
            self.root.clipboard_clear()
            self.root.clipboard_append(text)

    def _clear_display(self):
        self.display_text.config(state=tk.NORMAL)
        self.display_text.delete("1.0", tk.END)
        self.display_text.config(state=tk.DISABLED)
        # Truncate the status file to 0 bytes; keep the file itself
        # so subsequent appends do not fail.
        try:
            with open(self.status_log_path, 'w', encoding='utf-8'):
                pass
            # Reset the cached line count to zero after truncating.
            self._log_line_counts[self.status_log_path] = 0
        except Exception as e:
            self.display_text.config(state=tk.NORMAL)
            self.display_text.insert(tk.END, _("gui.status_delete_failed", e=e) + "\n", "error")
            self.display_text.config(state=tk.DISABLED)
        # Show the "cleared" notice in the UI only; it must not be
        # written to status.txt so the file stays strictly empty.
        self._insert_log(_("gui.status_cleared"), "info", write_to_file=False)

# -----------------------------------------------------------------------------
# GUI assembly (from gui.py)
# -----------------------------------------------------------------------------
class GUI(CallbacksMixin, BuilderMixin, TxInputMixin, HistoryViewMixin,
          LogViewMixin, GuiBase):
    """FT8 Plus GUI. Functionality is split across mixins."""
    pass

__all__ = ["GUI"]