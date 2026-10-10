# gui_dialogs.py - 独立对话框（呼号 / 联系人 / 关于）
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox

from i18n import _
from ft8_callsign import is_valid_callsign
from gui_theme import (
    COLOR_RED, COLOR_GREEN, COLOR_GRAY, COLOR_BLACK,
)


def center_window(window, parent):
    window.update_idletasks()
    w, h = window.winfo_width(), window.winfo_height()
    if w > 1 and h > 1:
        x = parent.winfo_x() + (parent.winfo_width() // 2) - (w // 2)
        y = parent.winfo_y() + (parent.winfo_height() // 2) - (h // 2)
        window.geometry(f"+{x}+{y}")


# ============ 联系人 ============

class ContactsDialog:
    def __init__(self, gui):
        self.gui = gui
        self.dialog = tk.Toplevel(gui.root)
        self.dialog.title(_("Contacts"))
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
        ttk.Button(btn_frame, text=_("New"),
                   command=self._add).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text=_("Edit"),
                   command=self._edit).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text=_("Delete"),
                   command=self._delete).pack(side=tk.LEFT, padx=5)
        self.listbox.bind("<Double-Button-1>", lambda e: self._select())

    def refresh(self):
        self.listbox.delete(0, tk.END)
        self.listbox.insert(tk.END, _("All"))
        for callsign, note in self.gui.contact_list:
            display = f"{callsign}, {note}" if note else callsign
            self.listbox.insert(tk.END, display)

    def _select(self):
        selection = self.listbox.curselection()
        if not selection:
            messagebox.showwarning(_("Info"), _("Please select a record first"))
            return
        idx = selection[0]
        if idx == 0:
            if not is_valid_callsign(self.gui.core.callsign):
                messagebox.showwarning(
                    _("Invalid Callsign"),
                    _("Current station callsign is invalid, cannot fill. Please update callsign first."))
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
        d.title(_("New Contact"))
        d.geometry("350x150")
        d.transient(self.gui.root)
        d.grab_set()
        center_window(d, self.gui.root)

        ttk.Label(d, text=_("Callsign:"), font=self.gui.label_font).grid(
            row=0, column=0, padx=10, pady=10, sticky="e")
        entry_callsign = ttk.Entry(d, width=20, font=self.gui.label_font)
        entry_callsign.grid(row=0, column=1, padx=10, pady=10)

        ttk.Label(d, text=_("Note:"), font=self.gui.label_font).grid(
            row=1, column=0, padx=10, pady=10, sticky="e")
        entry_note = ttk.Entry(d, width=20, font=self.gui.label_font)
        entry_note.grid(row=1, column=1, padx=10, pady=10)

        def confirm():
            callsign = entry_callsign.get().strip().upper()
            note = entry_note.get().strip()
            if not callsign:
                messagebox.showwarning(_("Warning"), _("Callsign cannot be empty"))
                return
            if not is_valid_callsign(callsign):
                messagebox.showwarning(
                    _("Warning"),
                    _("Invalid callsign format (must be 3~7 chars, with at least one digit)"))
                return
            if self.gui.core.add_contact(callsign, note):
                self.gui._refresh_contact_list()
                self.refresh()
                d.destroy()
            else:
                messagebox.showwarning(
                    _("Warning"),
                    _("Add failed (limit reached or callsign exists)"))

        bf = ttk.Frame(d)
        bf.grid(row=2, column=0, columnspan=2, pady=10)
        ttk.Button(bf, text=_("OK"), command=confirm, width=8).pack(side=tk.LEFT, padx=5)
        ttk.Button(bf, text=_("Cancel"), command=d.destroy, width=8).pack(side=tk.LEFT, padx=5)
        entry_callsign.focus_set()

    def _edit(self):
        selection = self.listbox.curselection()
        if not selection:
            messagebox.showwarning(_("Info"), _("Please select a contact to edit"))
            return
        idx = selection[0]
        if idx == 0:
            messagebox.showinfo(_("Info"), _("\"All\" is fixed, cannot edit"))
            return
        real_idx = idx - 1
        if real_idx < 0 or real_idx >= len(self.gui.contact_list):
            return
        callsign, note = self.gui.contact_list[real_idx]

        d = tk.Toplevel(self.gui.root)
        d.title(_("Edit Contact"))
        d.geometry("350x150")
        d.transient(self.gui.root)
        d.grab_set()
        center_window(d, self.gui.root)

        ttk.Label(d, text=_("Callsign:"), font=self.gui.label_font).grid(
            row=0, column=0, padx=10, pady=10, sticky="e")
        entry_callsign = ttk.Entry(d, width=20, font=self.gui.label_font)
        entry_callsign.insert(0, callsign)
        entry_callsign.grid(row=0, column=1, padx=10, pady=10)

        ttk.Label(d, text=_("Note:"), font=self.gui.label_font).grid(
            row=1, column=0, padx=10, pady=10, sticky="e")
        entry_note = ttk.Entry(d, width=20, font=self.gui.label_font)
        entry_note.insert(0, note)
        entry_note.grid(row=1, column=1, padx=10, pady=10)

        def confirm():
            new_callsign = entry_callsign.get().strip().upper()
            new_note = entry_note.get().strip()
            if not new_callsign:
                messagebox.showwarning(_("Warning"), _("Callsign cannot be empty"))
                return
            if not is_valid_callsign(new_callsign):
                messagebox.showwarning(
                    _("Warning"),
                    _("Invalid callsign format (must be 3~7 chars, with at least one digit)"))
                return
            if self.gui.core.update_contact(real_idx, new_callsign, new_note):
                self.gui._refresh_contact_list()
                self.refresh()
                d.destroy()
            else:
                messagebox.showwarning(_("Warning"),
                                       _("Update failed (callsign may exist)"))

        bf = ttk.Frame(d)
        bf.grid(row=2, column=0, columnspan=2, pady=10)
        ttk.Button(bf, text=_("OK"), command=confirm, width=8).pack(side=tk.LEFT, padx=5)
        ttk.Button(bf, text=_("Cancel"), command=d.destroy, width=8).pack(side=tk.LEFT, padx=5)
        entry_callsign.focus_set()
        entry_callsign.select_range(0, tk.END)

    def _delete(self):
        selection = self.listbox.curselection()
        if not selection:
            messagebox.showwarning(_("Info"), _("Please select a contact to delete"))
            return
        idx = selection[0]
        if idx == 0:
            messagebox.showinfo(_("Info"), _("\"All\" is fixed, cannot delete"))
            return
        real_idx = idx - 1
        if real_idx < 0 or real_idx >= len(self.gui.contact_list):
            return
        callsign, _note = self.gui.contact_list[real_idx]
        if messagebox.askyesno(_("Confirm Delete"),
                               _("Delete contact {callsign}?", callsign=callsign)):
            if self.gui.core.delete_contact(real_idx):
                self.gui._refresh_contact_list()
                self.refresh()
            else:
                messagebox.showwarning(_("Info"), _("Delete failed"))


