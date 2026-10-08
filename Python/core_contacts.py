# core_contacts.py - ContactsMixin：联系人管理
import os

from i18n import _
from ft8_constants import MAX_CONTACTS, MAX_NOTE_BYTES
from ft8_callsign import is_valid_callsign


class ContactsMixin:
    def _load_contacts(self):
        self.contact_list = []
        if os.path.exists(self.contact_file):
            try:
                with open(self.contact_file, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if line and ',' in line:
                            parts = line.split(',', 1)
                            callsign = parts[0].strip()
                            note = parts[1].strip() if len(parts) > 1 else ""
                            if callsign:
                                self.contact_list.append((callsign, note))
                if len(self.contact_list) > MAX_CONTACTS:
                    self.contact_list = self.contact_list[:MAX_CONTACTS]
            except Exception as e:
                print(_("Load contacts error: {e}", e=e))
                self._safe_call('on_toast', _("Load contacts failed: {e}", e=e), "error")

    def _save_contacts(self):
        try:
            with open(self.contact_file, 'w', encoding='utf-8') as f:
                for callsign, note in self.contact_list[:MAX_CONTACTS]:
                    f.write(f"{callsign},{note}\n")
        except Exception as e:
            self._safe_call('on_log', _("Save contacts failed: {e}", e=e), "error")
            self._safe_call('on_toast', _("Save contacts failed: {e}", e=e), "error")

    def _contact_exists(self, callsign):
        callsign = callsign.strip().upper()
        for c, _note in self.contact_list:
            if c == callsign:
                return True
        return False

    def _add_contact(self, callsign, note=""):
        callsign = callsign.strip().upper()
        if not callsign or not is_valid_callsign(callsign):
            self._safe_call('on_toast', _("Callsign {call} invalid", call=callsign), "warning")
            return False
        if self._contact_exists(callsign):
            return True
        if len(self.contact_list) >= MAX_CONTACTS:
            self._safe_call('on_log',
                            _("Contact limit {n} reached, cannot add {call}",
                              n=MAX_CONTACTS, call=callsign),
                            "error")
            self._safe_call('on_toast',
                            _("Contact limit {n} reached", n=MAX_CONTACTS),
                            "error")
            return False
        note_encoded = note.encode('utf-8')
        if len(note_encoded) > MAX_NOTE_BYTES:
            note = note_encoded[:MAX_NOTE_BYTES].decode('utf-8', errors='ignore')
            self._safe_call('on_log',
                            _("Note too long, truncated to {n} bytes", n=MAX_NOTE_BYTES),
                            "warning")
        self.contact_list.append((callsign, note.strip()))
        self._save_contacts()
        self._safe_call('on_contact_updated', self.contact_list)
        self._safe_call('on_toast', _("Added contact {call}", call=callsign), "info")
        return True

    def add_contact(self, callsign, note=""):
        return self._add_contact(callsign, note)

    def delete_contact(self, index):
        if 0 <= index < len(self.contact_list):
            callsign = self.contact_list[index][0]
            del self.contact_list[index]
            self._save_contacts()
            self._safe_call('on_contact_updated', self.contact_list)
            self._safe_call('on_toast', _("Deleted contact {call}", call=callsign), "info")
            return True
        return False

    def update_contact(self, index, new_callsign, new_note):
        if 0 <= index < len(self.contact_list):
            new_callsign = new_callsign.strip().upper()
            if not is_valid_callsign(new_callsign):
                self._safe_call('on_toast',
                                _("Callsign {call} invalid", call=new_callsign),
                                "warning")
                return False
            for i, (c, _note) in enumerate(self.contact_list):
                if i != index and c == new_callsign:
                    self._safe_call('on_toast',
                                    _("Callsign {call} already exists", call=new_callsign),
                                    "warning")
                    return False
            note_encoded = new_note.encode('utf-8')
            if len(note_encoded) > MAX_NOTE_BYTES:
                new_note = note_encoded[:MAX_NOTE_BYTES].decode('utf-8', errors='ignore')
                self._safe_call('on_log',
                                _("Note too long, truncated to {n} bytes", n=MAX_NOTE_BYTES),
                                "warning")
            self.contact_list[index] = (new_callsign, new_note.strip())
            self._save_contacts()
            self._safe_call('on_contact_updated', self.contact_list)
            self._safe_call('on_toast', _("Updated contact {call}", call=new_callsign), "info")
            return True
        return False

    def get_contacts(self):
        return self.contact_list.copy()

    # ---------- Helpers ----------
    def _find_contact_note(self, callsign):
        if not callsign:
            return None
        target = callsign.strip().upper()
        for c, note in self.contact_list:
            if c.strip().upper() == target:
                return note or None
        return None

    def _auto_save_source_contact(self, callsign):
        if not callsign or self._contact_exists(callsign):
            return
        date_str = self.get_corrected_utc_now().strftime("%Y-%m-%d")
        note = _("Auto-added at {date}", date=date_str)
        if self._add_contact(callsign, note):
            self._safe_call('on_log',
                            _("Auto-saved contact: {call} (from received msg start)",
                              call=callsign),
                            "auto_contact")
            self._safe_call('on_toast',
                            _("Auto-saved contact: {call}", call=callsign),
                            "info")

    # ---------- History management ----------
