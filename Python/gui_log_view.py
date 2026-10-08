# gui_log_view.py - LogViewMixin：状态日志显示
import os
import tkinter as tk

from i18n import _


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
                self.display_text.insert(tk.END, _("Failed to delete status file: {e}", e=e) + "\n", "error")
                self.display_text.config(state=tk.DISABLED)
        self._insert_log(_("Status cleared, deleted status.txt"), "info")

