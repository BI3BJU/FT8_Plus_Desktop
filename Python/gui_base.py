# gui_base.py - GuiBase：__init__ / 入口 / 时钟
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk, scrolledtext, messagebox

from i18n import _
from gui_theme import resource_path
from gui_dialogs import ContactsDialog, CallsignDialog, AboutDialog, center_window


class GuiBase:
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
            on_beacon_fill=self._on_beacon_fill,
            on_beacon_clear=self._on_beacon_clear,
            on_beacon_state=self._on_beacon_state,
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
            self.slot_var.set(_("Slot: {x}s / {y}s", x=f"{time_in_cycle:.1f}", y=cycle))
            if wait < 0.1:
                self.next_tx_var.set(_("Transmit now!"))
            else:
                self.next_tx_var.set(f"{wait:.1f}s")
        self.root.after(200, self._update_slot_timer)