# ============ 呼号设置 ============

class CallsignDialog:
    def __init__(self, gui):
        self.gui = gui
        d = tk.Toplevel(gui.root)
        d.title(_("Set Callsign"))
        d.geometry("400x230")
        d.transient(gui.root)
        d.grab_set()
        center_window(d, gui.root)

        ttk.Label(d, text=_("Enter your callsign"), font=gui.label_font).pack(pady=(10, 0))
        ttk.Label(d,
                  text=_("Format: 3~7 chars, contains at least one digit, letters/digits only"),
                  font=gui.label_font, foreground=COLOR_GRAY).pack()

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
                messagebox.showerror(_("Invalid"),
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
        ttk.Button(bf, text=_("OK"), command=apply, width=8).pack(side=tk.LEFT, padx=5)
        ttk.Button(bf, text=_("Cancel"), command=d.destroy, width=8).pack(side=tk.LEFT, padx=5)
        entry.focus_set()
        update()


# ============ 关于 ============

class AboutDialog:
    def __init__(self, gui):
        d = tk.Toplevel(gui.root)
        d.title(_("About FT8 Plus 1.0 Protocol Demo"))
        d.geometry("680x540")
        d.transient(gui.root)
        d.grab_set()
        center_window(d, gui.root)

        frame = ttk.Frame(d, padding="10")
        frame.pack(fill=tk.BOTH, expand=True)
        text = scrolledtext.ScrolledText(frame, wrap=tk.WORD, font=gui.label_font)
        text.pack(fill=tk.BOTH, expand=True)
        text.insert("1.0", _("about.text"))
        text.config(state=tk.DISABLED)

        bf = ttk.Frame(frame)
        bf.pack(fill=tk.X, pady=(8, 0))

        def copy_about():
            gui.root.clipboard_clear()
            gui.root.clipboard_append(text.get("1.0", tk.END))

        ttk.Button(bf, text=_("Copy"), command=copy_about, width=10).pack(side=tk.RIGHT, padx=5)
        ttk.Button(bf, text=_("Cancel"), command=d.destroy, width=10).pack(side=tk.RIGHT)
